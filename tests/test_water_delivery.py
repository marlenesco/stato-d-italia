import json
from pathlib import Path

import pandas as pd
import pytest
from shapely.geometry import box

from stato_italia.water_delivery import generate_water_delivery


METRICS = (
    ("water_total_precipitation_mm", "water_total_precipitation_mm_zonal_mean"),
    ("water_actual_evapotranspiration_mm", "water_actual_evapotranspiration_mm_zonal_mean"),
    ("water_internal_flow_mm", "water_internal_flow_mm_zonal_mean"),
    ("water_aquifer_recharge_mm", "water_aquifer_recharge_mm_zonal_mean"),
    ("water_surface_runoff_mm", "water_surface_runoff_mm_zonal_mean"),
)


def _territory_rows(year: int) -> list[dict]:
    return [{
        "territory_id": "it:province:001", "territory_version_id": f"it:province:001@{year}-01-01",
        "level": "province", "istat_code": "001", "name": "Provincia test", "parent_istat_code": "01",
        "geometry_wkb": box(12, 42, 12.1, 42.1).wkb,
    }]


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    canonical_root = tmp_path / "canonical"
    for year in (2006, 2025):
        path = canonical_root / "territories" / f"reference_year={year}" / "province.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(_territory_rows(year)).to_parquet(path)

    official_rows = []
    derived_rows = []
    for position, (official_metric, derived_metric) in enumerate(METRICS, start=1):
        official_rows.append({
            "metric_id": official_metric, "reference_year": 2025, "territory_id": "it:region:01",
            "territory_version_id": "it:region:01@2025-01-01", "territory_level": "region",
            "value_decimal": position, "unit_ucum": "mm", "period_end": "2025-12-31",
        })
        for year in (2006, 2025):
            version_year = 1989 if year == 2006 else year
            derived_rows.append({
                "derived_metric_id": derived_metric, "reference_year": year, "territory_id": "it:province:001",
                "territory_version_id": f"it:province:001@{version_year}-01-01", "territory_level": "province",
                "value_decimal": position + year / 10_000, "unit_ucum": "mm",
                "territory_geometry_reference": f"canonical/territories/reference_year={year}/province.parquet#it:province:001@{version_year}-01-01",
                "algorithm_version": "bigbang-tp-zonal-area-weighted-v1", "official_status": "derived_by_stato_italia",
            })
    official_path = canonical_root / "water" / "dataset_version=test" / "observations.parquet"
    official_path.parent.mkdir(parents=True)
    pd.DataFrame(official_rows).to_parquet(official_path)
    derived_path = tmp_path / "derived" / "water" / "observations.parquet"
    derived_path.parent.mkdir(parents=True)
    pd.DataFrame(derived_rows).to_parquet(derived_path)
    return official_path, derived_path, canonical_root, tmp_path / "delivery"


def test_water_delivery_keeps_official_regions_and_exposes_derived_provinces(tmp_path: Path) -> None:
    official_path, derived_path, canonical_root, destination = _inputs(tmp_path)

    report = generate_water_delivery(official_path, derived_path, canonical_root, destination, "release-test", force=True)

    index = json.loads((destination / "water/index.json").read_text())
    maps = [json.loads((destination / logical.removeprefix("delivery/")).read_text()) for logical in index["maps"]]
    official = [payload for payload in maps if payload["territoryLevel"] == "region"]
    province = [payload for payload in maps if payload["territoryLevel"] == "province"]
    assert len(official) == 5
    assert all(payload["kind"] == "official_model_map_values" for payload in official)
    assert len(province) == 10
    assert {payload["metricId"] for payload in province} == {metric for _, metric in METRICS}
    assert {payload["periodEnd"][:4] for payload in province} == {"2006", "2025"}
    assert "2021" not in {payload["periodEnd"][:4] for payload in province}
    assert all(payload["officialStatus"] == "derived_by_stato_italia" for payload in province)
    assert {payload["territoryReferenceDate"] for payload in province if payload["periodEnd"].startswith("2006")} == {"2006-01-01"}
    assert all(index["mapGeometry"][logical] in index["geometry"] for logical in index["maps"])
    assert {index["mapGeometry"][logical] for logical in index["maps"] if "/province.json" in logical} == {
        "delivery/water/geometry/istat-province-2006.pmtiles",
        "delivery/water/geometry/istat-province-2025.pmtiles",
    }
    assert {path.name for path in report["files"] if path.suffix == ".pmtiles"} == {
        "istat-province-2006.pmtiles", "istat-province-2025.pmtiles",
    }


def test_water_delivery_fails_closed_for_missing_or_ambiguous_derived_geometry(tmp_path: Path) -> None:
    official_path, derived_path, canonical_root, destination = _inputs(tmp_path)
    table = pd.read_parquet(derived_path)
    table.loc[0, "territory_geometry_reference"] = "canonical/territories/reference_year=1999/province.parquet#it:province:001@1999-01-01"
    table.to_parquet(derived_path)
    with pytest.raises(ValueError, match="geometry is missing"):
        generate_water_delivery(official_path, derived_path, canonical_root, destination, "release-test", force=True)

    official_path, derived_path, canonical_root, destination = _inputs(tmp_path / "ambiguous")
    table = pd.read_parquet(derived_path)
    duplicate = table.iloc[[0]].copy()
    duplicate.loc[:, "territory_geometry_reference"] = "canonical/territories/reference_year=2025/province.parquet#it:province:001@2025-01-01"
    table = pd.concat([table, duplicate], ignore_index=True)
    table.to_parquet(derived_path)
    with pytest.raises(ValueError, match="Ambiguous BIGBANG derived map geometry"):
        generate_water_delivery(official_path, derived_path, canonical_root, destination, "release-test", force=True)


def test_water_delivery_requires_all_derived_bigbang_metrics(tmp_path: Path) -> None:
    official_path, derived_path, canonical_root, destination = _inputs(tmp_path)
    table = pd.read_parquet(derived_path)
    table = table[table["derived_metric_id"] != "water_surface_runoff_mm_zonal_mean"]
    table.to_parquet(derived_path)

    with pytest.raises(ValueError, match="lacks an expected metric"):
        generate_water_delivery(official_path, derived_path, canonical_root, destination, "release-test", force=True)
