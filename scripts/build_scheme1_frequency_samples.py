from __future__ import annotations

import argparse
import csv
import math
import os
import random
from collections import Counter
from heapq import heappop, heappush
from multiprocessing import Pool
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **_kwargs):
        return iterable


_WORKER_ADJACENCY: list[list[tuple[int, float, int]]] | None = None


def load_coords(path: Path) -> tuple[list[tuple[float, float]], int]:
    coords: list[tuple[float, float]] = [(0.0, 0.0)]
    max_node = 0

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.startswith("v "):
                continue
            _, node, lon, lat = line.split()
            node_id = int(node)
            max_node = max(max_node, node_id)

            while len(coords) <= node_id:
                coords.append((0.0, 0.0))

            coords[node_id] = (int(lon) / 1e6, int(lat) / 1e6)

    return coords, max_node


def load_undirected_graph(
    path: Path,
    num_nodes: int,
    show_progress: bool = True,
) -> tuple[list[list[tuple[int, float, int]]], list[tuple[int, int, float]]]:
    adjacency: list[list[tuple[int, float, int]]] = [[] for _ in range(num_nodes + 1)]
    edge_index_by_key: dict[tuple[int, int, float], int] = {}
    edges: list[tuple[int, int, float]] = []

    with path.open("r", encoding="utf-8") as file:
        for line in tqdm(file, desc="Loading graph", disable=not show_progress):
            if not line.startswith("a "):
                continue
            _, src, dst, weight = line.split()
            src_id = int(src)
            dst_id = int(dst)
            edge_weight = float(weight)
            left = min(src_id, dst_id)
            right = max(src_id, dst_id)
            edge_key = (left, right, edge_weight)

            if edge_key in edge_index_by_key:
                continue

            edge_index = len(edges)
            edge_index_by_key[edge_key] = edge_index
            edges.append(edge_key)
            adjacency[left].append((right, edge_weight, edge_index))
            adjacency[right].append((left, edge_weight, edge_index))

    return adjacency, edges


def init_worker(graph_path: str, num_nodes: int) -> None:
    global _WORKER_ADJACENCY
    _WORKER_ADJACENCY, _edges = load_undirected_graph(
        Path(graph_path),
        num_nodes,
        show_progress=False,
    )


def chunk_queries(
    queries: list[dict[str, int]],
    chunk_size: int,
) -> list[list[dict[str, int]]]:
    return [queries[index:index + chunk_size] for index in range(0, len(queries), chunk_size)]


def process_query_chunk(query_chunk: list[dict[str, int]]) -> dict[str, object]:
    if _WORKER_ADJACENCY is None:
        raise RuntimeError("worker graph is not initialized")

    node_pass_counts: Counter[int] = Counter()
    edge_pass_counts: Counter[int] = Counter()
    origin_counts: Counter[int] = Counter()
    destination_counts: Counter[int] = Counter()
    unreachable_queries = 0

    for query in query_chunk:
        origin = query["origin"]
        destination = query["destination"]
        count = query["count"]
        origin_counts[origin] += count
        destination_counts[destination] += count

        _distance, path_nodes, path_edges = bidirectional_dijkstra_path(
            _WORKER_ADJACENCY,
            origin,
            destination,
        )
        if not path_nodes:
            unreachable_queries += 1
            continue

        for node_id in path_nodes:
            node_pass_counts[node_id] += count
        for edge_index in path_edges:
            edge_pass_counts[edge_index] += count

    return {
        "node_pass_counts": node_pass_counts,
        "edge_pass_counts": edge_pass_counts,
        "origin_counts": origin_counts,
        "destination_counts": destination_counts,
        "unreachable_queries": unreachable_queries,
        "num_queries": len(query_chunk),
    }


