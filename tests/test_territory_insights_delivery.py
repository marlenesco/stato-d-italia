import json

import pandas as pd

from stato_italia.territory_insights_delivery import comparison_for_series, generate_territory_insights_delivery


def _table(rows: list[dict]) -> pd.DataFrame:
    columns = [
        "territory_id", "metric_id", "period_start", "period_end", "value_decimal", "unit_ucum", "value_state",
        "source_dimensions_json", "territory_version_id", "territory_level", "methodology_version", "algorithm_version",
        "territory_geometry_reference", "derived_metric_id", "reference_year", "source_dataset_version", "official_status",
    ]
    return pd.DataFrame(rows, columns=columns)


def _row(territory_id: str, metric: str, year: int, value: float, unit: str, *, level: str, method: str = "method-v1", geometry_year: int = 2025, **extra: object) -> dict:
    return {
        "territory_id": territory_id, "metric_id": metric, "period_start": f"{year}-01-01", "period_end": f"{year}-12-31",
        "value_decimal": value, "unit_ucum": unit, "value_state": "observed", "source_dimensions_json": "{}",
        "territory_version_id": f"{territory_id}@{geometry_year}-01-01", "territory_level": level,
        "methodology_version": method, "algorithm_version": None,
        "territory_geometry_reference": None, "derived_metric_id": None, "reference_year": year,
        "source_dataset_version": None, "official_status": "official",
    } | extra


def _write_territories(root, entries: tuple[tuple[str, str, str], ...]) -> None:
    for level, code, name in entries:
        path = root / "territories" / "reference_year=2025" / f"{level}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([{"territory_id": f"it:{level}:{code}", "name": name, "istat_code": code}]).to_parquet(path, index=False)


def test_delivery_aggregates_real_domain_availability_by_level(tmp_path) -> None:
    territory_root = tmp_path / "canonical"
    _write_territories(territory_root, (("municipality", "057001", "Rieti"), ("province", "057", "Rieti"), ("region", "12", "Lazio")))
    municipality, province, region = "it:municipality:057001", "it:province:057", "it:region:12"
    soil = _table([_row(territory, "soil_net_consumption_hectares", 2024, 9, "ha", level=level) for territory, level in ((municipality, "municipality"), (province, "province"), (region, "region"))])
    forests = _table([_row(territory, "tree_cover_mean", year, value, "%", level=level, method="hrl_tree_cover_density_100m", geometry_year=2023) for territory, level, value in ((municipality, "municipality", 51), (province, "province", 52), (region, "region", 53)) for year in (2018, 2023)])
    risk = _table([_row(territory, metric, year, value, unit, level=level, method="idrogeo-risk-2024", geometry_year=2024) for territory, level in ((municipality, "municipality"), (province, "province"), (region, "region")) for _, metric, _, year, value, unit in (("Alluvioni", "hydrogeological_flood_high_hazard_area_km2", "area", 2020, 4, "km2"), ("Alluvioni", "hydrogeological_flood_high_hazard_population", "people", 2020, 40, "{persons}"), ("Frane", "hydrogeological_landslide_very_high_hazard_area_km2", "area", 2024, 5, "km2"), ("Frane", "hydrogeological_landslide_very_high_hazard_population", "people", 2024, 50, "{persons}"))])
    emissions = _table([_row(province, "emissions_pollutant_002", year, value, "Mg", level="province", method="ispra-emissions-2026", source_dimensions_json=json.dumps({"snap_code": "07010302"})) for year, value in ((2019, 100), (2023, 80))])
    water = _table([_row(region, "water_total_precipitation_mm", year, value, "mm", level="region", method="bigbang-10.0") for year, value in ((2024, 700), (2025, 710))])
    derived_water = _table([_row(province, "unused", year, value, "mm", level="province", method="", geometry_year=geometry_year, derived_metric_id="water_total_precipitation_mm_zonal_mean", reference_year=year, source_dataset_version="bigbang-10.0", algorithm_version="bigbang-tp-zonal-area-weighted-v1", territory_geometry_reference=f"canonical/territories/reference_year={geometry_year}/province.parquet#{province}@{geometry_year}-01-01", official_status="derived_by_stato_italia") for year, value, geometry_year in ((2020, 600, 2020), (2022, 620, 2022), (2025, 630, 2025))])
    infc = _table([_row(region, "forest_volume_infc", 2015, 12, "m3", level="region", method="infc2015", geometry_year=2015)])
    paths = {}
    for name, table in {"soil": soil, "forest": forests, "water": water, "risk": risk, "emissions": emissions, "derived": derived_water, "infc": infc}.items():
        path = tmp_path / f"{name}.parquet"; table.to_parquet(path, index=False); paths[name] = path

    result = generate_territory_insights_delivery(paths["soil"], paths["forest"], paths["water"], paths["risk"], paths["emissions"], territory_root, tmp_path / "delivery", "release-test", derived_water_path=paths["derived"], infc_path=paths["infc"])
    assert result["profiles"] == 3
    municipal = {item["id"]: item for item in json.loads((tmp_path / "delivery/territory-insights/municipality/057.json").read_text())["profiles"][0]["domains"]}
    provincial = {item["id"]: item for item in json.loads((tmp_path / "delivery/territory-insights/province/all.json").read_text())["profiles"][0]["domains"]}
    regional = {item["id"]: item for item in json.loads((tmp_path / "delivery/territory-insights/region/all.json").read_text())["profiles"][0]["domains"]}

    assert municipal["soil"]["availability"] == municipal["forests"]["availability"] == municipal["risk"]["availability"] == "available"
    assert municipal["water"]["reason"] == municipal["emissions"]["reason"] == "source_not_published_at_this_level"
    assert provincial["water"]["kind"] == "derived_metric"
    assert [point["periodEnd"][:4] for point in provincial["water"]["series"]] == ["2020", "2022", "2025"]
    assert provincial["water"]["comparison"]["reason"] == "geometry_changed"
    assert provincial["risk"]["snapshots"][0]["family"] == "Alluvioni"
    assert provincial["risk"]["snapshots"][-1]["family"] == "Frane"
    assert provincial["emissions"]["comparison"]["reason"] == "comparison_not_supported"
    assert regional["water"]["kind"] == "official_model"
    assert regional["water"]["comparison"]["status"] == "available"
    assert regional["water"]["comparison"].get("reason") is None
    assert regional["forests"]["groups"][-1]["id"] == "infc"


def test_comparison_policy_requires_the_declared_evidence() -> None:
    base = {"metricId": "metric", "unit": "mm", "geometryReference": "geometry-a", "methodologyReference": "method-a"}
    def point(year: int, value: float, **extra: str) -> dict:
        return base | {"periodStart": f"{year}-01-01", "periodEnd": f"{year}-12-31", "value": value} | extra
    policy = "same_metric_unit_method_geometry"
    assert comparison_for_series([point(2024, 10), point(2025, 12)], "context_only", policy)["status"] == "available"
    assert comparison_for_series([point(2024, 10), point(2025, 12, geometryReference="geometry-b")], "context_only", policy)["reason"] == "geometry_changed"
    assert comparison_for_series([point(2024, 10), point(2025, 12, methodologyReference="method-b")], "context_only", policy)["reason"] == "methodology_changed"
    assert comparison_for_series([point(2025, 12)], "context_only", policy)["reason"] == "single_snapshot"
    assert comparison_for_series([point(2024, 10), point(2025, 12)], "context_only", "not_supported")["reason"] == "comparison_not_supported"
