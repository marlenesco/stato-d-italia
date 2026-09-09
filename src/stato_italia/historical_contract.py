from __future__ import annotations

import copy
import math
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

HISTORICAL_CONTRACT_SCHEMA_VERSION = 1

TERRITORY_MODES = frozenset({
    "contemporaneous_exact",
    "source_harmonized",
    "project_aggregated_exact",
    "non_administrative_grid",
    "official_crosswalk",
    "project_harmonized",
    "unknown",
})
ELIGIBILITY_STATUSES = frozenset({
    "allowed",
    "allowed_with_annotation",
    "blocked",
    "not_applicable",
    "unresolved",
})
CAPABILITY_NAMES = frozenset({
    "display",
    "map",
    "timeseries",
    "delta",
    "trend",
    "ranking",
    "cross_territory",
})
SERIES_BREAK_DIMENSIONS = frozenset({
    "metric",
    "unit",
    "methodology",
    "classification",
    "territory",
    "revision",
    "period_duration",
    "spatial_resolution",
})
BREAK_EFFECTS = frozenset({"annotate", "segment", "block_comparison"})
PERIOD_KINDS = frozenset({"instant", "annual", "interval", "change_interval"})
DERIVATION_STATUSES = frozenset({"official", "derived_by_stato_italia"})
HISTORICAL_REASON_CODES = frozenset({
    "missing_territory_evidence",
    "identity_audit_required",
    "source_harmonized_only",
    "series_break_metric",
    "series_break_unit",
    "series_break_methodology",
    "series_break_classification",
    "series_break_territory",
    "series_break_revision",
    "series_break_period_duration",
    "series_break_spatial_resolution",
    "insufficient_periods",
    "sparse_series_no_interpolation",
    "official_change_product_required",
    "source_version_mismatch",
    "methodology_not_defined",
    "asset_not_published",
})

