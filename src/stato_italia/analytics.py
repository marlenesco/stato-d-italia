from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .common import stable_id

SOIL_ANALYTICS_VERSION = "soil-analytics-v1"
MIN_PERCENTILE_POPULATION = 10
MIN_TREND_OBSERVATIONS = 7
MIN_TREND_COVERAGE = 0.8
COMPARISON_ALLOWED_METRICS = {
    "soil_net_consumption_hectares",
    "soil_gross_consumption_hectares",
    "soil_consumed_hectares",
    "soil_consumed_share",
}


def load_territory_context(canonical_root: Path, year: int = 2025) -> dict[str, dict]:
    """Current source hierarchy only; historical crosswalks stay forbidden."""
    root = canonical_root / "territories" / f"reference_year={year}"
    context: dict[str, dict] = {}
    by_level_code: dict[tuple[str, str], str] = {}
    for level in ("municipality", "province", "region"):
        for row in pd.read_parquet(root / f"{level}.parquet").drop(columns=["geometry_wkb"]).to_dict("records"):
            context[row["territory_id"]] = row | {"parent_territory_id": None, "region_territory_id": None, "province_territory_id": None}
            by_level_code[(level, row["istat_code"])] = row["territory_id"]
    country_id = "it:country:IT"
    context[country_id] = {
        "territory_id": country_id, "territory_version_id": f"{country_id}@{year}-01-01", "level": "country",
        "istat_code": "IT", "name": "Italia", "parent_istat_code": None, "reference_date": f"{year}-01-01",
        "parent_territory_id": None, "region_territory_id": None, "province_territory_id": None,
    }
    for territory in context.values():
        if territory["level"] == "municipality":
            province_id = by_level_code[("province", territory["parent_istat_code"])]
            territory["parent_territory_id"] = province_id
            territory["province_territory_id"] = province_id
            territory["region_territory_id"] = context[province_id]["parent_territory_id"]
        elif territory["level"] == "province":
            region_id = by_level_code[("region", territory["parent_istat_code"])]
            territory["parent_territory_id"] = region_id
            territory["region_territory_id"] = region_id
        elif territory["level"] == "region":
            territory["parent_territory_id"] = country_id
            territory["region_territory_id"] = territory["territory_id"]
    return context


def latest_observations(observations: pd.DataFrame) -> pd.DataFrame:
    keys = ["territory_id", "metric_id", "period_start", "period_end"]
    if observations.duplicated(keys).any():
        raise ValueError("Canonical observations duplicate territory/metric/period")
    return (
        observations.sort_values(["territory_id", "metric_id", "period_end", "period_start"])
        .groupby(["territory_id", "metric_id"], as_index=False, group_keys=False).tail(1).copy()
    )


