"""Connected region generation for shortcut-index experiments."""

from __future__ import annotations

import random
from collections import Counter, deque
from dataclasses import dataclass
from typing import Iterable

from .graph_types import NodeId, Query, WeightedDiGraph


@dataclass(frozen=True, slots=True)
class Region:
    region_id: int
    nodes: frozenset[NodeId]
    boundary_nodes: frozenset[NodeId]
    seed_node: NodeId
    selection_method: str

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def boundary_count(self) -> int:
        return len(self.boundary_nodes)

    @property
    def storage_cost_estimate(self) -> int:
        return self.boundary_count * self.boundary_count


def build_random_regions(
    graph: WeightedDiGraph,
    region_count: int,
    region_size: int,
    seed: int = 42,
    allow_overlap: bool = False,
) -> list[Region]:
    rng = random.Random(seed)
    candidates = list(graph.adjacency)
    rng.shuffle(candidates)
    return _build_regions_from_seeds(
        graph,
        candidates,
        region_count,
        region_size,
        "random_bfs",
        allow_overlap=allow_overlap,
    )


def build_hotspot_regions(
    graph: WeightedDiGraph,
    queries: list[Query],
    region_count: int,
    region_size: int,
    allow_overlap: bool = False,
) -> list[Region]:
    counts: Counter[NodeId] = Counter()
    for query in queries:
        counts[query.origin] += 1
        counts[query.destination] += 1
    seeds = [node for node, _ in counts.most_common()]
    return _build_regions_from_seeds(
        graph,
        seeds,
        region_count,
        region_size,
        "od_hotspot_bfs",
        allow_overlap=allow_overlap,
    )


def grow_bfs_region(graph: WeightedDiGraph, seed_node: NodeId, max_nodes: int) -> frozenset[NodeId]:
    if max_nodes <= 0 or not graph.has_node(seed_node):
        return frozenset()

    region: set[NodeId] = {seed_node}
    queue: deque[NodeId] = deque([seed_node])

    while queue and len(region) < max_nodes:
        node = queue.popleft()
        neighbors = sorted(_undirected_neighbors(graph, node))
        for neighbor in neighbors:
            if neighbor in region:
                continue
            region.add(neighbor)
            queue.append(neighbor)
            if len(region) >= max_nodes:
                break

    return frozenset(region)


def find_boundary_nodes(graph: WeightedDiGraph, nodes: Iterable[NodeId]) -> frozenset[NodeId]:
    region = set(nodes)
    boundary: set[NodeId] = set()
    for node in region:
        if any(neighbor not in region for neighbor, _ in graph.out_neighbors(node)):
            boundary.add(node)
        if any(neighbor not in region for neighbor, _ in graph.in_neighbors(node)):
            boundary.add(node)
    return frozenset(boundary)


def _build_regions_from_seeds(
    graph: WeightedDiGraph,
    seeds: Iterable[NodeId],
    region_count: int,
    region_size: int,
    selection_method: str,
    allow_overlap: bool,
) -> list[Region]:
    regions: list[Region] = []
    used_nodes: set[NodeId] = set()

    for seed_node in seeds:
        if not allow_overlap and seed_node in used_nodes:
            continue
        nodes = grow_bfs_region(graph, seed_node, region_size)
        if len(nodes) < 2:
            continue
        if not allow_overlap and nodes & used_nodes:
            continue
        boundary_nodes = find_boundary_nodes(graph, nodes)
        if len(boundary_nodes) < 2:
            continue
        region = Region(
            region_id=len(regions),
            nodes=nodes,
            boundary_nodes=boundary_nodes,
            seed_node=seed_node,
            selection_method=selection_method,
        )
        regions.append(region)
        used_nodes.update(nodes)
        if len(regions) >= region_count:
            break

    return regions


def _undirected_neighbors(graph: WeightedDiGraph, node: NodeId) -> set[NodeId]:
    neighbors = {neighbor for neighbor, _ in graph.out_neighbors(node)}
    neighbors.update(neighbor for neighbor, _ in graph.in_neighbors(node))
    return neighbors
