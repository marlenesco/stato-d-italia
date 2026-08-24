from stato_italia.soil import EXPECTED_PERIODS, _validate_contract

import pandas as pd
import pytest


def test_expected_periods_cover_only_official_periods() -> None:
    assert (2006, 2012) in EXPECTED_PERIODS
    assert (2012, 2015) in EXPECTED_PERIODS
    assert (2023, 2024) in EXPECTED_PERIODS
    assert (2007, 2008) not in EXPECTED_PERIODS


def test_contract_rejects_missing_stock_column() -> None:
    columns = ["PRO_COM", "Nome_Comune", "Nome_Regione", "Nome_Provincia"]
    for start, end in EXPECTED_PERIODS:
        columns.extend([
            f"Incremento netto {start}-{end} [ettari]",
            f"Incremento lordo {start}-{end} [ettari]",
            f"Ripristino {start}-{end} [ettari]",
        ])
    columns.append("Suolo consumato 2024 [ettari]")
    with pytest.raises(ValueError, match="Unexpected ISPRA"):
        _validate_contract(pd.DataFrame(columns=columns), "municipality")
