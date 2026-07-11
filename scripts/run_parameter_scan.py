"""Run resumable controlled-variable experiments for region compression."""

from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from scripts.verify_materialized_queries import evaluate_paired
from src.compression_index import build_compression_index
from src.graph_io import load_porto_graph
from src.regions import build_hotspot_regions, build_random_regions
from src.workloads import load_porto_queries


DEFAULT_NODE_CSV = ROOT_DIR / "data" / "processed" / "porto" / "波尔图道路节点.csv"
DEFAULT_EDGE_CSV = ROOT_DIR / "data" / "processed" / "porto" / "波尔图道路边.csv"
DEFAULT_QUERY_CSV = ROOT_DIR / "data" / "processed" / "porto" / "波尔图可用起终点节点查询_200米.csv"
DEFAULT_OUTPUT = ROOT_DIR / "results" / "parameter_scan" / "porto_parameter_scan.csv"


@dataclass(frozen=True, slots=True)
class ScanConfig:
    run_id: str
    scan_mode: str
    experiment_axis: str
    strategy: str
    requested_region_count: int
    region_size: int
    seed: int | None


@dataclass(frozen=True, slots=True)
class ScanResult:
    run_id: str
    completed_at: str
    scan_mode: str
    experiment_axis: str
    strategy: str
    seed: int | None
    query_count: int
    requested_region_count: int
    actual_region_count: int
    region_size: int
    original_node_count: int
    original_edge_count: int
    compressed_node_count: int
    compressed_edge_count: int
    internal_node_count: int
    shortcut_count: int
    fallback_query_count: int
    fallback_rate_pct: float
    preprocessing_seconds: float
    evaluation_wall_seconds: float
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
    parser = argparse.ArgumentParser(
        description="Run resumable controlled-variable region compression experiments."
    )
    parser.add_argument("--node-csv", type=Path, default=DEFAULT_NODE_CSV)
    parser.add_argument("--edge-csv", type=Path, default=DEFAULT_EDGE_CSV)
    parser.add_argument("--query-csv", type=Path, default=DEFAULT_QUERY_CSV)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=None, help="Omit to use all OD queries.")
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--region-counts", type=int, nargs="+", default=[50, 100, 200, 400])
    parser.add_argument("--region-sizes", type=int, nargs="+", default=[128, 256, 512, 1024])
    parser.add_argument("--anchor-region-count", type=int, default=200)
    parser.add_argument("--anchor-region-size", type=int, default=512)
    parser.add_argument("--random-seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=["random_bfs", "od_hotspot_bfs"],
        default=["random_bfs", "od_hotspot_bfs"],
    )
    parser.add_argument(
        "--full-grid",
        action="store_true",
        help="Test every count-size combination instead of one-variable-at-a-time sweeps.",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Discard the existing output and run every configuration again.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned configurations without running them.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    _validate_args(args)
    configs = build_configs(args)
    if args.dry_run:
        _print_configs(configs)
        return

    if args.restart:
        args.output.unlink(missing_ok=True)

    graph = load_porto_graph(args.node_csv, args.edge_csv)
    queries = load_porto_queries(args.query_csv, limit=args.limit)
    completed = _load_completed(
        args.output,
        query_count=len(queries),
        original_node_count=graph.node_count,
        original_edge_count=graph.edge_count,
    )
    config_ids = {config.run_id for config in configs}
    completed.intersection_update(config_ids)
    pending = [config for config in configs if config.run_id not in completed]
    print(
        f"scan configurations: total={len(configs)}, completed={len(completed)}, "
        f"pending={len(pending)}, workers={args.workers}",
        flush=True,
    )
    if not pending:
        print(f"all configurations are complete: {_display_path(args.output)}")
        return

    started = time.perf_counter()
    finished_now = 0

    for position, config in enumerate(configs, start=1):
        if config.run_id in completed:
            print(f"[{position}/{len(configs)}] skip {config.run_id}", flush=True)
            continue

        print(f"[{position}/{len(configs)}] start {config.run_id}", flush=True)
        result = run_config(
            graph,
            queries,
            config,
            workers=args.workers,
            chunk_size=args.chunk_size,
        )
        _append_result(args.output, result)
        completed.add(config.run_id)
        finished_now += 1
        average_seconds = (time.perf_counter() - started) / finished_now
        remaining = len(configs) - len(completed)
        print(
            f"[{position}/{len(configs)}] done {config.run_id}: "
            f"time_change={result.elapsed_change_pct:.2f}%, "
            f"correctness={result.correctness_rate:.6f}, "
            f"estimated_remaining={_format_duration(average_seconds * remaining)}",
            flush=True,
        )

    print(f"parameter scan complete: {_display_path(args.output)}", flush=True)


def build_configs(args: argparse.Namespace) -> list[ScanConfig]:
    if args.full_grid:
        pairs = [
            (region_count, region_size, "full_grid")
            for region_count in args.region_counts
            for region_size in args.region_sizes
        ]
        scan_mode = "full_grid"
    else:
        pairs = [
            (region_count, args.anchor_region_size, "region_count")
            for region_count in args.region_counts
        ]
        pairs.extend(
            (args.anchor_region_count, region_size, "region_size")
            for region_size in args.region_sizes
            if region_size != args.anchor_region_size
        )
        scan_mode = "controlled"

    configs: list[ScanConfig] = []
    seen_run_ids: set[str] = set()
    for region_count, region_size, axis in pairs:
        for strategy in args.strategies:
            seeds = args.random_seeds if strategy == "random_bfs" else [None]
            for seed in seeds:
                seed_suffix = f"_seed{seed}" if seed is not None else ""
                run_id = f"{strategy}_r{region_count}_s{region_size}{seed_suffix}"
                if run_id in seen_run_ids:
                    continue
                seen_run_ids.add(run_id)
                configs.append(
                    ScanConfig(
                        run_id=run_id,
                        scan_mode=scan_mode,
                        experiment_axis=axis,
                        strategy=strategy,
                        requested_region_count=region_count,
                        region_size=region_size,
                        seed=seed,
                    )
                )
    return configs


def run_config(graph, queries, config: ScanConfig, workers: int, chunk_size: int) -> ScanResult:
    preprocessing_start = time.perf_counter()
    if config.strategy == "random_bfs":
        if config.seed is None:
            raise ValueError("random_bfs requires a seed")
        regions = build_random_regions(
            graph,
            config.requested_region_count,
            config.region_size,
            config.seed,
        )
    else:
        regions = build_hotspot_regions(
            graph,
            queries,
            config.requested_region_count,
            config.region_size,
        )
    index = build_compression_index(graph, regions)
    preprocessing_seconds = time.perf_counter() - preprocessing_start
    fallback_query_count = sum(
        index.requires_original_graph(query.origin, query.destination)
        for query in queries
    )

    evaluation_start = time.perf_counter()
    metrics, _ = evaluate_paired(
        graph,
        index,
        queries,
        config.run_id,
        workers,
        chunk_size,
        collect_details=False,
    )
    evaluation_wall_seconds = time.perf_counter() - evaluation_start

    baseline_avg_ms = _mean(metrics["baseline_elapsed"])
    indexed_avg_ms = _mean(metrics["indexed_elapsed"])
    baseline_p95_ms = _percentile(metrics["baseline_elapsed"], 95)
    indexed_p95_ms = _percentile(metrics["indexed_elapsed"], 95)
    baseline_avg_expanded = _mean(metrics["baseline_expanded"])
    indexed_avg_expanded = _mean(metrics["indexed_expanded"])
    return ScanResult(
        run_id=config.run_id,
        completed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        scan_mode=config.scan_mode,
        experiment_axis=config.experiment_axis,
        strategy=config.strategy,
        seed=config.seed,
        query_count=len(queries),
        requested_region_count=config.requested_region_count,
        actual_region_count=index.region_count,
        region_size=config.region_size,
        original_node_count=graph.node_count,
        original_edge_count=graph.edge_count,
        compressed_node_count=index.compressed_graph.node_count,
        compressed_edge_count=index.compressed_graph.edge_count,
        internal_node_count=index.internal_node_count,
        shortcut_count=index.shortcut_count,
        fallback_query_count=fallback_query_count,
        fallback_rate_pct=fallback_query_count / len(queries) * 100.0,
        preprocessing_seconds=preprocessing_seconds,
        evaluation_wall_seconds=evaluation_wall_seconds,
        baseline_avg_ms=baseline_avg_ms,
        indexed_avg_ms=indexed_avg_ms,
        elapsed_change_pct=_change_pct(indexed_avg_ms, baseline_avg_ms),
        baseline_p95_ms=baseline_p95_ms,
        indexed_p95_ms=indexed_p95_ms,
        p95_change_pct=_change_pct(indexed_p95_ms, baseline_p95_ms),
        baseline_avg_expanded=baseline_avg_expanded,
        indexed_avg_expanded=indexed_avg_expanded,
        expanded_change_pct=_change_pct(indexed_avg_expanded, baseline_avg_expanded),
        faster_query_rate_pct=(
            sum(delta < 0 for delta in metrics["elapsed_deltas"])
            / len(queries)
            * 100.0
        ),
        median_delta_ms=statistics.median(metrics["elapsed_deltas"]),
        correctness_rate=sum(metrics["correct_values"]) / len(queries),
    )


def _load_completed(
    path: Path,
    query_count: int,
    original_node_count: int,
    original_edge_count: int,
) -> set[str]:
    if not path.exists():
        return set()
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        expected = list(ScanResult.__dataclass_fields__)
        if reader.fieldnames != expected:
            raise SystemExit(
                f"existing output has incompatible columns: {path}; "
                "use --restart to replace it"
            )
        return {
            row["run_id"]
            for row in reader
            if int(row["query_count"]) == query_count
            and int(row["original_node_count"]) == original_node_count
            and int(row["original_edge_count"]) == original_edge_count
        }


def _append_result(path: Path, result: ScanResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(ScanResult.__dataclass_fields__))
        if write_header:
            writer.writeheader()
        writer.writerow(
            {
                key: f"{value:.6f}" if isinstance(value, float) else value
                for key, value in asdict(result).items()
            }
        )
        file.flush()
        os.fsync(file.fileno())


def _validate_args(args: argparse.Namespace) -> None:
    positive_values = [
        args.workers,
        args.chunk_size,
        args.anchor_region_count,
        args.anchor_region_size,
        *args.region_counts,
        *args.region_sizes,
    ]
    if any(value <= 0 for value in positive_values):
        raise SystemExit("workers, chunk size, region counts, and region sizes must be positive")
    if not args.random_seeds and "random_bfs" in args.strategies:
        raise SystemExit("random_bfs requires at least one random seed")


def _print_configs(configs: list[ScanConfig]) -> None:
    print(f"planned configurations: {len(configs)}")
    for index, config in enumerate(configs, start=1):
        print(f"{index:>3}: {config.run_id} ({config.experiment_axis})")


def _mean(values: list[float] | list[int]) -> float:
    return sum(values) / len(values) if values else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile / 100.0
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _change_pct(new_value: float, old_value: float) -> float:
    return (new_value - old_value) / old_value * 100.0 if old_value else 0.0


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


def _display_path(path: Path) -> Path:
    try:
        return path.relative_to(ROOT_DIR)
    except ValueError:
        return path


if __name__ == "__main__":
    main()
