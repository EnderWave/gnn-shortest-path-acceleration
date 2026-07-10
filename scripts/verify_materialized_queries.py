"""Paired full-workload verification for materialized compression graphs."""

from __future__ import annotations

import argparse
import csv
import math
import multiprocessing
import os
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from src.compression_index import CompressionIndex, build_compression_index
from src.graph_io import load_porto_graph
from src.indexed_query import indexed_bidirectional_dijkstra_distance
from src.regions import build_hotspot_regions, build_random_regions
from src.shortest_path import bidirectional_dijkstra_distance
from src.workloads import load_porto_queries


DEFAULT_NODE_CSV = ROOT_DIR / "data" / "processed" / "porto" / "波尔图道路节点.csv"
DEFAULT_EDGE_CSV = ROOT_DIR / "data" / "processed" / "porto" / "波尔图道路边.csv"
DEFAULT_QUERY_CSV = ROOT_DIR / "data" / "processed" / "porto" / "波尔图可用起终点节点查询_200米.csv"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "results" / "regions"

_WORKER_GRAPH = None
_WORKER_INDEX: CompressionIndex | None = None


@dataclass(frozen=True, slots=True)
class PairedVerificationRow:
    method: str
    query_count: int
    region_count: int
    shortcut_count: int
    compressed_node_count: int
    compressed_edge_count: int
    fallback_query_count: int
    fallback_rate_pct: float
    preprocessing_seconds: float
    baseline_avg_ms: float
    indexed_avg_ms: float
    elapsed_change_pct: float
    baseline_p95_ms: float
    indexed_p95_ms: float
    p95_change_pct: float
    baseline_avg_expanded: float
    indexed_avg_expanded: float
    expanded_change_pct: float
    faster_query_rate_pct: float
    median_delta_ms: float
    correctness_rate: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify materialized compression with paired queries.")
    parser.add_argument("--node-csv", type=Path, default=DEFAULT_NODE_CSV)
    parser.add_argument("--edge-csv", type=Path, default=DEFAULT_EDGE_CSV)
    parser.add_argument("--query-csv", type=Path, default=DEFAULT_QUERY_CSV)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--region-count", type=int, default=200)
    parser.add_argument("--region-size", type=int, default=512)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    graph = load_porto_graph(args.node_csv, args.edge_csv)
    queries = load_porto_queries(args.query_csv, limit=args.limit)
    strategies = [
        ("random_bfs", lambda: build_random_regions(graph, args.region_count, args.region_size, args.seed)),
        ("od_hotspot_bfs", lambda: build_hotspot_regions(graph, queries, args.region_count, args.region_size)),
    ]

    summaries: list[PairedVerificationRow] = []
    all_details: list[dict[str, str]] = []
    for method, build_regions in strategies:
        print(f"preprocessing {method}", flush=True)
        preprocessing_start = time.perf_counter()
        index = build_compression_index(graph, build_regions())
        preprocessing_seconds = time.perf_counter() - preprocessing_start
        fallback_query_count = sum(
            index.requires_original_graph(query.origin, query.destination)
            for query in queries
        )
        print(
            f"paired evaluation {method}: workers={args.workers}, "
            f"fallback={fallback_query_count:,}/{len(queries):,}",
            flush=True,
        )
        metrics, details = evaluate_paired(
            graph,
            index,
            queries,
            method,
            args.workers,
            args.chunk_size,
        )
        all_details.extend(details)
        row = PairedVerificationRow(
            method=method,
            query_count=len(queries),
            region_count=index.region_count,
            shortcut_count=index.shortcut_count,
            compressed_node_count=index.compressed_graph.node_count,
            compressed_edge_count=index.compressed_graph.edge_count,
            fallback_query_count=fallback_query_count,
            fallback_rate_pct=fallback_query_count / len(queries) * 100.0,
            preprocessing_seconds=preprocessing_seconds,
            baseline_avg_ms=_mean(metrics["baseline_elapsed"]),
            indexed_avg_ms=_mean(metrics["indexed_elapsed"]),
            elapsed_change_pct=_change_pct(
                _mean(metrics["indexed_elapsed"]),
                _mean(metrics["baseline_elapsed"]),
            ),
            baseline_p95_ms=_percentile(metrics["baseline_elapsed"], 95),
            indexed_p95_ms=_percentile(metrics["indexed_elapsed"], 95),
            p95_change_pct=_change_pct(
                _percentile(metrics["indexed_elapsed"], 95),
                _percentile(metrics["baseline_elapsed"], 95),
            ),
            baseline_avg_expanded=_mean(metrics["baseline_expanded"]),
            indexed_avg_expanded=_mean(metrics["indexed_expanded"]),
            expanded_change_pct=_change_pct(
                _mean(metrics["indexed_expanded"]),
                _mean(metrics["baseline_expanded"]),
            ),
            faster_query_rate_pct=(
                sum(delta < 0 for delta in metrics["elapsed_deltas"])
                / len(queries)
                * 100.0
            ),
            median_delta_ms=statistics.median(metrics["elapsed_deltas"]),
            correctness_rate=sum(metrics["correct_values"]) / len(queries),
        )
        summaries.append(row)
        print(
            f"{method}: baseline={row.baseline_avg_ms:.3f} ms, "
            f"indexed={row.indexed_avg_ms:.3f} ms, "
            f"change={row.elapsed_change_pct:.2f}%, "
            f"correctness={row.correctness_rate:.6f}",
            flush=True,
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"porto_{len(queries)}queries_r{args.region_count}_s{args.region_size}_paired"
    summary_path = args.output_dir / f"{suffix}_summary.csv"
    details_path = args.output_dir / f"{suffix}_details.csv"
    report_path = args.output_dir / f"{suffix}_final_report.md"
    write_summary(summary_path, summaries)
    write_details(details_path, all_details)
    write_report(report_path, summaries)
    print(f"summary={_display_path(summary_path)}")
    print(f"details={_display_path(details_path)}")
    print(f"report={_display_path(report_path)}")


def evaluate_paired(
    graph,
    index: CompressionIndex,
    queries,
    method: str,
    workers: int,
    chunk_size: int,
) -> tuple[dict[str, list], list[dict[str, str]]]:
    chunks = list(_chunked(queries, max(1, chunk_size)))
    results = []
    if workers <= 1:
        _init_worker(graph, index)
        results = [_evaluate_pair_chunk(method, chunk) for chunk in chunks]
    else:
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_worker,
            initargs=(graph, index),
            mp_context=_process_context(),
        ) as pool:
            futures = [pool.submit(_evaluate_pair_chunk, method, chunk) for chunk in chunks]
            for done, future in enumerate(as_completed(futures), start=1):
                results.append(future.result())
                if done == len(futures) or done % 10 == 0:
                    print(f"{method}: completed {done}/{len(futures)} paired chunks", flush=True)

    metrics = {
        "baseline_elapsed": [],
        "indexed_elapsed": [],
        "elapsed_deltas": [],
        "baseline_expanded": [],
        "indexed_expanded": [],
        "correct_values": [],
    }
    details: list[dict[str, str]] = []
    for partial in results:
        details.extend(partial.pop("details"))
        for key in metrics:
            metrics[key].extend(partial[key])
    return metrics, details


