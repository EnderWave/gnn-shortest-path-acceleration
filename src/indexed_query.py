"""Query a fully materialized compressed graph with an exact fallback."""

from __future__ import annotations

from .compression_index import CompressionIndex
import time

from .graph_types import WeightedDiGraph
from .shortest_path import ShortestPathResult, bidirectional_dijkstra_distance


def indexed_bidirectional_dijkstra_distance(
    graph: WeightedDiGraph,
    index: CompressionIndex,
    source: int,
    target: int,
) -> ShortestPathResult:
    start = time.perf_counter()
    query_graph = graph if index.requires_original_graph(source, target) else index.compressed_graph
    return bidirectional_dijkstra_distance(
        query_graph,
        source,
        target,
        _start_time=start,
    )
