"""Shared evaluation helpers for exact shortest-path baselines."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .graph_types import Query, WeightedDiGraph
from .shortest_path import ShortestPathResult


QueryMethod = Callable[[WeightedDiGraph, int, int], ShortestPathResult]


@dataclass(frozen=True, slots=True)
class MethodSummary:
    method: str
    query_count: int
    reachable_count: int
    unreachable_count: int
    avg_elapsed_ms: float
    p50_elapsed_ms: float
    p95_elapsed_ms: float
    avg_expanded_nodes: float
    correctness_rate: float


def evaluate_method(
    graph: WeightedDiGraph,
    queries: list[Query],
    method_name: str,
    method: QueryMethod,
    reference: QueryMethod | None = None,
    tolerance: float = 1e-6,
) -> tuple[MethodSummary, list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    elapsed_values: list[float] = []
    expanded_values: list[int] = []
    reachable_count = 0
    correct_count = 0

    for query in queries:
        result = method(graph, query.origin, query.destination)
        reference_result = result if reference is None else reference(graph, query.origin, query.destination)
        correct = _same_distance(result.distance, reference_result.distance, tolerance)

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


def write_detail_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "method",
        "query_id",
        "origin",
        "destination",
        "distance_m",
        "reachable",
        "expanded_nodes",
        "elapsed_ms",
        "correct",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, summaries: list[MethodSummary]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(MethodSummary.__dataclass_fields__))
        writer.writeheader()
        for summary in summaries:
            writer.writerow(
                {
                    "method": summary.method,
                    "query_count": summary.query_count,
                    "reachable_count": summary.reachable_count,
                    "unreachable_count": summary.unreachable_count,
                    "avg_elapsed_ms": f"{summary.avg_elapsed_ms:.6f}",
                    "p50_elapsed_ms": f"{summary.p50_elapsed_ms:.6f}",
                    "p95_elapsed_ms": f"{summary.p95_elapsed_ms:.6f}",
                    "avg_expanded_nodes": f"{summary.avg_expanded_nodes:.2f}",
                    "correctness_rate": f"{summary.correctness_rate:.6f}",
                }
            )


def _same_distance(left: float, right: float, tolerance: float) -> bool:
    if math.isinf(left) or math.isinf(right):
        return math.isinf(left) and math.isinf(right)
    return abs(left - right) <= tolerance


def _format_distance(distance: float) -> str:
    return "inf" if math.isinf(distance) else f"{distance:.6f}"


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