def _init_worker(graph, index: CompressionIndex) -> None:
    global _WORKER_GRAPH, _WORKER_INDEX
    _WORKER_GRAPH = graph
    _WORKER_INDEX = index


def _evaluate_pair_chunk(method: str, queries) -> dict[str, list]:
    if _WORKER_GRAPH is None or _WORKER_INDEX is None:
        raise RuntimeError("worker was not initialized")

    output = {
        "baseline_elapsed": [],
        "indexed_elapsed": [],
        "elapsed_deltas": [],
        "baseline_expanded": [],
        "indexed_expanded": [],
        "correct_values": [],
        "details": [],
    }
    for query in queries:
        if query.query_id % 2 == 0:
            indexed = indexed_bidirectional_dijkstra_distance(
                _WORKER_GRAPH, _WORKER_INDEX, query.origin, query.destination
            )
            baseline = bidirectional_dijkstra_distance(
                _WORKER_GRAPH, query.origin, query.destination
            )
            order = "indexed_first"
        else:
            baseline = bidirectional_dijkstra_distance(
                _WORKER_GRAPH, query.origin, query.destination
            )
            indexed = indexed_bidirectional_dijkstra_distance(
                _WORKER_GRAPH, _WORKER_INDEX, query.origin, query.destination
            )
            order = "baseline_first"

        correct = _same_distance(baseline.distance, indexed.distance)
        delta = indexed.elapsed_ms - baseline.elapsed_ms
        output["baseline_elapsed"].append(baseline.elapsed_ms)
        output["indexed_elapsed"].append(indexed.elapsed_ms)
        output["elapsed_deltas"].append(delta)
        output["baseline_expanded"].append(baseline.expanded_nodes)
        output["indexed_expanded"].append(indexed.expanded_nodes)
        output["correct_values"].append(int(correct))
        output["details"].append(
            {
                "method": method,
                "query_id": str(query.query_id),
                "origin": str(query.origin),
                "destination": str(query.destination),
                "query_graph": (
                    "original"
                    if _WORKER_INDEX.requires_original_graph(query.origin, query.destination)
                    else "compressed"
                ),
                "execution_order": order,
                "baseline_ms": f"{baseline.elapsed_ms:.6f}",
                "indexed_ms": f"{indexed.elapsed_ms:.6f}",
                "delta_ms": f"{delta:.6f}",
                "baseline_expanded": str(baseline.expanded_nodes),
                "indexed_expanded": str(indexed.expanded_nodes),
                "correct": str(correct),
            }
        )
    return output


