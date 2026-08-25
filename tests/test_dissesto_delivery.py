from pathlib import Path

import json
import pandas as pd

from stato_italia.dissesto_delivery import generate_dissesto_delivery


def test_delivery_keeps_only_observed_values_and_declares_2024_geometry(tmp_path: Path) -> None:
    canonical = tmp_path / "observations.parquet"
    pd.DataFrame([
        {
            "metric_id": "hydrogeological_landslide_very_high_hazard_area_km2",
            "territory_id": "it:region:12", "territory_level": "region",
            "period_start": "2024-01-01", "period_end": "2024-12-31",
            "value_decimal": 12.5, "value_state": "observed", "unit_ucum": "km2",
            "territory_version_id": "it:region:12@2024-01-01",
        },
        {
            "metric_id": "hydrogeological_landslide_very_high_hazard_area_km2",
            "territory_id": "it:region:13", "territory_level": "region",
            "period_start": "2024-01-01", "period_end": "2024-12-31",
            "value_decimal": None, "value_state": "unavailable", "unit_ucum": "km2",
            "territory_version_id": "it:region:13@2024-01-01",
        },
    ]).to_parquet(canonical, index=False)
    geometry = {}
    for level in ("municipality", "province", "region"):
        path = tmp_path / f"istat-{level}-2024.pmtiles"
        path.write_bytes(b"pmtiles")
        geometry[level] = path

    result = generate_dissesto_delivery(canonical, tmp_path / "delivery", "release-test", geometry)

    assert result["maps"] == 1
    index = json.loads((tmp_path / "delivery" / "dissesto" / "index.json").read_text())
    assert index["rankings"] == []
    assert index["geometry"][-1] == "delivery/dissesto/geometry/istat-region-2024.pmtiles"
    values = json.loads((tmp_path / "delivery" / "dissesto" / "maps" / "hydrogeological_landslide_very_high_hazard_area_km2" / "2024-2024" / "region.json").read_text())
    assert values["values"] == [["it:region:12", 12.5]]
