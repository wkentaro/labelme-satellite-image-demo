import argparse
import json
import pathlib

import rasterio
import rasterio.transform
from shapely.geometry import Polygon
from shapely.geometry import mapping


def _build_features(
    shapes: list[dict], transform: rasterio.transform.Affine
) -> list[dict]:
    return [
        {
            "type": "Feature",
            "properties": {"label": annotation["label"]},
            "geometry": mapping(
                Polygon(
                    [transform * (col, row) for col, row in annotation["points"]]
                )
            ),
        }
        for annotation in shapes
    ]


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
