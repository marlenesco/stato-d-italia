import json

import pandas as pd

from stato_italia.territory_delivery import generate_territory_delivery


def test_territory_identity_delivery_is_domain_independent_and_keeps_hierarchy(tmp_path) -> None:
    canonical = tmp_path / "canonical"
    rows = {
        "region": [{"territory_id": "it:region:12", "territory_version_id": "it:region:12@2025-01-01", "level": "region", "istat_code": "12", "name": "Lazio", "parent_istat_code": None, "reference_date": "2025-01-01"}],
        "province": [{"territory_id": "it:province:057", "territory_version_id": "it:province:057@2025-01-01", "level": "province", "istat_code": "057", "name": "Rieti", "parent_istat_code": "12", "reference_date": "2025-01-01"}],
        "municipality": [{"territory_id": "it:municipality:057001", "territory_version_id": "it:municipality:057001@2025-01-01", "level": "municipality", "istat_code": "057001", "name": "Rieti", "parent_istat_code": "057", "reference_date": "2025-01-01"}],
    }
    for level, values in rows.items():
        target = canonical / "territories/reference_year=2025" / f"{level}.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(values).to_parquet(target, index=False)

    result = generate_territory_delivery(canonical, tmp_path / "delivery", "release-test")
    assert result["territories"] == 4
    index = json.loads((tmp_path / "delivery/territories/index.json").read_text())
    assert index["algorithmVersion"] == "territory-identity-delivery-v2"
    assert index["currentIdentityIds"]["province"] == ["it:province:057"]
    assert all("soil" not in path for path in index["shards"])
    municipality = json.loads((tmp_path / "delivery/territories/municipality/057.json").read_text())["territories"][0]
    assert municipality["territoryId"] == "it:municipality:057001"
    assert [parent["territoryId"] for parent in municipality["parents"]] == ["it:province:057", "it:region:12"]
    assert json.loads((tmp_path / "delivery/territories/country/all.json").read_text())["territories"][0]["territoryId"] == "it:country:IT"
