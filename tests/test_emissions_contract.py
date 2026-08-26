from pathlib import Path

import pandas as pd
import pytest

from stato_italia import emissions
from stato_italia.emissions import _records, _validate_contract


def test_contract_rejects_missing_period_column() -> None:
    columns = [
        "COD_REGI", "NOM_REGI", "COD_PROV", "NOME_PROV", "G_EMEP", "SNAP",
        "Descrizione", "COD_POL", "NOMPOL", "UNI_mis", "2019",
    ]
    with pytest.raises(ValueError, match="Unexpected ISPRA emissions contract"):
        _validate_contract(pd.DataFrame(columns=columns))


def test_contract_accepts_required_columns() -> None:
    columns = [
        "COD_REGI", "NOM_REGI", "COD_PROV", "NOME_PROV", "G_EMEP", "SNAP",
        "Descrizione", "COD_POL", "NOMPOL", "UNI_mis", "2019", "2023",
    ]
    _validate_contract(pd.DataFrame([{column: "value" for column in columns}]))


def test_records_keep_snap_dimension_and_exclude_grid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(emissions, "PERIOD_REFERENCE_YEARS", {2023: 2023})
    monkeypatch.setattr(emissions, "_province_index", lambda _root, _year: {
        "001": {
            "territory_id": "it:province:001",
            "territory_version_id": "it:province:001@2023-01-01",
        },
        "002": {
            "territory_id": "it:province:002",
            "territory_version_id": "it:province:002@2023-01-01",
        },
    })
    frame = pd.DataFrame([
        {
            "G_EMEP": None, "COD_PROV": 1, "COD_POL": "006", "NOMPOL": "CO2",
            "SNAP": "070101", "Descrizione": "Trasporto", "UNI_mis": "Mg", "2023": 12.5,
        },
        {
            "G_EMEP": None, "COD_PROV": 2, "COD_POL": "006", "NOMPOL": "CO2",
            "SNAP": "070101", "Descrizione": "Trasporto", "UNI_mis": "Mg", "2023": 3.5,
        },
        {
            "G_EMEP": "42.1_10.2", "COD_PROV": 0, "COD_POL": "006", "NOMPOL": "CO2",
            "SNAP": "070101", "Descrizione": "Trasporto", "UNI_mis": "Mg", "2023": 999.0,
        },
    ])

    rows = _records(frame, Path("unused"), "a" * 64, "2026-08-25T12:00:00Z")

    assert len(rows) == 2
    assert {row["territory_id"] for row in rows} == {"it:province:001", "it:province:002"}
    assert all(row["metric_id"] == "emissions_pollutant_006" for row in rows)
    assert '"snap_code":"070101"' in rows[0]["source_dimensions_json"]
    assert rows[0]["quality_flags"] == ["official_top_down_disaggregation"]
    assert all(row["value_state"] == "observed" for row in rows)
