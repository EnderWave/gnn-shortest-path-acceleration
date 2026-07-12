"""加载 OD 查询负载。"""

from __future__ import annotations

import csv
from pathlib import Path

from .graph_types import Query


def load_porto_queries(query_csv: Path, limit: int | None = None) -> list[Query]:
    queries: list[Query] = []
    with query_csv.open("r", encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            if row.get("snap_usable", "True") != "True":
                continue
            queries.append(
                Query(
                    query_id=int(row["query_id"]),
                    origin=int(row["origin_node"]),
                    destination=int(row["dest_node"]),
                )
            )
            if limit is not None and len(queries) >= limit:
                break
    return queries
