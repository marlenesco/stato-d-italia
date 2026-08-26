import json
from pathlib import Path

import pandas as pd

from stato_italia.emissions_delivery import generate_emissions_delivery


def test_delivery_keeps_one_declared_snap_observation_per_province_and_period(tmp_path: Path) -> None:
    ghg_path = tmp_path / "ghg.parquet"
    nfr_path = tmp_path / "nfr.parquet"
    provincial_path = tmp_path / "provincial.parquet"
    geometry_paths = {year: tmp_path / f"istat-province-{year}.pmtiles" for year in (2019, 2023)}
    for path in geometry_paths.values():
        path.write_bytes(b"pmtiles")

    pd.DataFrame([
        {
            "metric_id": "emissions_ghg_co2e", "reference_year": year,
            "source_dimensions_json": '{"inventory_category":"Total (net emissions) (4)"}',
            "value_decimal": float(year), "value_state": "observed", "unit_ucum": "kt CO2 equivalent",
        }
        for year in range(1990, 2025)
    ]).to_parquet(ghg_path, index=False)
    pd.DataFrame([{
        "metric_id": "emissions_pollutant_002", "reference_year": 2024,
        "source_dimensions_json": "{}", "value_decimal": 1.0, "value_state": "observed", "unit_ucum": "Mg",
    }]).to_parquet(nfr_path, index=False)
    pd.DataFrame([
        {
            "metric_id": "emissions_pollutant_002", "reference_year": year,
            "source_dimensions_json": '{"snap_code":"07010302"}', "value_decimal": float(code),
            "value_state": "observed", "unit_ucum": "Mg", "territory_id": f"it:province:{code:03d}",
            "territory_version_id": f"it:province:{code:03d}@{year}-01-01",
        }
        for year in (2019, 2023) for code in range(1, 108)
    ]).to_parquet(provincial_path, index=False)

    result = generate_emissions_delivery(
        ghg_path, nfr_path, provincial_path, geometry_paths, tmp_path / "delivery", "release-test",
    )

    assert result["changed"] is True
    index = json.loads((tmp_path / "delivery" / "emissions" / "index.json").read_text())
    assert index["maps"] == ["delivery/emissions/maps/emissions_pollutant_002/2019/province.json", "delivery/emissions/maps/emissions_pollutant_002/2023/province.json"]
    assert index["geometry"] == ["delivery/emissions/geometry/istat-province-2019.pmtiles", "delivery/emissions/geometry/istat-province-2023.pmtiles"]
    values = json.loads((tmp_path / "delivery" / "emissions" / "maps" / "emissions_pollutant_002" / "2023" / "province.json").read_text())
    assert values["sourceDimensions"] == {"pollutant_code": "002", "snap_code": "07010302"}
    assert len(values["values"]) == 107