def _annual(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    output["start_year"] = output["period_start"].str[:4].astype(int)
    output["end_year"] = output["period_end"].str[:4].astype(int)
    return output[output["end_year"] - output["start_year"] == 1].copy()


def _peer_group_id(territory: dict, mode: str) -> str | None:
    if mode == "national":
        return territory["level"]
    if mode == "regional" and territory.get("region_territory_id"):
        return f"{territory['level']}:{territory['region_territory_id']}"
    if mode == "provincial" and territory["level"] == "municipality" and territory.get("province_territory_id"):
        return f"municipality:{territory['province_territory_id']}"
    return None


def _unavailable(summary: dict, prefix: str, reason: str) -> None:
    summary[f"{prefix}_status"] = "unavailable"
    summary[f"{prefix}_reason"] = reason


def _flow(summary: dict, latest: pd.Series, series: pd.DataFrame) -> None:
    if series.empty:
        return
    end_year = int(latest["period_end"][:4])
    latest_annual = series[series["end_year"] == end_year]
    if len(latest_annual) != 1:
        return
    latest_annual = latest_annual.iloc[0]
    versions = set(series["territory_version_id"])

    def change(prefix: str, years_back: int) -> None:
        wanted = series[series["end_year"] == end_year - years_back]
        if len(versions) != 1:
            _unavailable(summary, prefix, "series_break")
        elif len(wanted) != 1:
            _unavailable(summary, prefix, "missing_required_period")
        else:
            prior = wanted.iloc[0]
            summary[f"{prefix}_status"] = "available"
            summary[f"{prefix}_value"] = float(latest_annual["value_decimal"] - prior["value_decimal"])
            summary[f"{prefix}_unit"] = latest_annual["unit_ucum"]
            summary[f"{prefix}_input_observation_ids"] = [latest_annual["observation_id"], prior["observation_id"]]

    change("change_previous", 1)
    change("change_5y", 5)
    change("change_10y", 10)
    window = series[(series["end_year"] >= end_year - 9) & (series["end_year"] <= end_year)]
    years = window["end_year"].tolist()
    span = max(years) - min(years) + 1 if years else 0
    coverage = len(window) / span if span else 0.0
    has_gap = any(right - left > 1 for left, right in zip(years, years[1:], strict=False))
    summary["trend_coverage_observations"] = len(window)
    summary["trend_coverage_expected"] = span
    summary["trend_input_observation_ids"] = window["observation_id"].tolist()
    if len(versions) != 1:
        _unavailable(summary, "trend", "series_break")
    elif len(window) < MIN_TREND_OBSERVATIONS or coverage < MIN_TREND_COVERAGE or has_gap:
        _unavailable(summary, "trend", "insufficient_coverage")
    else:
        x = window["end_year"].to_numpy(dtype=float)
        y = window["value_decimal"].to_numpy(dtype=float)
        slope, intercept = np.polyfit(x, y, 1)
        residual = float(np.sum((y - (slope * x + intercept)) ** 2))
        total = float(np.sum((y - y.mean()) ** 2))
        r_squared = 1.0 if total == 0 else max(0.0, 1.0 - residual / total)
        threshold = float(np.median(np.abs(y))) * 0.01
        summary["trend_status"] = "available"
        summary["trend_slope_per_year"] = float(slope)
        summary["trend_intercept"] = float(intercept)
        summary["trend_r_squared"] = r_squared
        summary["trend_direction"] = "flat" if abs(slope) <= threshold else ("increasing" if slope > 0 else "decreasing")
        summary["trend_unit"] = f"{latest_annual['unit_ucum']}/year"


def _comparisons(summaries: dict[tuple[str, str], dict], latest: pd.DataFrame, context: dict[str, dict]) -> None:
    for mode in ("national", "regional", "provincial"):
        material = latest.copy()
        material["peer_group_id"] = material["territory_id"].map(lambda territory_id: _peer_group_id(context[territory_id], mode))
        material = material.dropna(subset=["peer_group_id"])
        for (metric_id, level, start, end, group_id), group in material.groupby(["metric_id", "territory_level", "period_start", "period_end", "peer_group_id"]):
            population = len(group)
            ranks = group["value_decimal"].astype(float).rank(method="min", ascending=False)
            percentiles = group["value_decimal"].astype(float).rank(method="max", ascending=True) * 100.0 / population
            selector = f"metric={metric_id};level={level};period={start}/{end};peer_group={mode};group_id={group_id}"
            for index, row in group.iterrows():
                summary = summaries[(row["territory_id"], metric_id)]
                summary[f"{mode}_input_selector"] = selector
                summary[f"{mode}_peer_count"] = population
                if metric_id not in COMPARISON_ALLOWED_METRICS:
                    _unavailable(summary, f"{mode}_percentile", "metric_not_comparable")
                    _unavailable(summary, f"{mode}_ranking", "metric_not_comparable")
                else:
                    summary[f"{mode}_ranking_status"] = "available" if population >= 2 else "unavailable"
                    summary[f"{mode}_ranking_reason"] = None if population >= 2 else "peer_group_too_small"
                    summary[f"{mode}_ranking"] = float(ranks.loc[index]) if population >= 2 else None
                    summary[f"{mode}_percentile_status"] = "available" if population >= MIN_PERCENTILE_POPULATION else "unavailable"
                    summary[f"{mode}_percentile_reason"] = None if population >= MIN_PERCENTILE_POPULATION else "peer_group_too_small"
                    summary[f"{mode}_percentile"] = float(percentiles.loc[index]) if population >= MIN_PERCENTILE_POPULATION else None


def calculate_soil_analytics(observations: pd.DataFrame, context: dict[str, dict]) -> pd.DataFrame:
    required = {"observation_id", "metric_id", "territory_id", "territory_version_id", "territory_level", "period_start", "period_end", "value_decimal", "unit_ucum"}
    missing = required - set(observations.columns)
    if missing:
        raise ValueError(f"Canonical data lacks analytics fields: {sorted(missing)}")
    if not observations["territory_id"].isin(context).all():
        raise ValueError("Canonical data has territory outside selected territory context")
    if not np.isfinite(observations["value_decimal"].astype(float)).all():
        raise ValueError("Canonical data has non-finite values")
    latest = latest_observations(observations)
    annual_series = {
        key: group.sort_values("end_year")
        for key, group in _annual(observations).groupby(["territory_id", "metric_id"])
    }
    summaries: dict[tuple[str, str], dict] = {}
    for _, row in latest.iterrows():
        summary = {
            "analytics_id": stable_id(SOIL_ANALYTICS_VERSION, row["territory_id"], row["metric_id"], row["period_start"], row["period_end"]),
            "algorithm_version": SOIL_ANALYTICS_VERSION,
            "metric_id": row["metric_id"], "territory_id": row["territory_id"], "territory_version_id": row["territory_version_id"],
            "territory_level": row["territory_level"], "latest_observation_id": row["observation_id"],
            "reference_period_start": row["period_start"], "reference_period_end": row["period_end"],
        }
        _flow(summary, row, annual_series.get((row["territory_id"], row["metric_id"]), pd.DataFrame()))
        summaries[(row["territory_id"], row["metric_id"])] = summary
    _comparisons(summaries, latest, context)
    result = pd.DataFrame(summaries.values())
    if result.duplicated(["analytics_id"]).any():
        raise ValueError("Derived analytics duplicate IDs")
    return result


def build_soil_analytics(canonical_path: Path, canonical_root: Path, destination: Path, force: bool = False) -> dict:
    if destination.exists() and not force:
        current = pd.read_parquet(destination, columns=["algorithm_version"])
        if set(current["algorithm_version"].dropna()) == {SOIL_ANALYTICS_VERSION}:
            return {"path": str(destination), "bytes": destination.stat().st_size, "records": len(current), "changed": False, "skipped": True}
    result = calculate_soil_analytics(pd.read_parquet(canonical_path), load_territory_context(canonical_root))
    destination.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(destination, index=False, compression="zstd")
    return {"path": str(destination), "bytes": destination.stat().st_size, "records": len(result), "changed": True, "algorithm_version": SOIL_ANALYTICS_VERSION}
