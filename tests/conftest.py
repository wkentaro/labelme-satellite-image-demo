import shutil
from pathlib import Path

import pytest


@pytest.fixture()
def data_path(tmp_path: Path) -> Path:
    data_path = tmp_path / "data"
    shutil.copytree(Path(__file__).parent / "data", data_path)
    return data_path
