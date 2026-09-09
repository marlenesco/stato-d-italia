from __future__ import annotations

from copy import deepcopy

import pytest

from stato_italia.historical_contract import (
    BREAK_EFFECTS,
    CAPABILITY_NAMES,
    DERIVATION_STATUSES,
    ELIGIBILITY_STATUSES,
    HISTORICAL_CONTRACT_SCHEMA_VERSION,
    HISTORICAL_REASON_CODES,
    PERIOD_KINDS,
    SERIES_BREAK_DIMENSIONS,
    TERRITORY_MODES,
    validate_historical_contract,
)


def _capability(
    status: str,
    *,
    reason_code: str | None = None,
    reason: str | None = None,
    evidence: list[str] | None = None,
) -> dict[str, object]:
    return {
        "status": status,
        "reason_code": reason_code,
        "reason": reason,
        "evidence": [] if evidence is None else evidence,
    }


def _blocked(reason_code: str, reason: str = "Capability intentionally unavailable") -> dict[str, object]:
    return _capability("blocked", reason_code=reason_code, reason=reason)


def _base_contract() -> dict[str, object]:
    return {
        "schema_version": 1,
        "reference_period": {
            "start": "2024-01-01",
            "end": "2024-12-31",
            "kind": "annual",
            "duration_days": 366,
        },
        "source_release": {
            "published_at": "2026-09-09T10:00:00Z",
            "release_id": "official-release-2026",
            "resolved_url": "https://example.test/data.xlsx",
            "raw_sha256": "a" * 64,
        },
        "source_version": "official-v1",
        "project_release_id": "project-release-1",
        "territory": {
            "mode": "contemporaneous_exact",
            "reference_date": "2024-01-01",
            "source_id": "istat-administrative-boundaries",
            "territory_version_id": "it:region:01@2024-01-01",
            "geometry_version_id": "istat-region-2024-a",
            "crosswalk_id": None,
        },
        "semantics": {
            "metric_id": "example_metric",
            "unit": "km2",
            "methodology_version": "official-v1",
            "classification_version": None,
            "spatial_resolution": None,
        },
        "series_breaks_before": [],
        "capabilities": {
            "display": _capability("allowed", evidence=["official:table:1"]),
            "map": _capability("allowed", evidence=["geometry:istat-region-2024-a"]),
            "timeseries": _blocked("insufficient_periods"),
            "delta": _blocked("insufficient_periods"),
            "trend": _blocked("methodology_not_defined"),
            "ranking": _blocked("asset_not_published"),
            "cross_territory": _blocked("asset_not_published"),
        },
        "derivation": {
            "official_status": "official",
            "algorithm_version": None,
            "input_references": [],
            "coverage": None,
            "quality_status": "verified",
        },
    }


def _break(dimension: str, effect: str = "block_comparison") -> dict[str, object]:
    return {
        "dimension": dimension,
        "effect": effect,
        "reason_code": f"series_break_{dimension}",
        "reason": f"Verified {dimension} transition",
        "evidence": [f"methodology:{dimension}"],
    }


def test_controlled_vocabularies_are_stable_and_exact() -> None:
    assert HISTORICAL_CONTRACT_SCHEMA_VERSION == 1
    assert TERRITORY_MODES == {
        "contemporaneous_exact", "source_harmonized", "project_aggregated_exact",
        "non_administrative_grid", "official_crosswalk", "project_harmonized", "unknown",
    }
    assert ELIGIBILITY_STATUSES == {
        "allowed", "allowed_with_annotation", "blocked", "not_applicable", "unresolved",
    }
    assert CAPABILITY_NAMES == {
        "display", "map", "timeseries", "delta", "trend", "ranking", "cross_territory",
    }
    assert SERIES_BREAK_DIMENSIONS == {
        "metric", "unit", "methodology", "classification", "territory", "revision",
        "period_duration", "spatial_resolution",
    }
    assert BREAK_EFFECTS == {"annotate", "segment", "block_comparison"}
    assert PERIOD_KINDS == {"instant", "annual", "interval", "change_interval"}
    assert DERIVATION_STATUSES == {"official", "derived_by_stato_italia"}
    assert "asset_not_published" in HISTORICAL_REASON_CODES
    assert len(HISTORICAL_REASON_CODES) == 17


def test_valid_exact_administrative_observation_is_detached() -> None:
    payload = _base_contract()
    original = deepcopy(payload)

    result = validate_historical_contract(payload)

    assert result == original
    assert result is not payload
    result["source_version"] = "changed"
    assert payload == original