def write_summary(path: Path, rows: list[PairedVerificationRow]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(PairedVerificationRow.__dataclass_fields__))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: f"{value:.6f}" if isinstance(value, float) else value
                    for key, value in asdict(row).items()
                }
            )


def write_details(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_report(path: Path, rows: list[PairedVerificationRow]) -> None:
    success = any(row.elapsed_change_pct < 0 and row.correctness_rate == 1.0 for row in rows)
    lines = [
        "# 物化区域压缩图最终验证报告",
        "",
        f"结论：{'物化压缩图确实减少了平均在线查询开销' if success else '物化压缩图尚未减少平均在线查询开销'}。",
        "",
        "| 方法 | 基线平均耗时 | 压缩平均耗时 | 平均耗时变化 | P95 变化 | 展开节点变化 | 查询加速比例 | 正确率 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row.method} | {row.baseline_avg_ms:.3f} ms | {row.indexed_avg_ms:.3f} ms | "
            f"{row.elapsed_change_pct:.2f}% | {row.p95_change_pct:.2f}% | "
            f"{row.expanded_change_pct:.2f}% | {row.faster_query_rate_pct:.2f}% | "
            f"{row.correctness_rate:.6f} |"
        )
    lines.extend(
        [
            "",
            "验证方法：每个 OD 在同一工作进程内连续执行基线与压缩查询，并按查询编号奇偶交替执行顺序。计时只包含节点状态查询和最短路计算；全部离线预处理均不计入在线耗时。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _process_context():
    if os.name == "posix":
        return multiprocessing.get_context("fork")
    return multiprocessing.get_context()


def _chunked(values, chunk_size: int):
    for start in range(0, len(values), chunk_size):
        yield values[start : start + chunk_size]


def _same_distance(left: float, right: float, tolerance: float = 1e-6) -> bool:
    if math.isinf(left) or math.isinf(right):
        return math.isinf(left) and math.isinf(right)
    return abs(left - right) <= tolerance


def _mean(values: list[float] | list[int]) -> float:
    return sum(values) / len(values) if values else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile / 100.0
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _change_pct(new_value: float, old_value: float) -> float:
    return (new_value - old_value) / old_value * 100.0 if old_value else 0.0


def _display_path(path: Path) -> Path:
    try:
        return path.relative_to(ROOT_DIR)
    except ValueError:
        return path


if __name__ == "__main__":
    main()
