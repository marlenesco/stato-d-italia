import zipfile
from pathlib import Path

from stato_italia import territories
from stato_italia.territories import boundary_url


def test_istat_url_eras_are_explicit() -> None:
    assert boundary_url(2006).endswith("generalizzati/Limiti01012006_g.zip")
    assert boundary_url(2021).endswith("generalizzati/Limiti2021_g.zip")
    assert boundary_url(2024).endswith("generalizzati/2024/Limiti01012024_g.zip")
    assert boundary_url(2025).endswith("generalizzati/2025/Limiti01012025_g.zip")


def test_boundary_ingest_creates_partition_directories(tmp_path: Path, monkeypatch) -> None:
    def fake_download(_url: str, destination: Path, _source_id: str) -> dict:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr("placeholder", "")
        return {"unchanged": False}

    def fake_features(_path: Path, level: str, reference_date: str) -> list[dict]:
        return [{
            "territory_id": f"it:{level}:001",
            "territory_version_id": f"it:{level}:001@{reference_date}",
            "level": level,
            "istat_code": "001",
            "name": "Test",
            "name_normalized": "test",
            "parent_istat_code": None,
            "reference_date": reference_date,
            "geometry": {"type": "Point", "coordinates": [12.0, 42.0]},
        }]

    monkeypatch.setattr(territories, "download", fake_download)
    monkeypatch.setattr(territories, "_shape_file", lambda *_args: Path("unused.shp"))
    monkeypatch.setattr(territories, "_features", fake_features)

    canonical = tmp_path / "canonical"
    territories.ingest_boundaries(tmp_path / "data", canonical, years=(2025,))

    for level in ("municipality", "province", "region"):
        assert (canonical / "territories" / "reference_year=2025" / f"{level}.parquet").exists()
