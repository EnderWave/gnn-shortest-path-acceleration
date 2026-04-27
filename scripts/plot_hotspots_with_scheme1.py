from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection


def load_coords(path: Path) -> tuple[list[tuple[float, float]], np.ndarray, np.ndarray]:
    coords: list[tuple[float, float]] = [(0.0, 0.0)]

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.startswith("v "):
                continue
            _, node, lon, lat = line.split()
            node_id = int(node)
            while len(coords) <= node_id:
                coords.append((0.0, 0.0))
            coords[node_id] = (int(lon) / 1e6, int(lat) / 1e6)

    lon_values = np.array([coord[0] for coord in coords[1:]], dtype=np.float64)
    lat_values = np.array([coord[1] for coord in coords[1:]], dtype=np.float64)
    return coords, lon_values, lat_values


def load_hotspots(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def load_positive_nodes(path: Path) -> list[int]:
    positive_nodes: list[int] = []
    with path.open("r", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row["sample_role"] == "positive":
                positive_nodes.append(int(row["node"]))
    return positive_nodes


def load_positive_edges(path: Path) -> list[tuple[int, int]]:
    positive_edges: list[tuple[int, int]] = []
    with path.open("r", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row["sample_role"] == "positive":
                positive_edges.append((int(row["src"]), int(row["dst"])))
    return positive_edges


def nearest_indexes(
    lon: np.ndarray,
    lat: np.ndarray,
    center_lon: float,
    center_lat: float,
    count: int,
) -> np.ndarray:
    nearest_count = min(count, len(lon))
    distance_square = (lon - center_lon) ** 2 + (lat - center_lat) ** 2
    return np.argpartition(distance_square, nearest_count - 1)[:nearest_count]


def plot_combined(args: argparse.Namespace) -> None:
    coords, lon, lat = load_coords(args.coords)
    hotspots = load_hotspots(args.hotspots)
    positive_nodes = load_positive_nodes(args.node_counts)
    positive_edges = load_positive_edges(args.edge_counts)

    args.output.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(11, 11), dpi=args.dpi)
    ax.scatter(lon, lat, s=0.035, c="#d0d0d0", alpha=0.18, linewidths=0)

    colors = plt.cm.tab20(np.linspace(0, 1, max(len(hotspots), 1)))
    for index, hotspot in enumerate(hotspots):
        center_lon = float(hotspot["center_lon"])
        center_lat = float(hotspot["center_lat"])
        num_nodes = int(hotspot["num_nodes"])
        hotspot_id = int(hotspot["hotspot_id"])
        region_indexes = nearest_indexes(lon, lat, center_lon, center_lat, num_nodes)
        color = colors[index % len(colors)]

        ax.scatter(
            lon[region_indexes],
            lat[region_indexes],
            s=2.1,
            color=color,
            alpha=0.34,
            linewidths=0,
        )
        ax.scatter(
            [center_lon],
            [center_lat],
            s=34,
            color=color,
            edgecolors="black",
            linewidths=0.45,
            zorder=6,
        )
        ax.text(
            center_lon,
            center_lat,
            str(hotspot_id),
            fontsize=5.5,
            ha="center",
            va="center",
            zorder=7,
        )

    edge_segments = [
        [coords[src], coords[dst]]
        for src, dst in positive_edges
        if src < len(coords) and dst < len(coords)
    ]
    if edge_segments:
        ax.add_collection(
            LineCollection(
                edge_segments,
                colors="#0072b2",
                linewidths=0.17,
                alpha=0.22,
                zorder=3,
            )
        )

    positive_lon = np.array([coords[node][0] for node in positive_nodes], dtype=np.float64)
    positive_lat = np.array([coords[node][1] for node in positive_nodes], dtype=np.float64)
    ax.scatter(
        positive_lon,
        positive_lat,
        s=0.62,
        c="#d62728",
        alpha=0.72,
        linewidths=0,
        zorder=5,
    )

    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title("Hotspots with Scheme 1 positive samples")
    ax.grid(True, linewidth=0.25, alpha=0.25)
    fig.tight_layout()
    fig.savefig(args.output)
    plt.close(fig)

    print(f"Hotspots: {len(hotspots):,}")
    print(f"Positive nodes: {len(positive_nodes):,}")
    print(f"Positive edges: {len(positive_edges):,}")
    print(f"Saved plot to {args.output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coords", type=Path, default=Path("data/raw/dimacs/small/USA-road-d.NY.co"))
    parser.add_argument("--hotspots", type=Path, default=Path("data/processed/query_loads/small/hotspots.csv"))
    parser.add_argument(
        "--node-counts",
        type=Path,
        default=Path("data/processed/training/small/scheme1_frequency/node_counts.csv"),
    )
    parser.add_argument(
        "--edge-counts",
        type=Path,
        default=Path("data/processed/training/small/scheme1_frequency/edge_counts.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/plots/small_hotspots_scheme1_positive_samples.png"),
    )
    parser.add_argument("--dpi", type=int, default=220)
    return parser.parse_args()


def main() -> None:
    plot_combined(parse_args())


if __name__ == "__main__":
    main()
