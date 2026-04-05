#!/usr/bin/env python3

import argparse
from pathlib import Path
from typing import Final

import cv2
import numpy as np
import rasterio
import rasterio.windows


def _read_rgb_for_display(src: rasterio.DatasetReader) -> np.ndarray:
    rgb = src.read([1, 2, 3])
    rgb = np.transpose(rgb, (1, 2, 0))
    if rgb.dtype != np.uint8:
        max_val = rgb.max()
        if max_val > 0:
            rgb = (rgb / max_val * 255).astype(np.uint8)
        else:
            rgb = rgb.astype(np.uint8)
    return rgb


def _downscale_for_display(rgb: np.ndarray) -> tuple[np.ndarray, float]:
    MAX_DISPLAY_SIZE: Final = 1500
    h, w = rgb.shape[:2]
    if max(h, w) <= MAX_DISPLAY_SIZE:
        return rgb, 1.0
    scale = MAX_DISPLAY_SIZE / max(h, w)
    small = cv2.resize(rgb, (int(w * scale), int(h * scale)))
    return small, scale


def _select_roi(rgb: np.ndarray) -> tuple[int, int, int, int] | None:
    WINDOW_NAME: Final = "Select ROI (ENTER to confirm, C to cancel)"
    display, scale = _downscale_for_display(rgb)
    bgr = cv2.cvtColor(display, cv2.COLOR_RGB2BGR)
    roi = cv2.selectROI(WINDOW_NAME, bgr, showCrosshair=True, fromCenter=False)
    cv2.destroyAllWindows()

    col_off, row_off, width, height = roi
    if width == 0 or height == 0:
        return None
    return (
        int(col_off / scale),
        int(row_off / scale),
        int(width / scale),
        int(height / scale),
    )


def _crop_and_save(
    src_path: Path,
    col_off: int,
    row_off: int,
    width: int,
    height: int,
) -> None:
    with rasterio.open(src_path) as src:
        width = min(width, src.width - col_off)
        height = min(height, src.height - row_off)
        window = rasterio.windows.Window(
            col_off=col_off,
            row_off=row_off,
            width=width,
            height=height,
        )
        transform = src.window_transform(window)
        data = src.read(window=window)

        out_path = src_path.with_stem(
            f"{src_path.stem}_x{col_off}_y{row_off}_w{width}_h{height}"
        )
        profile = {
            **src.profile,
            "width": width,
            "height": height,
            "transform": transform,
        }
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(data)

    print(f"Saved: {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Crop GeoTIFF with interactive ROI")
    parser.add_argument("input", type=Path, help="Input GeoTIFF file")
    args = parser.parse_args()

    with rasterio.open(args.input) as src:
        rgb = _read_rgb_for_display(src)

    print(f"Image size: {rgb.shape[1]}x{rgb.shape[0]}")
    print("Draw a rectangle, press ENTER to confirm, C to cancel.")

    roi = _select_roi(rgb)
    if roi is None:
        print("No ROI selected.")
        return

    col_off, row_off, width, height = roi
    print(f"ROI: col_off={col_off}, row_off={row_off}, width={width}, height={height}")

    _crop_and_save(
        src_path=args.input,
        col_off=col_off,
        row_off=row_off,
        width=width,
        height=height,
    )


if __name__ == "__main__":
    main()