def load_queries(path: Path) -> list[dict[str, int]]:
    queries: list[dict[str, int]] = []

    with path.open("r", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            count = int(row.get("count", 1))
            queries.append(
                {
                    "query_id": int(row["query_id"]),
                    "origin": int(row["origin"]),
                    "destination": int(row["destination"]),
                    "count": count,
                }
            )

    return queries


def bidirectional_dijkstra_path(
    adjacency: list[list[tuple[int, float, int]]],
    origin: int,
    destination: int,
) -> tuple[float, list[int], list[int]]:
    if origin == destination:
        return 0.0, [origin], []

    forward_heap: list[tuple[float, int]] = [(0.0, origin)]
    backward_heap: list[tuple[float, int]] = [(0.0, destination)]
    forward_dist: dict[int, float] = {origin: 0.0}
    backward_dist: dict[int, float] = {destination: 0.0}
    forward_parent: dict[int, tuple[int, int]] = {}
    backward_parent: dict[int, tuple[int, int]] = {}
    forward_done: set[int] = set()
    backward_done: set[int] = set()

    best_distance = math.inf
    meeting_node = -1

    while forward_heap and backward_heap:
        if forward_heap[0][0] + backward_heap[0][0] >= best_distance:
            break

        if forward_heap[0][0] <= backward_heap[0][0]:
            current_distance, current_node = heappop(forward_heap)
            if current_node in forward_done:
                continue
            forward_done.add(current_node)

            if current_node in backward_dist:
                total_distance = current_distance + backward_dist[current_node]
                if total_distance < best_distance:
                    best_distance = total_distance
                    meeting_node = current_node

            for next_node, weight, edge_index in adjacency[current_node]:
                next_distance = current_distance + weight
                if next_distance < forward_dist.get(next_node, math.inf):
                    forward_dist[next_node] = next_distance
                    forward_parent[next_node] = (current_node, edge_index)
                    heappush(forward_heap, (next_distance, next_node))

                    if next_node in backward_dist:
                        total_distance = next_distance + backward_dist[next_node]
                        if total_distance < best_distance:
                            best_distance = total_distance
                            meeting_node = next_node

        else:
            current_distance, current_node = heappop(backward_heap)
            if current_node in backward_done:
                continue
            backward_done.add(current_node)

            if current_node in forward_dist:
                total_distance = current_distance + forward_dist[current_node]
                if total_distance < best_distance:
                    best_distance = total_distance
                    meeting_node = current_node

            for next_node, weight, edge_index in adjacency[current_node]:
                next_distance = current_distance + weight
                if next_distance < backward_dist.get(next_node, math.inf):
                    backward_dist[next_node] = next_distance
                    backward_parent[next_node] = (current_node, edge_index)
                    heappush(backward_heap, (next_distance, next_node))

                    if next_node in forward_dist:
                        total_distance = next_distance + forward_dist[next_node]
                        if total_distance < best_distance:
                            best_distance = total_distance
                            meeting_node = next_node

    if meeting_node == -1:
        return math.inf, [], []

    left_nodes: list[int] = []
    left_edges: list[int] = []
    current = meeting_node
    while current != origin:
        left_nodes.append(current)
        parent_node, edge_index = forward_parent[current]
        left_edges.append(edge_index)
        current = parent_node
    left_nodes.append(origin)
    left_nodes.reverse()
    left_edges.reverse()

    right_nodes: list[int] = []
    right_edges: list[int] = []
    current = meeting_node
    while current != destination:
        next_node, edge_index = backward_parent[current]
        right_edges.append(edge_index)
        right_nodes.append(next_node)
        current = next_node

    return best_distance, left_nodes + right_nodes, left_edges + right_edges


def top_ten_percent_ids(counts: list[int]) -> set[int]:
    item_count = len(counts) - 1
    positive_count = max(1, math.ceil(item_count * 0.10))
    ranked_ids = sorted(range(1, len(counts)), key=lambda item_id: counts[item_id], reverse=True)
    return set(ranked_ids[:positive_count])


def top_ten_percent_edge_indexes(edge_counts: list[int]) -> set[int]:
    positive_count = max(1, math.ceil(len(edge_counts) * 0.10))
    ranked_indexes = sorted(range(len(edge_counts)), key=lambda edge_index: edge_counts[edge_index], reverse=True)
    return set(ranked_indexes[:positive_count])


def sample_negatives(
    candidates: list[int],
    sample_count: int,
    rng: random.Random,
) -> set[int]:
    if sample_count >= len(candidates):
        return set(candidates)
    return set(rng.sample(candidates, sample_count))


def write_node_counts(
    path: Path,
    coords: list[tuple[float, float]],
    pass_counts: list[int],
    origin_counts: Counter[int],
    destination_counts: Counter[int],
    positive_nodes: set[int],
    negative_nodes: set[int],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "node",
                "lon",
                "lat",
                "origin_count",
                "destination_count",
                "pass_count",
                "label",
                "sample_role",
            ],
        )
        writer.writeheader()

        for node_id in range(1, len(coords)):
            lon, lat = coords[node_id]
            is_positive = node_id in positive_nodes
            is_negative = node_id in negative_nodes
            writer.writerow(
                {
                    "node": node_id,
                    "lon": lon,
                    "lat": lat,
                    "origin_count": origin_counts[node_id],
                    "destination_count": destination_counts[node_id],
                    "pass_count": pass_counts[node_id],
                    "label": 1 if is_positive else 0,
                    "sample_role": "positive" if is_positive else "negative" if is_negative else "unused",
                }
            )


