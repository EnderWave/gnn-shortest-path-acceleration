"""Run first-pass connected-region shortcut experiments on Porto."""

from __future__ import annotations

import argparse
import csv
import math
import multiprocessing
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from src.compression_index import build_compression_index
from src.evaluation import MethodSummary, write_detail_rows
from src.graph_io import load_porto_graph
from src.indexed_query import indexed_bidirectional_dijkstra_distance
from src.regions import build_hotspot_regions, build_random_regions
from src.shortest_path import ShortestPathResult, bidirectional_dijkstra_distance
from src.workloads import load_porto_queries


DEFAULT_NODE_CSV = ROOT_DIR / "data" / "processed" / "porto" / "波尔图道路节点.csv"
DEFAULT_EDGE_CSV = ROOT_DIR / "data" / "processed" / "porto" / "波尔图道路边.csv"
DEFAULT_QUERY_CSV = ROOT_DIR / "data" / "processed" / "porto" / "波尔图可用起终点节点查询_200米.csv"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "results" / "regions"
DEFAULT_BASELINE_SUMMARY = ROOT_DIR / "results" / "baselines" / "porto_allqueries_summary.csv"
DEFAULT_BASELINE_DETAILS = ROOT_DIR / "results" / "baselines" / "porto_allqueries_details.csv"

_WORKER_GRAPH = None
_WORKER_INDEX = None


