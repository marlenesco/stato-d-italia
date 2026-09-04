from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from stato_italia.bigbang_historical_territory_policy import (
    ISTAT_BOUNDARIES_SOURCE,
    TerritoryGeometryVersion,
    build_bigbang_historical_support_matrix,
    inspect_canonical_territories,
    resolve_bigbang_territory_policy,
    write_bigbang_historical_support_report,
)


def _province_version(year: int, reference_date: str | None = None, **kwargs: object) -> TerritoryGeometryVersion:
    return TerritoryGeometryVersion(
        territory_level="province",
        reference_year=year,
        territory_reference_date=reference_date or f"{year}-01-01",
        territory_source=ISTAT_BOUNDARIES_SOURCE,
        geometry_reference=f"canonical/territories/reference_year={year}/province.parquet",
        **kwargs,
    )


def test_exact_province_geometry_is_derived_supported() -> None:
    result = resolve_bigbang_territory_policy(2015, "province", [_province_version(2015)])
    assert result.support_status == "derived_supported"
    assert result.territory_reference_date == "2015-01-01"
    assert result.geometry_reference == "canonical/territories/reference_year=2015/province.parquet"


def test_resolver_rejects_invalid_istat_2021_date_and_accepts_documented_date() -> None:
    with pytest.raises(ValueError, match="documented ISTAT date 2021-12-31"):
        resolve_bigbang_territory_policy(2021, "province", [_province_version(2021)])
    result = resolve_bigbang_territory_policy(2021, "province", [
        _province_version(2021, reference_date="2021-12-31"),
    ])
    assert result.support_status == "derived_supported"
    assert result.territory_reference_date == "2021-12-31"


def test_province_never_selects_nearest_or_current_geometry() -> None:
    versions = [_province_version(2015), _province_version(2025)]
    result = resolve_bigbang_territory_policy(2014, "province", versions)
    current_backfill = resolve_bigbang_territory_policy(1990, "province", [_province_version(2025)])
    assert result.support_status == "unsupported_missing_exact_geometry"
    assert result.territory_reference_date is None
    assert current_backfill.support_status == "unsupported_missing_exact_geometry"
    assert current_backfill.geometry_reference is None


def test_undocumented_crosswalk_interval_is_rejected() -> None:
    result = resolve_bigbang_territory_policy(1990, "province", [
        _province_version(1989, documented_valid_from=1990, documented_valid_to=1991),
    ])
    assert result.support_status == "unsupported_missing_exact_geometry"
    assert "without an official documented source" in result.reason


def test_documented_interval_is_explicitly_supported() -> None:
    result = resolve_bigbang_territory_policy(1990, "province", [
        _province_version(
            1989,
            documented_valid_from=1990,
            documented_valid_to=1991,
            documented_interval_source="ISTAT SITUAS official validity record",
        ),
    ])
    assert result.support_status == "derived_supported"
    assert result.territory_reference_date == "1989-01-01"
    assert "Documented official validity interval" in result.reason


def test_exact_geometry_and_documented_interval_are_ambiguous() -> None:
    with pytest.raises(ValueError, match="Ambiguous exact territory version and documented interval"):
        resolve_bigbang_territory_policy(2015, "province", [
            _province_version(2015),
            _province_version(
                2014,
                documented_valid_from=2014,
                documented_valid_to=2016,
                documented_interval_source="ISTAT SITUAS official validity record",
            ),
        ])


def test_municipality_is_methodologically_unsupported_and_country_region_are_official() -> None:
    municipality = resolve_bigbang_territory_policy(2025, "municipality", [_province_version(2025)])
    country = resolve_bigbang_territory_policy(1951, "country", [])
    region = resolve_bigbang_territory_policy(1951, "region", [])
    assert municipality.support_status == "unsupported_methodology"
    assert country.support_status == "official"
    assert region.support_status == "official"


def test_policy_is_deterministic_and_rejects_invalid_inputs() -> None:
    values = [_province_version(2025), _province_version(2015)]
    assert resolve_bigbang_territory_policy(2015, "province", values) == resolve_bigbang_territory_policy(2015, "province", values)
    with pytest.raises(ValueError, match="BIGBANG reference year"):
        resolve_bigbang_territory_policy(1950, "province", values)
    with pytest.raises(ValueError, match="Unsupported BIGBANG territory level"):
        resolve_bigbang_territory_policy(2025, "district", values)


def test_support_matrix_has_every_year_once_per_level_and_no_unreferenced_derived_rows() -> None:
    matrix = build_bigbang_historical_support_matrix([_province_version(year) for year in (2015, 2023, 2025)])
    assert len(matrix) == 75 * 4
    assert {(row["reference_year"], row["territory_level"]) for row in matrix} == {
        (year, level) for year in range(1951, 2026) for level in ("country", "region", "province", "municipality")
    }
    assert {row["support_status"] for row in matrix} <= {
        "official", "derived_supported", "unsupported_missing_exact_geometry", "unsupported_methodology",
    }
    assert all(row["territory_reference_date"] for row in matrix if row["support_status"] == "derived_supported")


def _write_territory_snapshot(root: Path, year: int, level: str, reference_date: str) -> None:
    path = root / "territories" / f"reference_year={year}" / f"{level}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{
        "territory_version_id": f"it:{level}:001@{reference_date}",
        "reference_date": reference_date,
    }]).to_parquet(path, index=False)


def test_canonical_inventory_uses_explicit_dates_and_report_is_local_matrix(tmp_path: Path) -> None:
    for level in ("region", "province", "municipality"):
        _write_territory_snapshot(tmp_path, 2015, level, "2015-01-01")
        _write_territory_snapshot(tmp_path, 2021, level, "2021-01-01")
    versions, inventory = inspect_canonical_territories(tmp_path)
    assert {(entry.reference_year, entry.territory_level) for entry in inventory} == {
        (year, level) for year in (2015, 2021) for level in ("region", "province", "municipality")
    }
    assert {(version.reference_year, version.territory_level) for version in versions} == {
        (2015, level) for level in ("region", "province", "municipality")
    }
    report_path = tmp_path / "artifacts/reports/bigbang-historical-territory-support.json"
    report = write_bigbang_historical_support_report(tmp_path, report_path)
    assert report_path.exists()
    assert json.loads(report_path.read_text()) == report
    supported_provinces = [row for row in report["supportMatrix"] if row["territory_level"] == "province" and row["support_status"] == "derived_supported"]
    assert [row["reference_year"] for row in supported_provinces] == [2015]