_ENABLED_STATUSES = frozenset({"allowed", "allowed_with_annotation"})
_REASONED_STATUSES = frozenset({"allowed_with_annotation", "blocked", "unresolved"})
_GEOMETRY_MODES = frozenset({
    "contemporaneous_exact",
    "source_harmonized",
    "project_aggregated_exact",
    "official_crosswalk",
    "project_harmonized",
})
_CROSSWALK_MODES = frozenset({"official_crosswalk", "project_harmonized"})
_PROJECT_DERIVED_TERRITORY_MODES = frozenset({"project_aggregated_exact", "project_harmonized"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _fail(path: str, message: str) -> None:
    raise ValueError(f"{path}: {message}")


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(path, "must be an object")
    return value


def _exact_keys(
    value: dict[str, Any], path: str, required: frozenset[str], optional: frozenset[str] = frozenset(),
) -> None:
    missing = sorted(required - value.keys())
    if missing:
        _fail(path, f"missing required fields: {', '.join(missing)}")
    unexpected = sorted(value.keys() - required - optional)
    if unexpected:
        _fail(path, f"unsupported fields: {', '.join(unexpected)}")


def _required_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(path, "must be a non-empty string")
    if value != value.strip():
        _fail(path, "must not contain surrounding whitespace")
    return value


def _nullable_string(value: Any, path: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, path)


def _string_list(value: Any, path: str, *, require_items: bool) -> list[str]:
    if not isinstance(value, list):
        _fail(path, "must be an array")
    if require_items and not value:
        _fail(path, "must contain at least one item")
    result = [_required_string(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        _fail(path, "must not contain duplicate items")
    return result


def _iso_date(value: Any, path: str) -> date:
    raw = _required_string(value, path)
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{path}: must be an ISO 8601 date") from exc
    if raw != parsed.isoformat():
        _fail(path, "must use canonical YYYY-MM-DD form")
    return parsed


def _publication_date(value: Any, path: str) -> None:
    raw = _required_string(value, path)
    try:
        if "T" not in raw:
            if raw != date.fromisoformat(raw).isoformat():
                _fail(path, "must use a canonical ISO 8601 date")
            return
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path}: must be an ISO 8601 date or datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(path, "datetime must include a timezone")


def _enum(value: Any, allowed: frozenset[str], path: str) -> str:
    raw = _required_string(value, path)
    if raw not in allowed:
        _fail(path, f"unsupported value: {raw}")
    return raw


def _validate_reference_period(value: Any) -> None:
    period = _mapping(value, "reference_period")
    _exact_keys(
        period,
        "reference_period",
        frozenset({"start", "end", "kind"}),
        frozenset({"duration_days"}),
    )
    start = _iso_date(period["start"], "reference_period.start")
    end = _iso_date(period["end"], "reference_period.end")
    kind = _enum(period["kind"], PERIOD_KINDS, "reference_period.kind")
    if start > end:
        _fail("reference_period", "start must not be after end")
    if kind == "instant" and start != end:
        _fail("reference_period", "instant periods require identical start and end")
    if kind in {"interval", "change_interval"} and start == end:
        _fail("reference_period", f"{kind} requires a non-zero interval")
    if kind == "annual" and (
        start.year != end.year or start != date(start.year, 1, 1) or end != date(end.year, 12, 31)
    ):
        _fail("reference_period", "annual periods must cover one complete calendar year")
    if "duration_days" in period:
        duration = period["duration_days"]
        if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
            _fail("reference_period.duration_days", "must be a positive integer")
        expected = (end - start).days + 1
        if duration != expected:
            _fail("reference_period.duration_days", f"must equal inclusive period duration {expected}")


def _validate_source_release(value: Any) -> None:
    release = _mapping(value, "source_release")
    _exact_keys(
        release,
        "source_release",
        frozenset({"published_at", "release_id", "resolved_url", "raw_sha256"}),
    )
    _publication_date(release["published_at"], "source_release.published_at")
    _required_string(release["release_id"], "source_release.release_id")
    resolved_url = _required_string(release["resolved_url"], "source_release.resolved_url")
    parsed_url = urlsplit(resolved_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        _fail("source_release.resolved_url", "must be an absolute HTTP(S) URL")
    raw_sha256 = _required_string(release["raw_sha256"], "source_release.raw_sha256")
    if not _SHA256_RE.fullmatch(raw_sha256):
        _fail("source_release.raw_sha256", "must be a lowercase 64-character SHA-256")


def _validate_territory(value: Any) -> str:
    territory = _mapping(value, "territory")
    fields = frozenset({
        "mode",
        "reference_date",
        "source_id",
        "territory_version_id",
        "geometry_version_id",
        "crosswalk_id",
    })
    _exact_keys(territory, "territory", fields)
    mode = _enum(territory["mode"], TERRITORY_MODES, "territory.mode")
    reference_date = territory["reference_date"]
    if reference_date is not None:
        _iso_date(reference_date, "territory.reference_date")
    for field in ("source_id", "territory_version_id", "geometry_version_id", "crosswalk_id"):
        _nullable_string(territory[field], f"territory.{field}")

    if mode in _GEOMETRY_MODES:
        for field in ("reference_date", "source_id", "territory_version_id", "geometry_version_id"):
            if territory[field] is None:
                _fail(f"territory.{field}", f"is required for territory mode {mode}")
    if mode in _CROSSWALK_MODES:
        if territory["crosswalk_id"] is None:
            _fail("territory.crosswalk_id", f"is required for territory mode {mode}")
    elif territory["crosswalk_id"] is not None:
        _fail("territory.crosswalk_id", f"is not valid for territory mode {mode}")

    if mode == "non_administrative_grid":
        for field in ("reference_date", "source_id", "territory_version_id", "geometry_version_id"):
            if territory[field] is not None:
                _fail(f"territory.{field}", "must be null for non_administrative_grid")
    if mode == "unknown":
        for field in ("territory_version_id", "geometry_version_id"):
            if territory[field] is not None:
                _fail(f"territory.{field}", "must be null when territory mode is unknown")
    return mode


def _validate_semantics(value: Any) -> None:
    semantics = _mapping(value, "semantics")
    _exact_keys(
        semantics,
        "semantics",
        frozenset({
            "metric_id",
            "unit",
            "methodology_version",
            "classification_version",
            "spatial_resolution",
        }),
    )
    for field in ("metric_id", "unit", "methodology_version"):
        _required_string(semantics[field], f"semantics.{field}")
    for field in ("classification_version", "spatial_resolution"):
        _nullable_string(semantics[field], f"semantics.{field}")


def _validate_breaks(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        _fail("series_breaks_before", "must be an array")
    seen_dimensions: set[str] = set()
    result: list[dict[str, Any]] = []
    fields = frozenset({"dimension", "effect", "reason_code", "reason", "evidence"})
    for index, item in enumerate(value):
        path = f"series_breaks_before[{index}]"
        declaration = _mapping(item, path)
        _exact_keys(declaration, path, fields)
        dimension = _enum(declaration["dimension"], SERIES_BREAK_DIMENSIONS, f"{path}.dimension")
        _enum(declaration["effect"], BREAK_EFFECTS, f"{path}.effect")
        reason_code = _enum(declaration["reason_code"], HISTORICAL_REASON_CODES, f"{path}.reason_code")
        expected_reason_code = f"series_break_{dimension}"
        if reason_code != expected_reason_code:
            _fail(f"{path}.reason_code", f"must be {expected_reason_code} for dimension {dimension}")
        _required_string(declaration["reason"], f"{path}.reason")
        _string_list(declaration["evidence"], f"{path}.evidence", require_items=True)
        if dimension in seen_dimensions:
            _fail(path, f"duplicate series-break dimension: {dimension}")
        seen_dimensions.add(dimension)
        result.append(declaration)
    return result


def _validate_capabilities(value: Any) -> dict[str, dict[str, Any]]:
    capabilities = _mapping(value, "capabilities")
    _exact_keys(capabilities, "capabilities", CAPABILITY_NAMES)
    fields = frozenset({"status", "reason_code", "reason", "evidence"})
    for name in sorted(CAPABILITY_NAMES):
        path = f"capabilities.{name}"
        declaration = _mapping(capabilities[name], path)
        _exact_keys(declaration, path, fields)
        status = _enum(declaration["status"], ELIGIBILITY_STATUSES, f"{path}.status")
        reason = declaration["reason"]
        if reason is not None:
            _required_string(reason, f"{path}.reason")
        reason_code = declaration["reason_code"]
        if reason_code is not None:
            _enum(reason_code, HISTORICAL_REASON_CODES, f"{path}.reason_code")
        evidence = _string_list(
            declaration["evidence"], f"{path}.evidence", require_items=status in _ENABLED_STATUSES,
        )
        if status in _REASONED_STATUSES:
            if reason_code is None or reason is None:
                _fail(path, f"{status} requires a reason_code and reason")
        elif reason_code is not None:
            _fail(f"{path}.reason_code", f"must be null for status {status}")
        if status == "not_applicable" and reason is None:
            _fail(f"{path}.reason", "not_applicable requires an explanation")
        if status == "allowed" and not evidence:
            _fail(f"{path}.evidence", "allowed capabilities require supporting evidence")
    return capabilities


def _validate_derivation(value: Any) -> str:
    derivation = _mapping(value, "derivation")
    _exact_keys(
        derivation,
        "derivation",
        frozenset({
            "official_status",
            "algorithm_version",
            "input_references",
            "coverage",
            "quality_status",
        }),
    )
    status = _enum(derivation["official_status"], DERIVATION_STATUSES, "derivation.official_status")
    algorithm_version = _nullable_string(derivation["algorithm_version"], "derivation.algorithm_version")
    input_references = _string_list(
        derivation["input_references"],
        "derivation.input_references",
        require_items=status == "derived_by_stato_italia",
    )
    coverage = derivation["coverage"]
    if coverage is not None:
        if isinstance(coverage, bool) or not isinstance(coverage, (int, float)):
            _fail("derivation.coverage", "must be a number between 0 and 1 or null")
        if not math.isfinite(float(coverage)) or not 0 <= float(coverage) <= 1:
            _fail("derivation.coverage", "must be finite and between 0 and 1")
    _nullable_string(derivation["quality_status"], "derivation.quality_status")

    if status == "derived_by_stato_italia" and algorithm_version is None:
        _fail("derivation.algorithm_version", "is required for derived_by_stato_italia")
    if status == "official" and (algorithm_version is not None or input_references):
        _fail("derivation", "official observations must not contain project derivation identity")
    return status


def _capability_enabled(capabilities: dict[str, dict[str, Any]], name: str) -> bool:
    return capabilities[name]["status"] in _ENABLED_STATUSES


def _validate_cross_fields(
    territory_mode: str,
    derivation_status: str,
    breaks: list[dict[str, Any]],
    capabilities: dict[str, dict[str, Any]],
) -> None:
    if territory_mode in _PROJECT_DERIVED_TERRITORY_MODES and derivation_status != "derived_by_stato_italia":
        _fail(
            "derivation.official_status",
            f"territory mode {territory_mode} requires derived_by_stato_italia",
        )
    if territory_mode == "unknown" and _capability_enabled(capabilities, "map"):
        _fail("capabilities.map", "unknown territory cannot enable administrative map eligibility")

    for name in ("map", "timeseries", "delta", "trend", "ranking", "cross_territory"):
        if _capability_enabled(capabilities, name) and not _capability_enabled(capabilities, "display"):
            _fail(f"capabilities.{name}", "cannot be enabled when display is not enabled")
    for name in ("delta", "trend"):
        if _capability_enabled(capabilities, name) and not _capability_enabled(capabilities, "timeseries"):
            _fail(f"capabilities.{name}", "cannot be enabled when timeseries is not enabled")

    if territory_mode in {"source_harmonized", "project_harmonized"}:
        for name, declaration in capabilities.items():
            if declaration["status"] == "allowed":
                _fail(f"capabilities.{name}", f"territory mode {territory_mode} requires annotation")

    if breaks:
        if capabilities["timeseries"]["status"] == "allowed":
            _fail("capabilities.timeseries", "series breaks require annotated or disabled timeseries")
        comparison_break = any(item["effect"] in {"segment", "block_comparison"} for item in breaks)
        if comparison_break:
            for name in ("delta", "trend"):
                if _capability_enabled(capabilities, name):
                    _fail(f"capabilities.{name}", "cannot cross a segmenting or comparison-blocking break")


def validate_historical_contract(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and return a detached historical metadata contract.

    Validation is deterministic and side-effect free. Missing values are never
    inferred, invalid values are never repaired, and the input is not mutated.
    """
    contract = _mapping(payload, "historical_contract")
    _exact_keys(
        contract,
        "historical_contract",
        frozenset({
            "schema_version",
            "reference_period",
            "source_release",
            "source_version",
            "project_release_id",
            "territory",
            "semantics",
            "series_breaks_before",
            "capabilities",
            "derivation",
        }),
    )
    schema_version = contract["schema_version"]
    if isinstance(schema_version, bool) or schema_version != HISTORICAL_CONTRACT_SCHEMA_VERSION:
        _fail("schema_version", f"unsupported historical contract schema: {schema_version!r}")

    _validate_reference_period(contract["reference_period"])
    _validate_source_release(contract["source_release"])
    _required_string(contract["source_version"], "source_version")
    _required_string(contract["project_release_id"], "project_release_id")
    territory_mode = _validate_territory(contract["territory"])
    _validate_semantics(contract["semantics"])
    breaks = _validate_breaks(contract["series_breaks_before"])
    capabilities = _validate_capabilities(contract["capabilities"])
    derivation_status = _validate_derivation(contract["derivation"])
    _validate_cross_fields(territory_mode, derivation_status, breaks, capabilities)
    return copy.deepcopy(contract)