@dataclass(frozen=True, slots=True)
class RegionExperimentRow:
    method: str
    query_count: int
    region_count: int
    region_size: int
    shortcut_count: int
    original_node_count: int
    compressed_node_count: int
    original_edge_count: int
    compressed_edge_count: int
    internal_node_count: int
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
    correctness_rate: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run connected-region shortcut experiments.")
    parser.add_argument("--node-csv", type=Path, default=DEFAULT_NODE_CSV)
    parser.add_argument("--edge-csv", type=Path, default=DEFAULT_EDGE_CSV)
    parser.add_argument("--query-csv", type=Path, default=DEFAULT_QUERY_CSV)
    parser.add_argument("--limit", type=int, default=None, help="Omit for all usable OD queries.")
    parser.add_argument("--region-count", type=int, default=80)
    parser.add_argument("--region-size", type=int, default=192)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--baseline-summary", type=Path, default=DEFAULT_BASELINE_SUMMARY)
    parser.add_argument("--baseline-details", type=Path, default=DEFAULT_BASELINE_DETAILS)
    parser.add_argument("--reuse-baseline", action="store_true", help="Reuse existing all-query baseline CSV files.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    graph = load_porto_graph(args.node_csv, args.edge_csv)
    queries = load_porto_queries(args.query_csv, limit=args.limit)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.reuse_baseline and args.limit is None and args.baseline_summary.exists() and args.baseline_details.exists():
        print("loading existing all-query bidirectional baseline", flush=True)
        baseline_summary, baseline_rows, reference_distances = load_existing_baseline(
            args.baseline_summary,
            args.baseline_details,
            len(queries),
        )
    else:
        print(f"evaluating baseline with {args.workers} workers", flush=True)
        baseline_summary, baseline_rows = evaluate_method_parallel(
            graph,
            queries,
            "bidirectional_dijkstra",
            reference_distances=None,
            workers=args.workers,
            chunk_size=args.chunk_size,
        )
        reference_distances = {
            int(row["query_id"]): float("inf") if row["distance_m"] == "inf" else float(row["distance_m"])
            for row in baseline_rows
        }

    experiment_rows: list[RegionExperimentRow] = []
    all_detail_rows = list(baseline_rows)

    strategy_builders = [
        ("random_bfs", lambda: build_random_regions(graph, args.region_count, args.region_size, args.seed)),
        ("od_hotspot_bfs", lambda: build_hotspot_regions(graph, queries, args.region_count, args.region_size)),
    ]

    for method_name, build_regions in strategy_builders:
        print(f"building regions: {method_name}", flush=True)
        preprocessing_start = time.perf_counter()
        regions = build_regions()
        index = build_compression_index(graph, regions)
        preprocessing_seconds = time.perf_counter() - preprocessing_start
        fallback_query_count = sum(
            index.requires_original_graph(query.origin, query.destination)
            for query in queries
        )
        print(
            f"{method_name}: materialized graph "
            f"nodes={index.compressed_graph.node_count:,}, "
            f"edges={index.compressed_graph.edge_count:,}, "
            f"fallback={fallback_query_count:,}/{len(queries):,}",
            flush=True,
        )
        indexed_summary, indexed_rows = evaluate_method_parallel(
            graph,
            queries,
            f"{method_name}_materialized",
            reference_distances=reference_distances,
            workers=args.workers,
            chunk_size=args.chunk_size,
            index=index,
        )
        all_detail_rows.extend(indexed_rows)
        row = RegionExperimentRow(
            method=method_name,
            query_count=len(queries),
            region_count=index.region_count,
            region_size=args.region_size,
            shortcut_count=index.shortcut_count,
            original_node_count=graph.node_count,
            compressed_node_count=index.compressed_graph.node_count,
            original_edge_count=graph.edge_count,
            compressed_edge_count=index.compressed_graph.edge_count,
            internal_node_count=index.internal_node_count,
            fallback_query_count=fallback_query_count,
            fallback_rate_pct=fallback_query_count / len(queries) * 100.0,
            preprocessing_seconds=preprocessing_seconds,
            baseline_avg_ms=baseline_summary.avg_elapsed_ms,
            indexed_avg_ms=indexed_summary.avg_elapsed_ms,
            elapsed_change_pct=_change_pct(indexed_summary.avg_elapsed_ms, baseline_summary.avg_elapsed_ms),
            baseline_p95_ms=baseline_summary.p95_elapsed_ms,
            indexed_p95_ms=indexed_summary.p95_elapsed_ms,
            p95_change_pct=_change_pct(indexed_summary.p95_elapsed_ms, baseline_summary.p95_elapsed_ms),
            baseline_avg_expanded=baseline_summary.avg_expanded_nodes,
            indexed_avg_expanded=indexed_summary.avg_expanded_nodes,
            expanded_change_pct=_change_pct(indexed_summary.avg_expanded_nodes, baseline_summary.avg_expanded_nodes),
            correctness_rate=indexed_summary.correctness_rate,
        )
        experiment_rows.append(row)
        print(
            f"{method_name}: shortcuts={index.shortcut_count:,}, "
            f"avg_ms={indexed_summary.avg_elapsed_ms:.3f}, "
            f"avg_expanded={indexed_summary.avg_expanded_nodes:.1f}, "
            f"correctness={indexed_summary.correctness_rate:.6f}",
            flush=True,
        )

    suffix = f"porto_{len(queries)}queries_r{args.region_count}_s{args.region_size}"
    summary_path = args.output_dir / f"{suffix}_summary.csv"
    detail_path = args.output_dir / f"{suffix}_details.csv"
    report_path = args.output_dir / f"{suffix}_report.md"
    write_experiment_summary(summary_path, experiment_rows)
    write_detail_rows(detail_path, all_detail_rows)
    write_report(report_path, experiment_rows)

    print(f"summary={_display_path(summary_path)}")
    print(f"details={_display_path(detail_path)}")
    print(f"report={_display_path(report_path)}")


def load_existing_baseline(
    summary_path: Path,
    detail_path: Path,
    expected_query_count: int,
) -> tuple[MethodSummary, list[dict[str, str]], dict[int, float]]:
    baseline_summary: MethodSummary | None = None
    with summary_path.open("r", encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            if row["method"] == "bidirectional_dijkstra":
                baseline_summary = MethodSummary(
                    method=row["method"],
                    query_count=int(row["query_count"]),
                    reachable_count=int(row["reachable_count"]),
                    unreachable_count=int(row["unreachable_count"]),
                    avg_elapsed_ms=float(row["avg_elapsed_ms"]),
                    p50_elapsed_ms=float(row["p50_elapsed_ms"]),
                    p95_elapsed_ms=float(row["p95_elapsed_ms"]),
                    avg_expanded_nodes=float(row["avg_expanded_nodes"]),
                    correctness_rate=float(row["correctness_rate"]),
                )
                break
    if baseline_summary is None:
        raise SystemExit(f"bidirectional_dijkstra was not found in {summary_path}")
    if baseline_summary.query_count != expected_query_count:
        raise SystemExit(
            f"baseline query count mismatch: {baseline_summary.query_count} != {expected_query_count}"
        )

    rows: list[dict[str, str]] = []
    references: dict[int, float] = {}
    with detail_path.open("r", encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            if row["method"] != "bidirectional_dijkstra":
                continue
            rows.append(row)
            references[int(row["query_id"])] = float("inf") if row["distance_m"] == "inf" else float(row["distance_m"])
    if len(rows) != expected_query_count:
        raise SystemExit(f"baseline detail row count mismatch: {len(rows)} != {expected_query_count}")
    return baseline_summary, rows, references


def evaluate_method_parallel(
    graph,
    queries,
    method_name: str,
    reference_distances: dict[int, float] | None,
    workers: int,
    chunk_size: int,
    index=None,
) -> tuple[MethodSummary, list[dict[str, str]]]:
    workers = max(1, workers)
    chunks = list(_chunked(queries, max(1, chunk_size)))
    if workers == 1:
        _init_worker(graph, index)
        results = [
            _evaluate_chunk(method_name, chunk, _reference_subset(chunk, reference_distances))
            for chunk in chunks
        ]
    else:
        results = []
        context = _process_context()
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_worker,
            initargs=(graph, index),
            mp_context=context,
        ) as pool:
            futures = [
                pool.submit(_evaluate_chunk, method_name, chunk, _reference_subset(chunk, reference_distances))
                for chunk in chunks
            ]
            done = 0
            for future in as_completed(futures):
                results.append(future.result())
                done += 1
                if done == len(futures) or done % 10 == 0:
                    print(f"{method_name}: completed {done}/{len(futures)} chunks", flush=True)

    rows: list[dict[str, str]] = []
    elapsed_values: list[float] = []
    expanded_values: list[int] = []
    reachable_count = 0
    correct_count = 0
    for partial in results:
        rows.extend(partial["rows"])
        elapsed_values.extend(partial["elapsed_values"])
        expanded_values.extend(partial["expanded_values"])
        reachable_count += partial["reachable_count"]
        correct_count += partial["correct_count"]

    query_count = len(queries)
    summary = MethodSummary(
        method=method_name,
        query_count=query_count,
        reachable_count=reachable_count,
        unreachable_count=query_count - reachable_count,
        avg_elapsed_ms=_mean(elapsed_values),
        p50_elapsed_ms=_percentile(elapsed_values, 50),
        p95_elapsed_ms=_percentile(elapsed_values, 95),
        avg_expanded_nodes=_mean(expanded_values),
        correctness_rate=(correct_count / query_count) if query_count else 0.0,
    )
    return summary, rows


def _init_worker(graph, index=None) -> None:
    global _WORKER_GRAPH, _WORKER_INDEX
    _WORKER_GRAPH = graph
    _WORKER_INDEX = index


def _process_context():
    if os.name == "posix":
        return multiprocessing.get_context("fork")
    return multiprocessing.get_context()


def _evaluate_chunk(
    method_name: str,
    queries,
    reference_distances: dict[int, float] | None,
    tolerance: float = 1e-6,
) -> dict[str, object]:
    if _WORKER_GRAPH is None:
        raise RuntimeError("worker graph was not initialized")
    rows: list[dict[str, str]] = []
    elapsed_values: list[float] = []
    expanded_values: list[int] = []
    reachable_count = 0
    correct_count = 0

    for query in queries:
        if _WORKER_INDEX is None:
            result: ShortestPathResult = bidirectional_dijkstra_distance(
                _WORKER_GRAPH,
                query.origin,
                query.destination,
            )
        else:
            result = indexed_bidirectional_dijkstra_distance(
                _WORKER_GRAPH,
                _WORKER_INDEX,
                query.origin,
                query.destination,
            )
        if reference_distances is None:
            reference_distance = result.distance
        else:
            reference_distance = reference_distances[query.query_id]
        correct = _same_distance(result.distance, reference_distance, tolerance)
        reachable_count += int(result.reachable)
        correct_count += int(correct)
        elapsed_values.append(result.elapsed_ms)
        expanded_values.append(result.expanded_nodes)
        rows.append(
            {
                "method": method_name,
                "query_id": str(query.query_id),
                "origin": str(query.origin),
                "destination": str(query.destination),
                "distance_m": _format_distance(result.distance),
                "reachable": str(result.reachable),
                "expanded_nodes": str(result.expanded_nodes),
                "elapsed_ms": f"{result.elapsed_ms:.6f}",
                "correct": str(correct),
            }
        )

    return {
        "rows": rows,
        "elapsed_values": elapsed_values,
        "expanded_values": expanded_values,
        "reachable_count": reachable_count,
        "correct_count": correct_count,
    }


def write_experiment_summary(path: Path, rows: list[RegionExperimentRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(RegionExperimentRow.__dataclass_fields__)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(_format_summary_row(row))


def write_report(path: Path, rows: list[RegionExperimentRow]) -> None:
    best = min(rows, key=lambda row: row.elapsed_change_pct)
    success = best.elapsed_change_pct < 0 and best.correctness_rate == 1.0
    lines = [
        "# 物化区域压缩图全量实验报告",
        "",
        f"结论：{'成功减少了平均在线查询时间' if success else '尚未减少平均在线查询时间'}。",
        "",
        "| 方法 | 查询数 | 压缩节点数 | 压缩边数 | 回退率 | 平均查询时间 | 平均耗时变化 | P95 变化 | 平均展开节点变化 | 正确率 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| "
            f"{row.method} | {row.query_count} | {row.compressed_node_count} | "
            f"{row.compressed_edge_count} | {row.fallback_rate_pct:.2f}% | "
            f"{row.indexed_avg_ms:.3f} ms | {row.elapsed_change_pct:.2f}% | "
            f"{row.p95_change_pct:.2f}% | {row.expanded_change_pct:.2f}% | "
            f"{row.correctness_rate:.6f} |"
        )
    lines.extend(
        [
            "",
            f"基线平均在线查询时间：{rows[0].baseline_avg_ms:.3f} ms。",
            "",
            "说明：变化百分比相对双向 Dijkstra；负数表示开销下降。在线计时只包含一次节点状态查询和最短路计算，不包含区域生成、shortcut 计算、压缩图构建、进程调度及结果写盘。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _format_summary_row(row: RegionExperimentRow) -> dict[str, str]:
    formatted: dict[str, str] = {}
    for key, value in asdict(row).items():
        if isinstance(value, float):
            formatted[key] = f"{value:.6f}"
        else:
            formatted[key] = str(value)
    return formatted


def _change_pct(new_value: float, old_value: float) -> float:
    if old_value == 0:
        return 0.0
    return (new_value - old_value) / old_value * 100.0


def _reference_subset(queries, reference_distances: dict[int, float] | None) -> dict[int, float] | None:
    if reference_distances is None:
        return None
    return {query.query_id: reference_distances[query.query_id] for query in queries}


def _chunked(values, chunk_size: int):
    for start in range(0, len(values), chunk_size):
        yield values[start : start + chunk_size]


def _same_distance(left: float, right: float, tolerance: float) -> bool:
    if math.isinf(left) or math.isinf(right):
        return math.isinf(left) and math.isinf(right)
    return abs(left - right) <= tolerance


def _format_distance(distance: float) -> str:
    return "inf" if math.isinf(distance) else f"{distance:.6f}"


def _display_path(path: Path) -> Path:
    try:
        return path.relative_to(ROOT_DIR)
    except ValueError:
        return path


def _mean(values: list[float] | list[int]) -> float:
    return (sum(values) / len(values)) if values else 0.0


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


if __name__ == "__main__":
    main()
