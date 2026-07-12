"""在波尔图路网上运行精确最短路基线实验。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from src.evaluation import evaluate_method, write_detail_rows, write_summary
from src.graph_io import load_porto_graph, summarize_graph
from src.shortest_path import bidirectional_dijkstra_distance, dijkstra_distance
from src.workloads import load_porto_queries


DEFAULT_NODE_CSV = ROOT_DIR / "data" / "processed" / "porto" / "波尔图道路节点.csv"
DEFAULT_EDGE_CSV = ROOT_DIR / "data" / "processed" / "porto" / "波尔图道路边.csv"
DEFAULT_QUERY_CSV = ROOT_DIR / "data" / "processed" / "porto" / "波尔图可用起终点节点查询_200米.csv"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "results" / "baselines"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Dijkstra baselines on Porto OD queries.")
    parser.add_argument("--node-csv", type=Path, default=DEFAULT_NODE_CSV)
    parser.add_argument("--edge-csv", type=Path, default=DEFAULT_EDGE_CSV)
    parser.add_argument("--query-csv", type=Path, default=DEFAULT_QUERY_CSV)
    parser.add_argument("--limit", type=int, default=None, help="Number of usable OD queries to evaluate. Omit for all.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--progress-interval", type=int, default=5000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    graph = load_porto_graph(args.node_csv, args.edge_csv)
    queries = load_porto_queries(args.query_csv, limit=args.limit)
    summary = summarize_graph(graph)

    print(
        "graph: "
        f"nodes={summary.node_count:,}, edges={summary.edge_count:,}, "
        f"isolated={summary.isolated_nodes:,}, max_out_degree={summary.max_out_degree}, "
        f"avg_out_degree={summary.average_out_degree:.2f}, "
        f"weight_range=[{summary.min_weight:.3f}, {summary.max_weight:.3f}]"
    )
    print(f"queries: {len(queries):,}")

    all_rows = []
    summaries = []

    dijkstra_summary, dijkstra_rows = evaluate_method(
        graph,
        queries,
        "dijkstra",
        dijkstra_distance,
        reference=None,
        progress_interval=args.progress_interval,
    )
    summaries.append(dijkstra_summary)
    all_rows.extend(dijkstra_rows)
    reference_distances = {
        int(row["query_id"]): float("inf") if row["distance_m"] == "inf" else float(row["distance_m"])
        for row in dijkstra_rows
    }

    bidirectional_summary, bidirectional_rows = evaluate_method(
        graph,
        queries,
        "bidirectional_dijkstra",
        bidirectional_dijkstra_distance,
        reference_distances=reference_distances,
        progress_interval=args.progress_interval,
    )
    summaries.append(bidirectional_summary)
    all_rows.extend(bidirectional_rows)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "porto_allqueries" if args.limit is None else f"porto_{len(queries)}queries"
    summary_path = args.output_dir / f"{suffix}_summary.csv"
    detail_path = args.output_dir / f"{suffix}_details.csv"
    write_summary(summary_path, summaries)
    write_detail_rows(detail_path, all_rows)

    for item in summaries:
        print(
            f"{item.method}: avg_ms={item.avg_elapsed_ms:.3f}, "
            f"p95_ms={item.p95_elapsed_ms:.3f}, "
            f"avg_expanded={item.avg_expanded_nodes:.1f}, "
            f"reachable={item.reachable_count}/{item.query_count}, "
            f"correctness={item.correctness_rate:.3f}"
        )
    print(f"summary={summary_path.relative_to(ROOT_DIR)}")
    print(f"details={detail_path.relative_to(ROOT_DIR)}")


if __name__ == "__main__":
    main()
