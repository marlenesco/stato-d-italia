from __future__ import annotations

import hashlib
import zipfile
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import box
from shapely.ops import transform

from stato_italia.bigbang_historical_processing import (
    _reject_structural_regional_mismatch,
    build_bigbang_historical_processing_plan,
    load_bound_territories,
    run_bigbang_historical_processing,
)
from stato_italia.bigbang_historical_territory_policy import TerritoryGeometryVersion
from stato_italia.bigbang_raster_poc import METRIC_SPECS, RasterMetricSpec, validate_archive_structure
from stato_italia.common import sha256_file


def _write_raster(path: Path) -> Path:
    geometry = box(10, 45, 10.01, 45.01)
    project = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True).transform
    projected = transform(project, geometry)
    cell_size = max(projected.bounds[2] - projected.bounds[0], projected.bounds[3] - projected.bounds[1]) + 20
    with rasterio.open(
        path,
        "w",
        driver="AAIGrid",
        width=2,
        height=2,
        count=1,
        dtype="float32",
        crs="EPSG:3035",
        transform=from_origin(projected.bounds[0] - 10, projected.bounds[3] + cell_size + 10, cell_size, cell_size),
        nodata=-9999,
    ) as destination:
        destination.write(np.full((2, 2), 7.0, dtype="float32"), 1)
    return geometry


def _historical_spec(tmp_path: Path) -> RasterMetricSpec:
    source = tmp_path / "source.asc"
    _write_raster(source)
    projection = source.with_suffix(".prj")
    archive = tmp_path / "TP_ANNUAL_1951-2025.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for year in range(1951, 2026):
            output.writestr(f"tp_{year}_yyc.asc", source.read_bytes())
            output.writestr(f"tp_{year}_yyc.prj", projection.read_bytes())
    with rasterio.open(source) as dataset:
        contract = {
            "archive_name": archive.name,
            "archive_sha256": sha256_file(archive),
            "archive_bytes": archive.stat().st_size,
            "archive_member_count": 150,
            "archive_first_year": 1951,
            "archive_last_year": 2025,
            "member_prefix": "tp",
            "reference_year": 2025,
            "raster_bytes": source.stat().st_size,
            "raster_sha256": sha256_file(source),
            "format": "AAIGrid",
            "crs": "EPSG:3035",
            "width": dataset.width,
            "height": dataset.height,
            "cell_size_m": abs(dataset.transform.a),
            "nodata": dataset.nodata,
            "bounds": list(dataset.bounds),
        }
    return replace(METRIC_SPECS["TP"], contract=contract)


def _versions(years: tuple[int, ...]) -> list[TerritoryGeometryVersion]:
    return [
        TerritoryGeometryVersion(
            territory_level="province",
            reference_year=year,
            territory_reference_date=f"{year}-01-01",
            territory_source="ISTAT",
            geometry_reference=f"canonical/territories/reference_year={year}/province.parquet",
        )
        for year in years
    ]


def _write_snapshot(root: Path, year: int, level: str, count: int, geometry) -> None:
    reference_date = f"{year}-01-01"
    path = root / "territories" / f"reference_year={year}" / f"{level}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "territory_id": f"it:{level}:{index:03d}",
            "territory_version_id": f"it:{level}:{index:03d}@{reference_date}",
            "level": level,
            "name": f"{level}-{index}",
            "reference_date": reference_date,
            "geometry_wkb": geometry.wkb,
        }
        for index in range(1, count + 1)
    ]
    pd.DataFrame(rows).to_parquet(path, index=False)


def _write_historical_canonical(root: Path, geometry) -> Path:
    for year, province_count in ((2015, 2), (2016, 3)):
        _write_snapshot(root, year, "province", province_count, geometry)
        _write_snapshot(root, year, "region", 20, geometry)
    official_rows = []
    for year in (2015, 2016):
        official_rows.extend({
            "metric_id": METRIC_SPECS["TP"].official_metric_id,
            "reference_year": year,
            "territory_level": "region",
            "territory_id": f"it:region:{index:03d}",
            "value_decimal": 7.0,
            "unit_ucum": "mm",
        } for index in range(1, 21))
    path = root / "water/dataset_version=bigbang-10-1951-2025/observations.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(official_rows).to_parquet(path, index=False)
    return path


