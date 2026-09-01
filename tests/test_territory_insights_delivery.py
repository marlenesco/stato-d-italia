import json

import pandas as pd

from stato_italia.territory_insights_delivery import generate_territory_insights_delivery


def _table(rows: list[dict]) -> pd.DataFrame:
    columns = ["territory_id", "metric_id", "period_start", "period_end", "value_decimal", "unit_ucum", "value_state", "source_dimensions_json"]
    return pd.DataFrame(rows, columns=columns)


def test_delivery_keeps_domain_series_and_declares_snapshot(tmp_path) -> None:
    territory_root = tmp_path / "canonical"
    for level, code, name in (("municipality", "057001", "Rieti"), ("province", "057", "Rieti"), ("region", "12", "Lazio")):
        path = territory_root / "territories" / "reference_year=2025" / f"{level}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([{"territory_id": f"it:{level}:{code}", "name": name, "istat_code": code}]).to_parquet(path, index=False)
    soil = _table([
        {"territory_id": "it:province:057", "metric_id": "soil_net_consumption_hectares", "period_start": "2022-01-01", "period_end": "2023-12-31", "value_decimal": 12, "unit_ucum": "ha", "value_state": "observed"},
        {"territory_id": "it:province:057", "metric_id": "soil_net_consumption_hectares", "period_start": "2023-01-01", "period_end": "2024-12-31", "value_decimal": 9, "unit_ucum": "ha", "value_state": "observed"},
    ])
    forest = _table([
        {"territory_id": "it:province:057", "metric_id": "tree_cover_mean", "period_start": "2021-01-01", "period_end": "2021-12-31", "value_decimal": 51, "unit_ucum": "%", "value_state": "observed"},
        {"territory_id": "it:province:057", "metric_id": "tree_cover_mean", "period_start": "2023-01-01", "period_end": "2023-12-31", "value_decimal": 52, "unit_ucum": "%", "value_state": "observed"},
    ])
    risk = _table([{"territory_id": "it:province:057", "metric_id": "hydrogeological_landslide_very_high_hazard_area_km2", "period_start": "2024-01-01", "period_end": "2024-12-31", "value_decimal": 11, "unit_ucum": "km2", "value_state": "observed"}])
    emissions = _table([
        {"territory_id": "it:province:057", "metric_id": "emissions_pollutant_002", "period_start": "2019-01-01", "period_end": "2019-12-31", "value_decimal": 100, "unit_ucum": "Mg", "value_state": "observed", "source_dimensions_json": json.dumps({"snap_code": "07010302"})},
        {"territory_id": "it:province:057", "metric_id": "emissions_pollutant_002", "period_start": "2023-01-01", "period_end": "2023-12-31", "value_decimal": 80, "unit_ucum": "Mg", "value_state": "observed", "source_dimensions_json": json.dumps({"snap_code": "07010302"})},
    ])
    paths = {}
    for name, table in {"soil": soil, "forest": forest, "water": _table([]), "risk": risk, "emissions": emissions}.items():
        path = tmp_path / f"{name}.parquet"; table.to_parquet(path, index=False); paths[name] = path
    result = generate_territory_insights_delivery(paths["soil"], paths["forest"], paths["water"], paths["risk"], paths["emissions"], territory_root, tmp_path / "delivery", "release-test")
    assert result["profiles"] == 3
    profile = json.loads((tmp_path / "delivery" / "territory-insights" / "province" / "all.json").read_text())["profiles"][0]
    domains = {item["id"]: item for item in profile["domains"]}
    assert domains["soil"]["comparison"]["direction"] == "improving"
    assert domains["forests"]["comparison"]["direction"] == "changed"
    assert domains["risk"]["comparison"]["reason"] == "single_snapshot"
    assert domains["emissions"]["comparison"]["percent"] == -20

    for path in paths.values():
        path.touch()
    reused = generate_territory_insights_delivery(
        paths["soil"], paths["forest"], paths["water"], paths["risk"], paths["emissions"],
        territory_root, tmp_path / "delivery", "release-other",
    )
    assert reused["changed"] is False
