import json
from pathlib import Path
from typing import Final

import pytest

from labelme_to_geojson import _convert

_STEM: Final = "ok_m_3509603_nw_14_030_20230615_20230927_x3004_y11271_w499_h846"


@pytest.fixture()
def _geojson_expected(data_path: Path) -> dict:
    with open(data_path / f"{_STEM}.geojson") as f:
        return json.load(f)


@pytest.fixture()
def _geojson_actual(data_path: Path, _geojson_expected: dict) -> dict:
    # Remove expected file so _convert writes a fresh one
    (data_path / f"{_STEM}.geojson").unlink()

    _convert(labelme_json_path=data_path / f"{_STEM}.json")

    with open(data_path / f"{_STEM}.geojson") as f:
        return json.load(f)


def test_convert_produces_valid_geojson(
    _geojson_actual: dict, _geojson_expected: dict
) -> None:
    assert _geojson_actual["type"] == "FeatureCollection"
    assert _geojson_actual["name"] == _STEM
    assert _geojson_actual["crs"] == _geojson_expected["crs"]
    assert len(_geojson_actual["features"]) == len(_geojson_expected["features"])


def test_convert_preserves_features(
    _geojson_actual: dict, _geojson_expected: dict
) -> None:
    for result_feat, expected_feat in zip(
        _geojson_actual["features"], _geojson_expected["features"], strict=True
    ):
        assert result_feat["type"] == "Feature"
        assert result_feat["properties"] == expected_feat["properties"]
        assert result_feat["geometry"]["type"] == expected_feat["geometry"]["type"]

        for result_ring, expected_ring in zip(
            result_feat["geometry"]["coordinates"],
            expected_feat["geometry"]["coordinates"],
            strict=True,
        ):
            assert len(result_ring) == len(expected_ring)
            for result_coord, expected_coord in zip(
                result_ring, expected_ring, strict=True
            ):
                assert result_coord == pytest.approx(expected_coord)
