from __future__ import annotations

import pandas as pd
import pytest

from stato_italia.analytics import SOIL_ANALYTICS_VERSION, calculate_soil_analytics


def _context(count: int = 10) -> dict[str, dict]:
    context = {
        "it:country:IT": {"territory_id": "it:country:IT", "level": "country", "region_territory_id": None, "province_territory_id": None},
        "it:region:01": {"territory_id": "it:region:01", "level": "region", "region_territory_id": "it:region:01", "province_territory_id": None},
        "it:province:001": {"territory_id": "it:province:001", "level": "province", "region_territory_id": "it:region:01", "province_territory_id": None},
    }
    for index in range(count):
        territory_id = f"it:municipality:{index:06d}"
        context[territory_id] = {
            "territory_id": territory_id,
            "level": "municipality",
            "region_territory_id": "it:region:01",
            "province_territory_id": "it:province:001",
        }
    return context


def _row(territory_id: str, end_year: int, value: float, version: str | None = None) -> dict:
    return {
        "observation_id": f"{territory_id}:{end_year}:{version or 'v1'}",
        "metric_id": "soil_net_consumption_hectares",
        "territory_id": territory_id,
        "territory_version_id": version or f"{territory_id}@2025-01-01",
        "territory_level": "municipality",
        "period_start": f"{end_year - 1}-01-01",
        "period_end": f"{end_year}-12-31",
        "value_decimal": value,
        "unit_ucum": "ha",
    }


def _analytics(rows: list[dict]) -> pd.DataFrame:
    result = calculate_soil_analytics(pd.DataFrame(rows), _context())
    assert set(result["algorithm_version"]) == {SOIL_ANALYTICS_VERSION}
    return result


def _one(result: pd.DataFrame, territory_id: str) -> pd.Series:
    selected = result[(result["territory_id"] == territory_id) & (result["metric_id"] == "soil_net_consumption_hectares")]
    assert len(selected) == 1
    return selected.iloc[0]


def test_changes_percentile_and_tie_ranking_are_deterministic() -> None:
    rows: list[dict] = []
    for index in range(10):
        territory_id = f"it:municipality:{index:06d}"
        for end_year in range(2018, 2025):
            # Two tied latest values; includes zero series baseline for municipality 0.
            latest = 1.0 if index < 2 else float(index + 1)
            rows.append(_row(territory_id, end_year, latest if end_year == 2024 else float(index)))
    result = _analytics(rows)
    territory_id = "it:municipality:000000"
    summary = _one(result, territory_id)
    assert summary["change_previous_value"] == 1.0
    assert summary["change_5y_value"] == 1.0
    assert summary["change_10y_status"] == "unavailable"
    assert summary["change_10y_reason"] == "missing_required_period"
    assert summary["national_percentile"] == 20.0
    assert summary["national_ranking"] == 9.0


def test_gap_and_missing_required_period_are_not_interpolated() -> None:
    rows = [_row("it:municipality:000000", year, 1.0) for year in (2018, 2020, 2021, 2022, 2023, 2024)]
    result = _analytics(rows)
    summary = _one(result, "it:municipality:000000")
    assert summary["change_5y_status"] == "unavailable"
    assert summary["change_5y_reason"] == "missing_required_period"
    assert summary["trend_status"] == "unavailable"
    assert summary["trend_reason"] == "insufficient_coverage"


def test_series_break_blocks_analytics() -> None:
    rows = [_row("it:municipality:000000", year, float(year)) for year in range(2018, 2025)]
    rows[0]["territory_version_id"] = "it:municipality:000000@2018-01-01"
    result = _analytics(rows)
    summary = _one(result, "it:municipality:000000")
    assert summary["change_5y_reason"] == "series_break"
    assert summary["trend_reason"] == "series_break"


def test_zero_series_has_flat_trend_without_division_by_zero() -> None:
    rows = [_row("it:municipality:000000", year, 0.0) for year in range(2018, 2025)]
    result = _analytics(rows)
    trend = _one(result, "it:municipality:000000")
    assert trend["trend_status"] == "available"
    assert trend["trend_slope_per_year"] == 0.0
    assert trend["trend_r_squared"] == 1.0
    assert trend["trend_direction"] == "flat"


def test_null_observation_value_fails_loudly() -> None:
    row = _row("it:municipality:000000", 2024, 1.0)
    row["value_decimal"] = None
    with pytest.raises(ValueError, match="non-finite"):
        _analytics([row])
