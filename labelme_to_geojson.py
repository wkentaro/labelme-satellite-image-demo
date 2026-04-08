import argparse
import json
import math
import pathlib
import warnings

import rasterio
import rasterio.transform
from shapely.geometry import Point
from shapely.geometry import Polygon
from shapely.geometry import mapping

_UNSUPPORTED_SHAPE_TYPES = ("line", "linestrip", "point")


def _shape_to_geo_polygon(
    annotation: dict, transform: rasterio.transform.Affine
) -> Polygon | None:
    shape_type = annotation.get("shape_type", "polygon")
    points = annotation["points"]

    if shape_type in ("polygon", "rectangle"):
        return _pixel_polygon_to_geo(polygon=Polygon(points), transform=transform)

    if shape_type == "circle":
        if len(points) != 2:
            raise ValueError(
                f"circle shape requires exactly 2 points, got {len(points)}"
                f" (label={annotation['label']!r})"
            )
        (cx, cy), (ex, ey) = points
        geo_center = transform * (cx, cy)
        geo_edge = transform * (ex, ey)
        geo_radius = math.hypot(
            geo_edge[0] - geo_center[0], geo_edge[1] - geo_center[1]
        )
        return Point(geo_center).buffer(distance=geo_radius)

    if shape_type in _UNSUPPORTED_SHAPE_TYPES:
        warnings.warn(
            f"Skipping shape_type={shape_type!r} (label={annotation['label']!r}): "
            "not convertible to polygon",
        )
        return None

    warnings.warn(
        f"Skipping unknown shape_type={shape_type!r} (label={annotation['label']!r})",
    )
    return None


def _pixel_polygon_to_geo(
    polygon: Polygon, transform: rasterio.transform.Affine
) -> Polygon:
    shell = [transform * coord for coord in polygon.exterior.coords]
    holes = [[transform * coord for coord in ring.coords] for ring in polygon.interiors]
    return Polygon(shell, holes)


def _build_features(
    shapes: list[dict], transform: rasterio.transform.Affine
) -> list[dict]:
    features = []
    for annotation in shapes:
        polygon = _shape_to_geo_polygon(annotation=annotation, transform=transform)
        if polygon is None:
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {"label": annotation["label"]},
                "geometry": mapping(polygon),
            }
        )
    return features


def _convert(labelme_json_path: pathlib.Path) -> None:
    with open(labelme_json_path) as f:
        labelme_data = json.load(f)

    tiff_path = (labelme_json_path.parent / labelme_data["imagePath"]).resolve()
    if not tiff_path.is_relative_to(labelme_json_path.parent.resolve()):
        raise ValueError(f"imagePath escapes annotation directory: {tiff_path}")

    with rasterio.open(tiff_path) as src:
        transform = src.transform
        crs = src.crs

    features = _build_features(shapes=labelme_data["shapes"], transform=transform)

    geojson = {
        "type": "FeatureCollection",
        "name": labelme_json_path.stem,
        "crs": {
            "type": "name",
            "properties": {"name": str(crs)},
        },
        "features": features,
    }

    output_path = labelme_json_path.with_suffix(".geojson")
    with open(output_path, "w") as f:
        json.dump(geojson, f, indent=2)

    print(f"Converted {len(features)} features to {output_path} (CRS: {crs})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "labelme_json",
        type=pathlib.Path,
        help="path to LabelMe JSON annotation file",
    )
    args = parser.parse_args()
    _convert(labelme_json_path=args.labelme_json)


if __name__ == "__main__":
    main()