def write_edge_counts(
    path: Path,
    edges: list[tuple[int, int, float]],
    pass_counts: list[int],
    positive_edges: set[int],
    negative_edges: set[int],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["edge_index", "src", "dst", "weight", "pass_count", "label", "sample_role"],
        )
        writer.writeheader()

        for edge_index, (src, dst, weight) in enumerate(edges):
            is_positive = edge_index in positive_edges
            is_negative = edge_index in negative_edges
            writer.writerow(
                {
                    "edge_index": edge_index,
                    "src": src,
                    "dst": dst,
                    "weight": weight,
                    "pass_count": pass_counts[edge_index],
                    "label": 1 if is_positive else 0,
                    "sample_role": "positive" if is_positive else "negative" if is_negative else "unused",
                }
            )


def plot_positive_samples(
    output_path: Path,
    coords: list[tuple[float, float]],
    edges: list[tuple[int, int, float]],
    positive_nodes: set[int],
    positive_edges: set[int],
    dpi: int,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lon = np.array([coord[0] for coord in coords[1:]], dtype=np.float64)
    lat = np.array([coord[1] for coord in coords[1:]], dtype=np.float64)

    positive_node_ids = sorted(positive_nodes)
    positive_lon = np.array([coords[node_id][0] for node_id in positive_node_ids], dtype=np.float64)
    positive_lat = np.array([coords[node_id][1] for node_id in positive_node_ids], dtype=np.float64)

    segments = [
        [coords[edges[edge_index][0]], coords[edges[edge_index][1]]]
        for edge_index in positive_edges
    ]

    fig, ax = plt.subplots(figsize=(10, 10), dpi=dpi)
    ax.scatter(lon, lat, s=0.04, c="#cccccc", alpha=0.22, linewidths=0)

    if segments:
        edge_collection = LineCollection(segments, colors="#0072b2", linewidths=0.18, alpha=0.25)
        ax.add_collection(edge_collection)

    ax.scatter(positive_lon, positive_lat, s=0.55, c="#d62728", alpha=0.78, linewidths=0)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title("Scheme 1 positive samples: top 10% node/edge pass counts")
    ax.grid(True, linewidth=0.25, alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)


def build_frequency_samples(args: argparse.Namespace) -> None:
    rng = random.Random(args.seed)
    coords, num_nodes = load_coords(args.coords)
    adjacency, edges = load_undirected_graph(args.graph, num_nodes)
    queries = load_queries(args.queries)
    if args.max_queries is not None:
        queries = queries[:args.max_queries]

    del adjacency

    workers = args.workers if args.workers is not None else max(1, (os.cpu_count() or 2) - 1)
    chunks = chunk_queries(queries, args.chunk_size)
    node_pass_counter: Counter[int] = Counter()
    edge_pass_counter: Counter[int] = Counter()
    origin_counts: Counter[int] = Counter()
    destination_counts: Counter[int] = Counter()
    unreachable_queries = 0

    print(f"Workers: {workers}")
    print(f"Query chunks: {len(chunks):,}")

    with Pool(
        processes=workers,
        initializer=init_worker,
        initargs=(str(args.graph), num_nodes),
    ) as pool:
        results = pool.imap_unordered(process_query_chunk, chunks)
        for result in tqdm(results, total=len(chunks), desc="Tracing query chunks"):
            node_pass_counter.update(result["node_pass_counts"])
            edge_pass_counter.update(result["edge_pass_counts"])
            origin_counts.update(result["origin_counts"])
            destination_counts.update(result["destination_counts"])
            unreachable_queries += int(result["unreachable_queries"])

    node_pass_counts = [0] * (num_nodes + 1)
    for node_id, count in node_pass_counter.items():
        node_pass_counts[node_id] = count

    edge_pass_counts = [0] * len(edges)
    for edge_index, count in edge_pass_counter.items():
        edge_pass_counts[edge_index] = count

    positive_nodes = top_ten_percent_ids(node_pass_counts)
    negative_node_candidates = [node_id for node_id in range(1, num_nodes + 1) if node_id not in positive_nodes]
    negative_nodes = sample_negatives(negative_node_candidates, len(positive_nodes), rng)

    positive_edges = top_ten_percent_edge_indexes(edge_pass_counts)
    negative_edge_candidates = [edge_index for edge_index in range(len(edges)) if edge_index not in positive_edges]
    negative_edges = sample_negatives(negative_edge_candidates, len(positive_edges), rng)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_node_counts(
        args.output_dir / "node_counts.csv",
        coords,
        node_pass_counts,
        origin_counts,
        destination_counts,
        positive_nodes,
        negative_nodes,
    )
    write_edge_counts(
        args.output_dir / "edge_counts.csv",
        edges,
        edge_pass_counts,
        positive_edges,
        negative_edges,
    )
    plot_positive_samples(
        args.plot_output,
        coords,
        edges,
        positive_nodes,
        positive_edges,
        args.dpi,
    )

    print(f"Queries: {len(queries):,}")
    print(f"Unreachable queries: {unreachable_queries:,}")
    print(f"Nodes: {num_nodes:,}")
    print(f"Edges: {len(edges):,}")
    print(f"Positive nodes: {len(positive_nodes):,}")
    print(f"Negative nodes: {len(negative_nodes):,}")
    print(f"Positive edges: {len(positive_edges):,}")
    print(f"Negative edges: {len(negative_edges):,}")
    print(f"Output directory: {args.output_dir}")
    print(f"Plot: {args.plot_output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coords", type=Path, default=Path("data/raw/dimacs/small/USA-road-d.NY.co"))
    parser.add_argument("--graph", type=Path, default=Path("data/raw/dimacs/small/USA-road-d.NY.gr"))
    parser.add_argument(
        "--queries",
        type=Path,
        default=Path("data/processed/query_loads/small/queries_train.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed/training/small/scheme1_frequency"),
    )
    parser.add_argument(
        "--plot-output",
        type=Path,
        default=Path("data/plots/small_scheme1_positive_samples.png"),
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dpi", type=int, default=220)
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of worker processes. Defaults to CPU count minus one.",
    )
    parser.add_argument("--chunk-size", type=int, default=100)
    parser.add_argument("--max-queries", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    build_frequency_samples(parse_args())


if __name__ == "__main__":
    main()
