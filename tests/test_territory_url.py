import zipfile
from pathlib import Path

import pandas as pd
import pytest
from shapely.geometry import Point

from stato_italia import territories
from stato_italia.territories import (
    boundary_url,
    load_territory_index,
    normalize_boundary_features,
    territory_reference_date,
    validate_territory_hierarchy,
)


def _source_feature(
    level: str, *, source_identity: str | tuple[str, ...], code: str | None,
    name: str, source_codes: dict[str, str | None] | None = None, region_code: str = "01",
) -> dict:
    administrative_codes = {"cod_uts": None, "cod_prov": None, "cod_cm": None, "cod_pcm": None}
    administrative_codes.update(source_codes or {})
    return {
        "level": level, "source_identity": source_identity, "istat_code": code,
        "name": name, "name_normalized": name.lower(), "source_codes": administrative_codes,
        "region_code": region_code, "geometry": Point(12, 42).__geo_interface__,
    }


def _valid_source_features() -> dict[str, list[dict]]:
    return {
        "region": [_source_feature("region", source_identity="01", code="01", name="Piemonte")],
        "province": [_source_feature("province", source_identity=("cod_prov=001",), code=None, name="Torino", source_codes={"cod_prov": "001", "cod_uts": "001"})],
        "municipality": [_source_feature("municipality", source_identity="001001", code="001001", name="Comune", source_codes={"cod_prov": "001", "cod_uts": "001"})],
    }


def test_istat_url_eras_are_explicit() -> None:
    assert boundary_url(2006).endswith("generalizzati/Limiti01012006_g.zip")
    assert boundary_url(2021).endswith("generalizzati/Limiti2021_g.zip")
    assert boundary_url(2024).endswith("generalizzati/2024/Limiti01012024_g.zip")
    assert boundary_url(2025).endswith("generalizzati/2025/Limiti01012025_g.zip")


def test_istat_reference_date_has_the_documented_2021_exception() -> None:
    assert territory_reference_date(2018) == "2018-01-01"
    assert territory_reference_date(2021) == "2021-12-31"
    assert territory_reference_date(2023) == "2023-01-01"


def test_2021_normalization_uses_field_semantic_uts_for_metro_municipality_parents() -> None:
    source = {
        "region": [
            _source_feature("region", source_identity="03", code="03", name="Lombardia", region_code="03"),
            _source_feature("region", source_identity="12", code="12", name="Lazio", region_code="12"),
            _source_feature("region", source_identity="15", code="15", name="Campania", region_code="15"),
        ],
        "province": [
            _source_feature("province", source_identity=("milano",), code=None, name="Milano", source_codes={"cod_prov": "015", "cod_cm": "215", "cod_uts": "215"}, region_code="03"),
            _source_feature("province", source_identity=("roma",), code=None, name="Roma", source_codes={"cod_prov": "058", "cod_cm": "258", "cod_uts": "258"}, region_code="12"),
            _source_feature("province", source_identity=("napoli",), code=None, name="Napoli", source_codes={"cod_prov": "063", "cod_cm": "263", "cod_uts": "263"}, region_code="15"),
        ],
        "municipality": [
            _source_feature("municipality", source_identity="015146", code="015146", name="Milano", source_codes={"cod_prov": "015", "cod_cm": "215", "cod_uts": "215"}, region_code="03"),
            _source_feature("municipality", source_identity="058091", code="058091", name="Roma", source_codes={"cod_prov": "058", "cod_cm": "258", "cod_uts": "258"}, region_code="12"),
            _source_feature("municipality", source_identity="063049", code="063049", name="Napoli", source_codes={"cod_prov": "063", "cod_cm": "263", "cod_uts": "263"}, region_code="15"),
        ],
    }

    normalized = normalize_boundary_features(source, territory_reference_date(2021))

    assert {item["istat_code"] for item in normalized["province"]} == {"215", "258", "263"}
    assert {item["parent_istat_code"] for item in normalized["municipality"]} == {"215", "258", "263"}
    assert {item["source_cod_prov"] for item in normalized["province"]} == {"015", "058", "063"}
    assert {item["source_cod_uts"] for item in normalized["province"]} == {"215", "258", "263"}
    assert all(item["territory_version_id"].endswith("@2021-12-31") for records in normalized.values() for item in records)