def test_valid_source_harmonized_observation_is_explicitly_annotated() -> None:
    payload = _base_contract()
    payload["territory"]["mode"] = "source_harmonized"
    for name in ("display", "map"):
        payload["capabilities"][name] = _capability(
            "allowed_with_annotation",
            reason_code="source_harmonized_only",
            reason="Published on the source's 2024 common geography",
            evidence=["source:geography:2024"],
        )

    result = validate_historical_contract(payload)

    assert result["territory"]["mode"] == "source_harmonized"
    assert result["capabilities"]["map"]["status"] == "allowed_with_annotation"


def test_valid_raster_derived_administrative_observation() -> None:
    payload = _base_contract()
    payload["territory"]["mode"] = "project_aggregated_exact"
    payload["derivation"] = {
        "official_status": "derived_by_stato_italia",
        "algorithm_version": "zonal-area-weighted-v1",
        "input_references": ["raw:raster:sha256", "geometry:istat-region-2024-a"],
        "coverage": 0.998,
        "quality_status": "complete",
    }

    result = validate_historical_contract(payload)

    assert result["derivation"]["official_status"] == "derived_by_stato_italia"
    assert result["derivation"]["input_references"]


def test_valid_native_grid_does_not_invent_administrative_geometry() -> None:
    payload = _base_contract()
    payload["territory"] = {
        "mode": "non_administrative_grid",
        "reference_date": None,
        "source_id": None,
        "territory_version_id": None,
        "geometry_version_id": None,
        "crosswalk_id": None,
    }
    payload["capabilities"]["map"] = _capability("allowed", evidence=["source:grid-cell-layout"])

    result = validate_historical_contract(payload)

    assert result["territory"]["geometry_version_id"] is None


def test_valid_change_interval_remains_distinct_from_status_period() -> None:
    payload = _base_contract()
    payload["reference_period"] = {
        "start": "2021-01-01",
        "end": "2024-12-31",
        "kind": "change_interval",
        "duration_days": 1461,
    }

    result = validate_historical_contract(payload)

    assert result["reference_period"]["kind"] == "change_interval"


def test_multiple_historical_break_dimensions_survive_validation() -> None:
    payload = _base_contract()
    payload["series_breaks_before"] = [
        _break("methodology", "segment"),
        _break("spatial_resolution", "block_comparison"),
        _break("territory", "segment"),
    ]
    payload["capabilities"]["timeseries"] = _capability(
        "allowed_with_annotation",
        reason_code="series_break_methodology",
        reason="Series is displayed as separate segments",
        evidence=["contract:break-matrix"],
    )

    result = validate_historical_contract(payload)

    assert [item["dimension"] for item in result["series_breaks_before"]] == [
        "methodology", "spatial_resolution", "territory",
    ]


def test_blocked_and_unresolved_reason_codes_survive_validation() -> None:
    payload = _base_contract()
    payload["capabilities"]["timeseries"] = _capability(
        "unresolved",
        reason_code="insufficient_periods",
        reason="A second verified period is not available",
        evidence=["audit:h1a"],
    )

    result = validate_historical_contract(payload)

    assert result["capabilities"]["timeseries"]["reason_code"] == "insufficient_periods"
    assert result["capabilities"]["delta"]["status"] == "blocked"


@pytest.mark.parametrize("schema_version", [0, 2, True, "1"])
def test_rejects_unsupported_schema_version(schema_version: object) -> None:
    payload = _base_contract()
    payload["schema_version"] = schema_version
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


@pytest.mark.parametrize("mode", ["invented", "nearest_year", "current_boundary_fallback"])
def test_rejects_unknown_or_fallback_territory_mode(mode: str) -> None:
    payload = _base_contract()
    payload["territory"]["mode"] = mode
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


def test_rejects_allowed_capability_without_evidence() -> None:
    payload = _base_contract()
    payload["capabilities"]["display"]["evidence"] = []
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


def test_rejects_unknown_territory_with_enabled_map() -> None:
    payload = _base_contract()
    payload["territory"] = {
        "mode": "unknown",
        "reference_date": None,
        "source_id": None,
        "territory_version_id": None,
        "geometry_version_id": None,
        "crosswalk_id": None,
    }
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


def test_rejects_missing_source_version() -> None:
    payload = _base_contract()
    del payload["source_version"]
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


def test_rejects_invalid_raw_sha256() -> None:
    payload = _base_contract()
    payload["source_release"]["raw_sha256"] = "not-a-sha"
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


