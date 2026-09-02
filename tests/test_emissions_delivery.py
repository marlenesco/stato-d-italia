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
            "source_dimensions_json": '{"inventory_category":"Total (net emissions) (4)","source_unit":"kt CO2 equivalenti (kt)"}',
            "value_decimal": float(year), "value_state": "observed", "unit_ucum": "kt CO2 equivalent",
        }
        for year in range(1990, 2025)
    ]).to_parquet(ghg_path, index=False)
    pd.DataFrame([{
        "metric_id": "emissions_pollutant_002", "reference_year": 2024,
        "source_dimensions_json": '{"nfr_code":"1A1a","nfr_group":"A_PublicPower","nfr_label":"Public electricity and heat production","pollutant_label":"NOx (as NO2)","source_unit":"kt"}', "value_decimal": 1.0, "value_state": "observed", "unit_ucum": "Mg",
    }]).to_parquet(nfr_path, index=False)
    pd.DataFrame([
        {
            "metric_id": "emissions_pollutant_002", "reference_year": year,
            "source_dimensions_json": '{"pollutant_code":"002","pollutant_label":"Ossidi di azoto","snap_code":"07010302","snap_label":"Automobili diesel su strade urbane"}', "value_decimal": float(code),
            "value_state": "observed", "unit_ucum": "Mg", "territory_id": f"it:province:{code:03d}",
            "territory_version_id": f"it:province:{code:03d}@{year}-01-01",
        }
        for year in (2019, 2023) for code in range(1, 108)
    ]).to_parquet(provincial_path, index=False)

    stale = tmp_path / "delivery" / "emissions" / "obsolete.json"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("{}")
    result = generate_emissions_delivery(
        ghg_path, nfr_path, provincial_path, geometry_paths, tmp_path / "delivery", "release-test",
    )

    assert result["changed"] is True
    assert not stale.exists()
    assert stale not in result["files"]
    index = json.loads((tmp_path / "delivery" / "emissions" / "index.json").read_text())
    assert index["national"] == {
        "greenhouseGases": "delivery/emissions/national/greenhouse-gases.json",
        "airPollutantsNfr": "delivery/emissions/national/air-pollutants-nfr.json",
    }
    assert index["provincialCatalog"] == "delivery/emissions/provincial/catalog.json"
    assert index["maps"] == [
        "delivery/emissions/maps/emissions_pollutant_002/2019/province.json",
        "delivery/emissions/maps/emissions_pollutant_002/2023/province.json",
    ]
    assert index["geometry"] == ["delivery/emissions/geometry/istat-province-2019.pmtiles", "delivery/emissions/geometry/istat-province-2023.pmtiles"]
    overview = json.loads((tmp_path / "delivery" / "emissions" / "overview.json").read_text())
    assert overview["map"]["metricId"] == "emissions_pollutant_002"
    assert overview["map"]["snapCode"] == "07010302"
    catalog = json.loads((tmp_path / "delivery" / "emissions" / "provincial" / "catalog.json").read_text())
    assert catalog["combinations"][0]["mapPaths"] == {"2019": "delivery/emissions/maps/emissions_pollutant_002/2019/province.json", "2023": "delivery/emissions/maps/emissions_pollutant_002/2023/province.json"}
    values = json.loads((tmp_path / "delivery" / "emissions" / "maps" / "emissions_pollutant_002" / "2023" / "province.json").read_text())
    snapshot = values["snapshots"][0]
    assert snapshot["sourceDimensions"]["snap_code"] == "07010302"
    assert len(snapshot["values"]) == 107