def test_processing_plan_is_policy_driven_and_excludes_unsupported_and_2021() -> None:
    plan = build_bigbang_historical_processing_plan(_versions((2015, 2016)))
    included = [entry.reference_year for entry in plan if entry.process_provinces]
    assert included == [2015, 2016]
    assert next(entry for entry in plan if entry.reference_year == 2014).process_provinces is False
    assert next(entry for entry in plan if entry.reference_year == 2021).process_provinces is False


@pytest.mark.parametrize(("reference_date", "version_id", "error"), [
    ("2014-01-01", "it:province:001@2014-01-01", "reference_date"),
    ("2015-01-01", "it:province:001@2014-01-01", "territory_version_id"),
])
def test_geometry_binding_rejects_policy_mismatches(
    tmp_path: Path, reference_date: str, version_id: str, error: str,
) -> None:
    path = tmp_path / "territories/reference_year=2015/province.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([{
        "territory_version_id": version_id,
        "level": "province",
        "reference_date": reference_date,
        "geometry_wkb": box(10, 45, 10.01, 45.01).wkb,
    }]).to_parquet(path, index=False)
    with pytest.raises(ValueError, match=error):
        load_bound_territories(
            tmp_path,
            territory_level="province",
            territory_reference_date="2015-01-01",
            geometry_reference="canonical/territories/reference_year=2015/province.parquet",
        )


def test_historical_archive_fails_closed_for_missing_or_duplicate_requested_member(tmp_path: Path) -> None:
    spec = _historical_spec(tmp_path)
    archive = tmp_path / str(spec.contract["archive_name"])
    with zipfile.ZipFile(archive) as source:
        entries = [(item.filename, source.read(item.filename)) for item in source.infolist() if item.filename != "tp_2015_yyc.asc"]
    missing = tmp_path / "missing.zip"
    with zipfile.ZipFile(missing, "w") as output:
        for name, content in entries:
            output.writestr(name, content)
    missing_spec = replace(spec, contract={**spec.contract, "archive_name": missing.name, "archive_sha256": sha256_file(missing), "archive_bytes": missing.stat().st_size, "archive_member_count": 149})
    with pytest.raises(ValueError, match="archive structure"):
        validate_archive_structure(missing, missing_spec, 2015)

    duplicate = tmp_path / "duplicate.zip"
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(duplicate, "w") as output:
            for name, content in entries:
                output.writestr(name, content)
            output.writestr("tp_2015_yyc.asc", b"first")
            output.writestr("tp_2015_yyc.asc", b"second")
    duplicate_spec = replace(spec, contract={**spec.contract, "archive_name": duplicate.name, "archive_sha256": sha256_file(duplicate), "archive_bytes": duplicate.stat().st_size, "archive_member_count": 151})
    with pytest.raises(ValueError, match="duplicate member"):
        validate_archive_structure(duplicate, duplicate_spec, 2015)


def test_historical_processing_uses_variable_cardinality_and_preserves_official_canonical(tmp_path: Path) -> None:
    geometry = _write_raster(tmp_path / "grid.asc")
    canonical_root = tmp_path / "canonical"
    official_path = _write_historical_canonical(canonical_root, geometry)
    archive_dir = tmp_path / "archives"
    archive_dir.mkdir()
    spec = _historical_spec(archive_dir)
    report = run_bigbang_historical_processing(
        archive_dir,
        canonical_root,
        tmp_path / "derived",
        tmp_path / "report.json",
        metric_specs={"TP": spec},
    )
    assert report["supportedProvinceYears"] == [2015, 2016]
    assert report["derivedProvinceRecords"] == 5
    assert report["metrics"]["TP"]["years"]["2015"]["provinceRecordCount"] == 2
    assert report["metrics"]["TP"]["years"]["2016"]["provinceRecordCount"] == 3
    assert report["metrics"]["TP"]["years"]["2015"]["regionalValidation"]["status"] == "executed"
    assert report["officialCanonical"]["sha256Before"] == sha256_file(official_path)
    assert report["officialCanonical"]["sha256After"] == sha256_file(official_path)
    derived = pd.read_parquet(report["derivedArtifact"])
    assert len(derived) == 5
    assert derived["derived_observation_id"].is_unique
    assert not (canonical_root / "water/dataset_version=bigbang-10-1951-2025/derived.parquet").exists()


def test_regional_structural_scale_mismatch_fails_closed() -> None:
    comparison = pd.DataFrame({
        "official_value_mm": [1.0, 2.0],
        "derived_raster_value_mm": [1000.0, 2000.0],
    })
    with pytest.raises(ValueError, match="unit-scale mismatch"):
        _reject_structural_regional_mismatch(comparison, "TP", 2015)
