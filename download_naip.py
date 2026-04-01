#!/usr/bin/env python3

import argparse
import math
from pathlib import Path

import numpy as np
import planetary_computer
import pystac_client
import rasterio
import rasterio.windows
from PIL import Image
from pyproj import Transformer
from shapely.geometry import shape
from tqdm import tqdm

_OUTPUT_DIR = Path("data/naip")

_LOCATIONS: dict[str, tuple[float, float]] = {
    "cushing": (35.9485, -96.7422),
    "houston": (29.7428, -95.1163),
    "alta-wind": (35.0174, -118.2948),
}

_HALF_SIZE_DEG = 0.02
_DATETIME_RANGE = "2020-01-01/2024-12-31"


def _make_aoi(lat: float, lon: float) -> dict:
    half_lat = _HALF_SIZE_DEG
    half_lon = _HALF_SIZE_DEG / math.cos(math.radians(lat))
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon - half_lon, lat - half_lat],
                [lon + half_lon, lat - half_lat],
                [lon + half_lon, lat + half_lat],
                [lon - half_lon, lat + half_lat],
                [lon - half_lon, lat - half_lat],
            ]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Download NAIP imagery")
    parser.add_argument(
        "location",
        choices=_LOCATIONS.keys(),
        help="Location to download",
    )
    args = parser.parse_args()

    name = args.location
    lat, lon = _LOCATIONS[name]
    aoi = _make_aoi(lat, lon)
    area_shape = shape(aoi)

    out_dir = _OUTPUT_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Location: {name} ({lat}, {lon})")

    catalog = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )

    search = catalog.search(
        collections=["naip"],
        intersects=aoi,
        datetime=_DATETIME_RANGE,
    )
    items = search.item_collection()
    print(f"Found {len(items)} NAIP items")

    if not items:
        print("No items found. Try adjusting the area or date range.")
        return

    target_area = area_shape.area

    def overlap_ratio(item):
        return shape(item.geometry).intersection(area_shape).area / target_area

    item = max(items, key=overlap_ratio)
    overlap = overlap_ratio(item)
    assert item.datetime is not None
    print(f"\n{item.id} — date: {item.datetime.date()}, overlap: {overlap:.1%}")

    href = item.assets["image"].href
    print("  Opening remote COG...")

    with rasterio.open(href) as src:
        crs = src.crs
        print(f"  Full tile: {src.width}x{src.height}, CRS: {crs}")

        transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        minx, miny, maxx, maxy = area_shape.bounds
        left, bottom = transformer.transform(minx, miny)
        right, top = transformer.transform(maxx, maxy)

        window = rasterio.windows.from_bounds(
            left, bottom, right, top, transform=src.transform
        )
        window = window.round_offsets().round_lengths()
        window = window.intersection(
            rasterio.windows.Window(0, 0, src.width, src.height)  # ty: ignore[too-many-positional-arguments]  # attrs-generated __init__
        )

        if window.width == 0 or window.height == 0:
            print("No overlap with raster bounds.")
            return

        w, h = int(window.width), int(window.height)
        n_bands = src.count
        itemsize = np.dtype(src.dtypes[0]).itemsize
        total_mb = w * h * n_bands * itemsize / 1024 / 1024
        print(f"  Reading window: {w}x{h} pixels ({total_mb:.1f} MB)")

        chunk_size = 256
        data = np.empty((n_bands, h, w), dtype=src.dtypes[0])
        n_chunks = (h + chunk_size - 1) // chunk_size
        bytes_per_row = w * n_bands * itemsize
        bar_format = (
            "  Downloading: {percentage:3.0f}%|{bar}|"
            " {n:.1f}/{total:.1f}MB"
            " [{elapsed}<{remaining}, {rate_fmt}]"
        )
        with tqdm(
            total=total_mb,
            unit="MB",
            unit_scale=False,
            desc="  Downloading",
            bar_format=bar_format,
        ) as pbar:
            for ci in range(n_chunks):
                row_off = ci * chunk_size
                rows = min(chunk_size, h - row_off)
                chunk_window = rasterio.windows.Window(
                    window.col_off,  # ty: ignore[too-many-positional-arguments]  # attrs-generated __init__
                    window.row_off + row_off,
                    w,
                    rows,
                )
                data[:, row_off : row_off + rows, :] = src.read(window=chunk_window)
                pbar.update(rows * bytes_per_row / 1024 / 1024)
        win_transform = src.window_transform(window)

        tiff_path = out_dir / f"{item.id}.tif"
        profile = src.profile.copy()
        profile.update(
            width=w,
            height=h,
            transform=win_transform,
        )
        with rasterio.open(tiff_path, "w", **profile) as dst:
            dst.write(data)
        print(f"  Saved: {tiff_path} ({data.shape[0]} bands)")

    rgb = np.transpose(data[:3], (1, 2, 0))
    if rgb.dtype != np.uint8:
        max_val = rgb.max()
        if max_val > 0:
            rgb = (rgb / max_val * 255).astype(np.uint8)
        else:
            rgb = rgb.astype(np.uint8)
    png_path = out_dir / f"{item.id}.png"
    Image.fromarray(rgb).save(png_path)
    print(f"  Saved: {png_path}")

    print(f"\nDone! Images saved to {out_dir}/")


if __name__ == "__main__":
    main()
