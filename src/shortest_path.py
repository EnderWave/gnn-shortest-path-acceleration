"""Exact shortest-path baseline algorithms."""

from __future__ import annotations

import heapq
import math
import time
from dataclasses import dataclass

from .graph_types import NodeId, WeightedDiGraph


@dataclass(frozen=True, slots=True)
class ShortestPathResult:
    distance: float
    expanded_nodes: int
    elapsed_ms: float
    reachable: bool


def dijkstra_distance(graph: WeightedDiGraph, source: NodeId, target: NodeId) -> ShortestPathResult:
    start = time.perf_counter()
    if not graph.has_node(source) or not graph.has_node(target):
        return ShortestPathResult(math.inf, 0, _elapsed_ms(start), False)
    if source == target:
        return ShortestPathResult(0.0, 1, _elapsed_ms(start), True)

    distances: dict[NodeId, float] = {source: 0.0}
    queue: list[tuple[float, NodeId]] = [(0.0, source)]
    settled: set[NodeId] = set()

    while queue:
        distance, node = heapq.heappop(queue)
        if node in settled:
            continue
        settled.add(node)
        if node == target:
            return ShortestPathResult(distance, len(settled), _elapsed_ms(start), True)

        for neighbor, weight in graph.out_neighbors(node):
            if neighbor in settled:
                continue
            new_distance = distance + weight
            if new_distance < distances.get(neighbor, math.inf):
                distances[neighbor] = new_distance
                heapq.heappush(queue, (new_distance, neighbor))

    return ShortestPathResult(math.inf, len(settled), _elapsed_ms(start), False)


def bidirectional_dijkstra_distance(
    graph: WeightedDiGraph,
    source: NodeId,
    target: NodeId,
) -> ShortestPathResult:
    start = time.perf_counter()
    if not graph.has_node(source) or not graph.has_node(target):
        return ShortestPathResult(math.inf, 0, _elapsed_ms(start), False)
    if source == target:
        return ShortestPathResult(0.0, 1, _elapsed_ms(start), True)

    forward_distances: dict[NodeId, float] = {source: 0.0}
    backward_distances: dict[NodeId, float] = {target: 0.0}
    forward_queue: list[tuple[float, NodeId]] = [(0.0, source)]
    backward_queue: list[tuple[float, NodeId]] = [(0.0, target)]
    forward_settled: set[NodeId] = set()
    backward_settled: set[NodeId] = set()
    best = math.inf

    while forward_queue and backward_queue:
        if forward_queue[0][0] + backward_queue[0][0] >= best:
            break

        if forward_queue[0][0] <= backward_queue[0][0]:
            distance, node = heapq.heappop(forward_queue)
            if node in forward_settled:
                continue
            forward_settled.add(node)
            if node in backward_settled:
                best = min(best, distance + backward_distances[node])
            for neighbor, weight in graph.out_neighbors(node):
                new_distance = distance + weight
                if new_distance < forward_distances.get(neighbor, math.inf):
                    forward_distances[neighbor] = new_distance
                    heapq.heappush(forward_queue, (new_distance, neighbor))
                if neighbor in backward_distances:
                    best = min(best, new_distance + backward_distances[neighbor])
        else:
            distance, node = heapq.heappop(backward_queue)
            if node in backward_settled:
                continue
            backward_settled.add(node)
            if node in forward_settled:
                best = min(best, distance + forward_distances[node])
            for neighbor, weight in graph.in_neighbors(node):
                new_distance = distance + weight
                if new_distance < backward_distances.get(neighbor, math.inf):
                    backward_distances[neighbor] = new_distance
                    heapq.heappush(backward_queue, (new_distance, neighbor))
                if neighbor in forward_distances:
                    best = min(best, new_distance + forward_distances[neighbor])

    expanded = len(forward_settled) + len(backward_settled)
    return ShortestPathResult(best, expanded, _elapsed_ms(start), math.isfinite(best))


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0