def test_2021_municipality_does_not_fall_back_to_cod_prov_when_uts_parent_is_missing() -> None:
    source = _valid_source_features()
    source["province"] = [
        _source_feature("province", source_identity=("milano",), code=None, name="Milano", source_codes={"cod_prov": "015", "cod_cm": "015", "cod_uts": "015"}),
    ]
    source["municipality"] = [
        _source_feature("municipality", source_identity="015146", code="015146", name="Milano", source_codes={"cod_prov": "015", "cod_cm": "215", "cod_uts": "215"}),
    ]

    with pytest.raises(ValueError, match="parent does not exist.*215"):
        normalize_boundary_features(source, territory_reference_date(2021))


def test_2021_non_metro_keeps_matching_province_and_uts_code() -> None:
    source = _valid_source_features()

    normalized = normalize_boundary_features(source, territory_reference_date(2021))

    assert normalized["province"][0]["istat_code"] == "001"
    assert normalized["municipality"][0]["parent_istat_code"] == "001"


def test_pre_2021_schema_preserves_legacy_province_code_priority() -> None:
    source = _valid_source_features()
    source["province"][0]["source_codes"] = {"cod_uts": "201", "cod_prov": "001", "cod_cm": None, "cod_pcm": None}
    source["municipality"][0]["source_codes"] = {"cod_uts": "201", "cod_prov": "001", "cod_cm": None, "cod_pcm": None}

    normalized = normalize_boundary_features(source, territory_reference_date(2020))

    assert normalized["province"][0]["istat_code"] == "001"
    assert normalized["municipality"][0]["parent_istat_code"] == "001"


def test_2021_normalization_regression_keeps_all_municipalities_through_hierarchy_resolution() -> None:
    source = _valid_source_features()
    source["province"] = [_source_feature("province", source_identity=("torino",), code=None, name="Torino", source_codes={"cod_prov": "001", "cod_uts": "201"})]
    source["municipality"] = [
        _source_feature(
            "municipality", source_identity=f"{index:06d}", code=f"{index:06d}",
            name=f"Comune {index}", source_codes={"cod_prov": "001", "cod_uts": "201"},
        )
        for index in range(1, 7905)
    ]

    normalized = normalize_boundary_features(source, territory_reference_date(2021))

    assert len(normalized["municipality"]) == 7904
    assert {item["parent_istat_code"] for item in normalized["municipality"]} == {"201"}


@pytest.mark.parametrize(
    ("source", "error"),
    (
        (
            {
                **_valid_source_features(),
                "municipality": [_source_feature("municipality", source_identity="001001", code="001001", name="Orfano", source_codes={"cod_uts": "999", "cod_prov": "001"})],
            },
            "parent does not exist",
        ),
        (
            {
                **_valid_source_features(),
                "province": [_source_feature("province", source_identity=("orfana",), code=None, name="Orfana", source_codes={"cod_uts": "001"}, region_code="99")],
            },
            "province has an unknown region parent",
        ),
        (
            {
                **_valid_source_features(),
                "province": [
                    _source_feature("province", source_identity=("a",), code=None, name="A", source_codes={"cod_uts": "001"}),
                    _source_feature("province", source_identity=("b",), code=None, name="B", source_codes={"cod_uts": "001"}),
                ],
                "municipality": [_source_feature("municipality", source_identity="001001", code="001001", name="Ambiguo", source_codes={"cod_uts": "001", "cod_prov": "001"})],
            },
            "resolves multiple province features",
        ),
    ),
)
def test_boundary_normalization_fails_closed_for_invalid_hierarchy(source: dict[str, list[dict]], error: str) -> None:
    with pytest.raises(ValueError, match=error):
        normalize_boundary_features(source, territory_reference_date(2021))


