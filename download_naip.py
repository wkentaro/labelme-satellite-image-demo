#!/usr/bin/env python3

import argparse
import math
from pathlib import Path
from typing import Final

import numpy as np
import planetary_computer
import pystac
import pystac_client
import rasterio
import rasterio.windows
from PIL import Image
from pyproj import Transformer
from shapely.geometry import Polygon
from shapely.geometry import shape
from tqdm import tqdm


def _lat_lon_to_aoi_polygon(lat: float, lon: float) -> dict:
    HALF_SIZE_DEG: Final = 0.02
    half_lat = HALF_SIZE_DEG
    half_lon = HALF_SIZE_DEG / math.cos(math.radians(lat))
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


def _find_most_overlapping_item(aoi: dict, area_shape: Polygon) -> pystac.Item | None:
    DATETIME_RANGE: Final = "2020-01-01/2024-12-31"

    catalog = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )
    search = catalog.search(
        collections=["naip"],
        intersects=aoi,
        datetime=DATETIME_RANGE,
    )
    items = search.item_collection()
    print(f"Found {len(items)} NAIP items")

    if not items:
        return None

    target_area = area_shape.area

    def overlap_ratio(item: pystac.Item) -> float:
        return shape(item.geometry).intersection(area_shape).area / target_area

    return max(items, key=overlap_ratio)


def _geo_bounds_to_pixel_window(
    src: rasterio.DatasetReader, area_shape: Polygon
) -> rasterio.windows.Window | None:
    transformer = Transformer.from_crs(
        crs_from="EPSG:4326", crs_to=src.crs, always_xy=True
    )
    minx, miny, maxx, maxy = area_shape.bounds
    left, bottom = transformer.transform(xx=minx, yy=miny)
    right, top = transformer.transform(xx=maxx, yy=maxy)

    window = rasterio.windows.from_bounds(
        left, bottom, right, top, transform=src.transform
    )
    window = window.round_offsets().round_lengths()
    window = window.intersection(
        rasterio.windows.Window(0, 0, src.width, src.height)  # ty: ignore[too-many-positional-arguments]  # attrs-generated __init__
    )

    if window.width == 0 or window.height == 0:
        return None
    return window


def _read_raster_in_chunks(
    src: rasterio.DatasetReader,
    window: rasterio.windows.Window,
) -> np.ndarray:
    # Read in row-chunks to avoid loading the entire raster into memory at once
    CHUNK_SIZE: Final = 256
    w, h = int(window.width), int(window.height)
    n_bands = src.count
    itemsize = np.dtype(src.dtypes[0]).itemsize
    total_mb = w * h * n_bands * itemsize / 1024 / 1024

    print(f"  Reading window: {w}x{h} pixels ({total_mb:.1f} MB)")

    data = np.empty((n_bands, h, w), dtype=src.dtypes[0])
    n_chunks = (h + CHUNK_SIZE - 1) // CHUNK_SIZE
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
            row_off = ci * CHUNK_SIZE
            rows = min(CHUNK_SIZE, h - row_off)
            chunk_window = rasterio.windows.Window(
                window.col_off,  # ty: ignore[too-many-positional-arguments]  # attrs-generated __init__
                window.row_off + row_off,
                w,
                rows,
            )
            data[:, row_off : row_off + rows, :] = src.read(window=chunk_window)
            pbar.update(rows * bytes_per_row / 1024 / 1024)

    return data


def _write_cropped_geotiff(
    path: Path,
    data: np.ndarray,
    profile: dict,
    window: rasterio.windows.Window,
    win_transform: rasterio.transform.Affine,
) -> None:
    cropped_profile = {
        **profile,
        "width": int(window.width),
        "height": int(window.height),
        "transform": win_transform,
    }
    with rasterio.open(path, "w", **cropped_profile) as dst:
        dst.write(data)
    print(f"  Saved: {path} ({data.shape[0]} bands)")


def _write_rgb_png(path: Path, data: np.ndarray) -> None:
    rgb = np.transpose(data[:3], (1, 2, 0))
    if rgb.dtype != np.uint8:
        max_val = rgb.max()
        if max_val > 0:
            rgb = (rgb / max_val * 255).astype(np.uint8)
        else:
            rgb = rgb.astype(np.uint8)
    Image.fromarray(obj=rgb).save(path)
    print(f"  Saved: {path}")


def _download_naip(name: str, lat: float, lon: float) -> None:
    aoi = _lat_lon_to_aoi_polygon(lat=lat, lon=lon)
    area_shape = shape(aoi)

    OUTPUT_DIR: Final = Path("data/naip")
    out_dir = OUTPUT_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Location: {name} ({lat}, {lon})")

    item = _find_most_overlapping_item(aoi=aoi, area_shape=area_shape)
    if item is None:
        print("No items found. Try adjusting the area or date range.")
        return

    assert item.datetime is not None
    print(f"\n{item.id} — date: {item.datetime.date()}")

    href = item.assets["image"].href
    print("  Opening remote COG...")

    with rasterio.open(href) as src:
        print(f"  Full tile: {src.width}x{src.height}, CRS: {src.crs}")

        window = _geo_bounds_to_pixel_window(src=src, area_shape=area_shape)
        if window is None:
            print("No overlap with raster bounds.")
            return

        data = _read_raster_in_chunks(src=src, window=window)
        win_transform = src.window_transform(window)

        tiff_path = out_dir / f"{item.id}.tif"
        _write_cropped_geotiff(
            path=tiff_path,
            data=data,
            profile=src.profile,
            window=window,
            win_transform=win_transform,
        )

    png_path = out_dir / f"{item.id}.png"
    _write_rgb_png(path=png_path, data=data)

    print(f"\nDone! Images saved to {out_dir}/")


def main() -> None:
    LOCATIONS: Final[dict[str, tuple[float, float]]] = {
        "cushing": (35.9485, -96.7422),
        "houston": (29.7428, -95.1163),
        "alta-wind": (35.0174, -118.2948),
    }

    parser = argparse.ArgumentParser(description="Download NAIP imagery")
    parser.add_argument(
        "location",
        choices=LOCATIONS.keys(),
        help="Location to download",
    )
    args = parser.parse_args()

    lat, lon = LOCATIONS[args.location]
    _download_naip(name=args.location, lat=lat, lon=lon)


if __name__ == "__main__":
    main()
