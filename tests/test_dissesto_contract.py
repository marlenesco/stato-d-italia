import json
import zipfile
from pathlib import Path

from stato_italia import dissesto
from stato_italia.dissesto import _record, fetch_dissesto


def _territory() -> dict:
    return {
        "territory_id": "it:region:12",
        "territory_version_id": "it:region:12@2024-01-01",
        "level": "region",
        "istat_code": "12",
    }


def test_idrogeo_minus_one_is_unavailable_not_zero() -> None:
    record = _record(
        row={"ar_fr_p4": -1}, row_number=0, level="region", territory=_territory(),
        field="ar_fr_p4", spec={"metric_id": "hydrogeological_landslide_very_high_hazard_area_km2", "unit_ucum": "km2", "reference_year": 2024},
        source_hash="a" * 64, ingested_at="2026-08-25T00:00:00+00:00",
    )

    assert record["value_decimal"] is None
    assert record["value_state"] == "unavailable"
    assert record["quality_flags"] == ["source_value_unavailable"]


def test_idrogeo_fetch_archives_official_api_responses(tmp_path: Path, monkeypatch) -> None:
    def fake_download(_url: str, destination: Path, _source_id: str) -> dict:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.suffix == ".xlsx":
            with zipfile.ZipFile(destination, "w") as workbook:
                workbook.writestr("[Content_Types].xml", "<Types />")
        else:
            destination.write_bytes(b"%PDF-1.4\n")
        return {"unchanged": True}

    def fake_get_json(url: str) -> bytes:
        suffix = url.removeprefix(dissesto.API_BASE_URL)
        exports = {
            "/regioni/export": [{"cod_reg": 1}],
            "/province/export": [{"cod_prov": 1}],
            "/comuni/export": [{"pro_com": 1}],
        }
        if suffix in exports:
            return json.dumps(exports[suffix]).encode()
        row = {"ar_id_p3": 1, "pop_idr_p3": 2, "ar_fr_p4": 3, "pop_fr_p4": 4}
        return json.dumps([row]).encode()

    monkeypatch.setattr(dissesto, "download", fake_download)
    monkeypatch.setattr(dissesto, "_get_json", fake_get_json)
    result = fetch_dissesto(tmp_path)

    archive = tmp_path / "raw" / dissesto.SOURCE_ID / dissesto.RAW_ARCHIVE
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.namelist() == ["country/export.json", "region/export.json", "province/export.json", "municipality/export.json"]
    assert result["source"]["response_count"] == 4