def test_boundary_ingest_creates_partition_directories(tmp_path: Path, monkeypatch) -> None:
    def fake_download(_url: str, destination: Path, _source_id: str, *, offline: bool = False) -> dict:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr("placeholder", "")
        return {"unchanged": False}

    def fake_source_features(_path: Path, level: str) -> list[dict]:
        return _valid_source_features()[level]

    monkeypatch.setattr(territories, "download", fake_download)
    monkeypatch.setattr(territories, "_shape_file", lambda *_args: Path("unused.shp"))
    monkeypatch.setattr(territories, "_source_features", fake_source_features)

    canonical = tmp_path / "canonical"
    territories.ingest_boundaries(tmp_path / "data", canonical, years=(2025,))

    for level in ("municipality", "province", "region"):
        assert (canonical / "territories" / "reference_year=2025" / f"{level}.parquet").exists()


def test_hierarchy_validator_rejects_orphans_in_canonical_frames() -> None:
    valid = normalize_boundary_features(_valid_source_features(), territory_reference_date(2021))
    frames = {level: pd.DataFrame(records) for level, records in valid.items()}
    assert validate_territory_hierarchy(frames)["orphan_municipalities"] == 0
    frames["municipality"].loc[0, "parent_istat_code"] = "999"
    with pytest.raises(ValueError, match="orphan municipalities"):
        validate_territory_hierarchy(frames)


def test_2021_stale_canonical_is_not_reusable(tmp_path: Path) -> None:
    root = tmp_path / "territories" / "reference_year=2021"
    root.mkdir(parents=True)
    for level, code, parent in (
        ("region", "01", None),
        ("province", "201", "01"),
        ("municipality", "001001", "201"),
    ):
        pd.DataFrame([{
            "territory_id": f"it:{level}:{code}", "territory_version_id": f"it:{level}:{code}@2021-01-01",
            "level": level, "istat_code": code, "name": level, "parent_istat_code": parent,
            "reference_date": "2021-01-01", "geometry_wkb": Point(12, 42).wkb,
        }]).to_parquet(root / f"{level}.parquet")

    assert territories._canonical_snapshot_is_current(root, 2021) is False


def test_2021_v2_canonical_is_not_reusable_after_field_semantic_resolution(tmp_path: Path) -> None:
    root = tmp_path / "territories" / "reference_year=2021"
    root.mkdir(parents=True)
    for level, code, parent in (
        ("region", "01", None),
        ("province", "215", "01"),
        ("municipality", "015146", "215"),
    ):
        pd.DataFrame([{
            "territory_id": f"it:{level}:{code}", "territory_version_id": f"it:{level}:{code}@2021-12-31",
            "canonical_contract_version": 2, "level": level, "istat_code": code, "name": level,
            "parent_istat_code": parent, "reference_date": "2021-12-31", "geometry_wkb": Point(12, 42).wkb,
        }]).to_parquet(root / f"{level}.parquet")

    assert territories._canonical_snapshot_is_current(root, 2021) is False


def test_country_version_matches_requested_territory_reference_year(tmp_path: Path) -> None:
    reference = tmp_path / "canonical" / "territories" / "reference_year=2025"
    reference.mkdir(parents=True)
    for level in ("municipality", "province", "region"):
        # Empty Parquet is sufficient: country is injected by territory index.
        import pandas as pd
        pd.DataFrame(columns=["territory_id", "name", "geometry_wkb"]).to_parquet(reference / f"{level}.parquet")
    country = load_territory_index(tmp_path / "canonical", year=2025)["it:country:IT"]
    assert country["territory_version_id"] == "it:country:IT@2025-01-01"
    assert country["reference_date"] == "2025-01-01"
