import contextlib
import io
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.errors import NotGeoreferencedWarning
from rasterio.transform import Affine
from rasterio.transform import from_origin
from shapely.geometry import shape

from labelme_to_geojson import _convert


def _write_labelme_json(path: Path, *, image_path: str) -> None:
    labelme_payload = {
        "version": "test",
        "flags": {},
        "shapes": [
            {
                "label": "tank",
                "points": [[10.0, 12.0], [14.0, 12.0]],
                "group_id": None,
                "description": "",
                "shape_type": "circle",
                "flags": {},
                "mask": None,
            }
        ],
        "imagePath": image_path,
        "imageData": None,
        "imageHeight": 64,
        "imageWidth": 64,
    }
    path.write_text(json.dumps(labelme_payload), encoding="utf-8")


def _write_png(path: Path) -> None:
    rgb = np.zeros((64, 64, 3), dtype=np.uint8)
    Image.fromarray(rgb).save(path)


def _write_geotiff(path: Path, *, crs: str | None) -> Affine:
    transform = from_origin(500000.0, 4200000.0, 1.0, 1.0)
    data = np.zeros((1, 64, 64), dtype=np.uint8)
    profile: dict = {
        "driver": "GTiff",
        "height": 64,
        "width": 64,
        "count": 1,
        "dtype": "uint8",
        "transform": transform,
    }
    if crs is not None:
        profile["crs"] = crs

    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data)

    return transform


def test_prefers_same_stem_geotiff_when_imagepath_is_png(tmp_path: Path) -> None:
    json_path = tmp_path / "tile.json"
    png_path = tmp_path / "tile.png"
    tif_path = tmp_path / "tile.tif"

    transform = _write_geotiff(tif_path, crs="EPSG:26914")
    _write_png(png_path)
    _write_labelme_json(json_path, image_path=png_path.name)

    with contextlib.redirect_stdout(io.StringIO()):
        _convert(json_path)

    output_path = json_path.with_suffix(".geojson")
    geojson = json.loads(output_path.read_text(encoding="utf-8"))

    assert geojson["crs"]["properties"]["name"] == "EPSG:26914"
    geometry = shape(geojson["features"][0]["geometry"])
    expected_center = transform * (10.0, 12.0)

    assert geometry.centroid.x == pytest.approx(expected_center[0], abs=1e-6)
    assert geometry.centroid.y == pytest.approx(expected_center[1], abs=1e-6)
    assert geometry.centroid.x > 100000


def test_raises_on_non_georeferenced_raster(tmp_path: Path) -> None:
    json_path = tmp_path / "tile.json"
    png_path = tmp_path / "tile.png"

    _write_png(png_path)
    _write_labelme_json(json_path, image_path=png_path.name)

    with pytest.warns(NotGeoreferencedWarning):
        with pytest.raises(ValueError, match="Raster is not georeferenced"):
            with contextlib.redirect_stdout(io.StringIO()):
                _convert(json_path)
