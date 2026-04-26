from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


def load_dimacs_coords(path: Path) -> tuple[np.ndarray, np.ndarray]:
    lon_values: list[float] = []
    lat_values: list[float] = []

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.startswith("v "):
                continue
            _, _node, lon, lat = line.split()
            lon_values.append(int(lon) / 1_000_000)
            lat_values.append(int(lat) / 1_000_000)

    if not lon_values:
        raise ValueError(f"No coordinate rows found in {path}")

    return np.array(lon_values), np.array(lat_values)


def infer_title(input_path: Path, point_count: int) -> str:
    parts = {part.lower() for part in input_path.parts}
    if "small" in parts:
        scale = "small"
    elif "medium" in parts:
        scale = "medium"
    elif "large" in parts:
        scale = "large"
    else:
        scale = "DIMACS"

    dataset = input_path.stem
    if dataset.endswith(".co"):
        dataset = dataset[:-3]

    return f"DIMACS {scale} nodes - {dataset} ({point_count:,} points)"


def plot_points(input_path: Path, output_path: Path, dpi: int) -> None:
    lon, lat = load_dimacs_coords(input_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(9, 9), dpi=dpi)
    ax.scatter(lon, lat, s=0.08, c="black", alpha=0.45, linewidths=0)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(infer_title(input_path, len(lon)))
    ax.grid(True, linewidth=0.25, alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)

    print(f"Loaded {len(lon):,} points from {input_path}")
    print(f"Saved plot to {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot all node coordinates from a DIMACS .co file."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/raw/dimacs/small/USA-road-d.NY.co"),
        help="Path to the DIMACS .co coordinate file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/plots/small_points.png"),
        help="Path for the generated image.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=220,
        help="Output image DPI.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    plot_points(args.input, args.output, args.dpi)


if __name__ == "__main__":
    main()
