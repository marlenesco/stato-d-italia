import pytest

from stato_italia.emissions_national import _ghg_metric, _source_value


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, (0.0, "observed", None)),
        ("NA,NO", (None, "not_applicable", "NA,NO")),
        ("NE,NO", (None, "unavailable", "NE,NO")),
        ("C", (None, "suppressed", "C")),
    ],
)
def test_source_value_preserves_official_state(raw: object, expected: tuple[float | None, str, str | None]) -> None:
    assert _source_value(raw) == expected


def test_source_value_rejects_unknown_notation() -> None:
    with pytest.raises(ValueError, match="Unknown ISPRA emissions value notation"):
        _source_value("confidential?")


def test_f_gas_co2_equivalent_is_not_mixed_with_mass() -> None:
    assert _ghg_metric("f_gases", "Emissions of HFCs - CO2 equivalents (kt)") == "emissions_ghg_f_gases_co2e"
    assert _ghg_metric("f_gases", "HFC-23") == "emissions_ghg_f_gases"