@pytest.mark.parametrize(
    ("start", "end", "kind"),
    [
        ("2024-12-31", "2024-01-01", "annual"),
        ("2024-01-01", "not-a-date", "annual"),
        ("2024-01-01", "2024-12-30", "annual"),
        ("2024-01-01", "2024-01-01", "change_interval"),
    ],
)
def test_rejects_invalid_period_dates(start: str, end: str, kind: str) -> None:
    payload = _base_contract()
    payload["reference_period"] |= {"start": start, "end": end, "kind": kind}
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


def test_rejects_incoherent_period_duration() -> None:
    payload = _base_contract()
    payload["reference_period"]["duration_days"] = 365
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


def test_rejects_project_aggregated_exact_marked_official() -> None:
    payload = _base_contract()
    payload["territory"]["mode"] = "project_aggregated_exact"
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


def test_rejects_project_harmonized_without_crosswalk() -> None:
    payload = _base_contract()
    payload["territory"]["mode"] = "project_harmonized"
    payload["derivation"] = {
        "official_status": "derived_by_stato_italia",
        "algorithm_version": "official-crosswalk-v1",
        "input_references": ["observation:1", "geometry:1"],
        "coverage": 1.0,
        "quality_status": "complete",
    }
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


def test_rejects_derived_observation_without_algorithm_version() -> None:
    payload = _base_contract()
    payload["derivation"]["official_status"] = "derived_by_stato_italia"
    payload["derivation"]["input_references"] = ["observation:1"]
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


def test_rejects_derived_observation_without_input_references() -> None:
    payload = _base_contract()
    payload["derivation"]["official_status"] = "derived_by_stato_italia"
    payload["derivation"]["algorithm_version"] = "derived-v1"
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


def test_rejects_invalid_capability_status() -> None:
    payload = _base_contract()
    payload["capabilities"]["display"]["status"] = "available"
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


def test_rejects_invalid_reason_code() -> None:
    payload = _base_contract()
    payload["capabilities"]["delta"]["reason_code"] = "insufficent_periods"
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


def test_rejects_invalid_break_dimension() -> None:
    payload = _base_contract()
    payload["series_breaks_before"] = [_break("weather")]
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


def test_rejects_duplicate_ambiguous_break_declaration() -> None:
    payload = _base_contract()
    payload["series_breaks_before"] = [_break("territory", "segment"), _break("territory")]
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


def test_rejects_malformed_capability_declaration() -> None:
    payload = _base_contract()
    payload["capabilities"]["map"] = "allowed"
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


def test_rejects_missing_required_section() -> None:
    payload = _base_contract()
    del payload["semantics"]
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


@pytest.mark.parametrize(
    ("section", "malformed"),
    [
        ("reference_period", []),
        ("source_release", []),
        ("territory", []),
        ("semantics", []),
        ("series_breaks_before", {}),
        ("capabilities", []),
        ("derivation", []),
    ],
)
def test_rejects_malformed_required_section_types(section: str, malformed: object) -> None:
    payload = _base_contract()
    payload[section] = malformed
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


@pytest.mark.parametrize("status", ["blocked", "unresolved"])
def test_rejects_reasoned_capability_without_reason_metadata(status: str) -> None:
    payload = _base_contract()
    payload["capabilities"]["trend"] = _capability(status)
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


def test_rejects_exact_territory_without_geometry_identity() -> None:
    payload = _base_contract()
    payload["territory"]["geometry_version_id"] = None
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


def test_rejects_official_crosswalk_without_crosswalk_identity() -> None:
    payload = _base_contract()
    payload["territory"]["mode"] = "official_crosswalk"
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


def test_rejects_plain_allowed_source_harmonized_capability() -> None:
    payload = _base_contract()
    payload["territory"]["mode"] = "source_harmonized"
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


def test_rejects_comparison_enabled_across_blocking_break() -> None:
    payload = _base_contract()
    payload["series_breaks_before"] = [_break("methodology")]
    payload["capabilities"]["timeseries"] = _capability(
        "allowed_with_annotation",
        reason_code="series_break_methodology",
        reason="Segmented series",
        evidence=["methodology:transition"],
    )
    payload["capabilities"]["delta"] = _capability("allowed", evidence=["metric:comparison"])
    with pytest.raises(ValueError):
        validate_historical_contract(payload)


def test_rejects_unexpected_fields_in_strict_contract() -> None:
    payload = _base_contract()
    payload["territory"]["nearest_year"] = 2023
    with pytest.raises(ValueError):
        validate_historical_contract(payload)
