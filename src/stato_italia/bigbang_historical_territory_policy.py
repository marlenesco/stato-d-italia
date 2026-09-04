from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd

from .common import json_dump


FIRST_BIGBANG_YEAR = 1951
LAST_BIGBANG_YEAR = 2025
TERRITORY_LEVELS = ("country", "region", "province", "municipality")
ISTAT_BOUNDARIES_SOURCE = "ISTAT Confini delle unita amministrative a fini statistici"
ISTAT_BOUNDARIES_URL = "https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/"


@dataclass(frozen=True)
class TerritoryGeometryVersion:
    territory_level: str
    reference_year: int
    territory_reference_date: str
    territory_source: str
    geometry_reference: str
    documented_valid_from: int | None = None
    documented_valid_to: int | None = None
    documented_interval_source: str | None = None


@dataclass(frozen=True)
class TerritoryInventoryEntry:
    territory_level: str
    reference_year: int
    territory_reference_date: str | None
    territory_count: int
    territory_version_id_sample: str | None
    geometry_reference: str
    accepted_for_policy: bool
    reason: str | None = None


@dataclass(frozen=True)
class TerritoryPolicyDecision:
    reference_year: int
    territory_level: str
    support_status: str
    data_kind: str
    territory_reference_date: str | None
    territory_source: str
    reason: str
    geometry_reference: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _expected_istat_reference_date(year: int) -> str:
    if year == 2021:
        return "2021-12-31"
    return f"{year}-01-01"


def _as_version(value: TerritoryGeometryVersion | Mapping[str, object]) -> TerritoryGeometryVersion:
    if isinstance(value, TerritoryGeometryVersion):
        return value
    return TerritoryGeometryVersion(
        territory_level=str(value["territory_level"]),
        reference_year=int(value["reference_year"]),
        territory_reference_date=str(value["territory_reference_date"]),
        territory_source=str(value["territory_source"]),
        geometry_reference=str(value["geometry_reference"]),
        documented_valid_from=(int(value["documented_valid_from"]) if value.get("documented_valid_from") is not None else None),
        documented_valid_to=(int(value["documented_valid_to"]) if value.get("documented_valid_to") is not None else None),
        documented_interval_source=(str(value["documented_interval_source"]) if value.get("documented_interval_source") else None),
    )


def _validated_versions(
    versions: Iterable[TerritoryGeometryVersion | Mapping[str, object]],
    territory_level: str,
) -> list[TerritoryGeometryVersion]:
    output = []
    for version in versions:
        item = _as_version(version)
        if item.territory_level != territory_level:
            continue
        try:
            reference_date = date.fromisoformat(item.territory_reference_date)
        except ValueError as exc:
            raise ValueError(f"Invalid territory reference date: {item.territory_reference_date}") from exc
        if reference_date.year != item.reference_year:
            raise ValueError("Territory reference year and date disagree")
        output.append(item)
    return output


def _documented_interval_match(
    versions: Iterable[TerritoryGeometryVersion], reference_year: int,
) -> TerritoryGeometryVersion | None:
    candidates = [
        version
        for version in versions
        if version.documented_interval_source
        and version.documented_valid_from is not None
        and version.documented_valid_to is not None
        and version.documented_valid_from <= reference_year <= version.documented_valid_to
    ]
    if len(candidates) > 1:
        raise ValueError(f"Ambiguous documented territory intervals for {reference_year}")
    return candidates[0] if candidates else None


def resolve_bigbang_territory_policy(
    reference_year: int,
    territory_level: str,
    available_territory_versions: Iterable[TerritoryGeometryVersion | Mapping[str, object]],
) -> TerritoryPolicyDecision:
    """Resolve BIGBANG territorial support without nearest-year or current-boundary fallbacks."""
    if not FIRST_BIGBANG_YEAR <= reference_year <= LAST_BIGBANG_YEAR:
        raise ValueError(f"BIGBANG reference year must be {FIRST_BIGBANG_YEAR}-{LAST_BIGBANG_YEAR}")
    if territory_level not in TERRITORY_LEVELS:
        raise ValueError(f"Unsupported BIGBANG territory level: {territory_level}")
    if territory_level in {"country", "region"}:
        return TerritoryPolicyDecision(
            reference_year=reference_year,
            territory_level=territory_level,
            support_status="official",
            data_kind="official_workbook",
            territory_reference_date=None,
            territory_source="ISPRA BIGBANG 10.0 workbook",
            reason="Official BIGBANG observations remain canonical; no raster-derived replacement is authorized.",
        )
    if territory_level == "municipality":
        return TerritoryPolicyDecision(
            reference_year=reference_year,
            territory_level=territory_level,
            support_status="unsupported_methodology",
            data_kind="none",
            territory_reference_date=None,
            territory_source="ISPRA BIGBANG 10.0 methodology",
            reason="Complete municipal coverage is outside the accepted > 100 km2 methodological applicability gate.",
        )

    versions = _validated_versions(available_territory_versions, territory_level)
    exact = [version for version in versions if version.reference_year == reference_year]
    if len(exact) > 1:
        raise ValueError(f"Ambiguous exact territory versions for {territory_level}/{reference_year}")
    selected = exact[0] if exact else _documented_interval_match(versions, reference_year)
    if selected:
        reason = (
            "Exact canonical territory version for the BIGBANG reference year."
            if selected.reference_year == reference_year
            else f"Documented official validity interval: {selected.documented_interval_source}."
        )
        return TerritoryPolicyDecision(
            reference_year=reference_year,
            territory_level=territory_level,
            support_status="derived_supported",
            data_kind="raster_derived",
            territory_reference_date=selected.territory_reference_date,
            territory_source=selected.territory_source,
            geometry_reference=selected.geometry_reference,
            reason=reason,
        )
    has_undocumented_interval = any(
        version.documented_valid_from is not None
        and version.documented_valid_to is not None
        and version.documented_valid_from <= reference_year <= version.documented_valid_to
        and not version.documented_interval_source
        for version in versions
    )
    reason = (
        "An interval was supplied without an official documented source; it is not a valid crosswalk."
        if has_undocumented_interval
        else "No exact canonical territory version or documented official validity interval exists for this year."
    )
    return TerritoryPolicyDecision(
        reference_year=reference_year,
        territory_level=territory_level,
        support_status="unsupported_missing_exact_geometry",
        data_kind="raster_derived",
        territory_reference_date=None,
        territory_source=ISTAT_BOUNDARIES_SOURCE,
        reason=reason,
    )


def inspect_canonical_territories(canonical_root: Path) -> tuple[list[TerritoryGeometryVersion], list[TerritoryInventoryEntry]]:
    """Return usable versions and a complete auditable inventory of local territory snapshots."""
    versions: list[TerritoryGeometryVersion] = []
    inventory: list[TerritoryInventoryEntry] = []
    root = canonical_root / "territories"
    for directory in sorted(root.glob("reference_year=*")):
        reference_year = int(directory.name.split("=", 1)[1])
        for path in sorted(directory.glob("*.parquet")):
            territory_level = path.stem
            if territory_level not in {"region", "province", "municipality"}:
                raise ValueError(f"Unexpected canonical territory level: {territory_level}")
            table = pd.read_parquet(path, columns=["territory_version_id", "reference_date"])
            reference_dates = sorted(set(table["reference_date"].astype(str)))
            expected_date = _expected_istat_reference_date(reference_year)
            version_ids = table["territory_version_id"].astype(str)
            accepted = bool(
                len(table)
                and reference_dates == [expected_date]
                and version_ids.str.endswith(f"@{expected_date}").all()
            )
            if not len(table):
                reason = "Canonical territory snapshot is empty."
            elif reference_dates != [expected_date]:
                reason = f"Canonical reference_date {reference_dates} does not match the documented ISTAT date {expected_date}."
            elif not version_ids.str.endswith(f"@{expected_date}").all():
                reason = "Canonical territory_version_id does not match the documented ISTAT reference date."
            else:
                reason = None
            entry = TerritoryInventoryEntry(
                territory_level=territory_level,
                reference_year=reference_year,
                territory_reference_date=reference_dates[0] if len(reference_dates) == 1 else None,
                territory_count=len(table),
                territory_version_id_sample=table["territory_version_id"].astype(str).min() if len(table) else None,
                geometry_reference=f"canonical/territories/{directory.name}/{path.name}",
                accepted_for_policy=accepted,
                reason=reason,
            )
            inventory.append(entry)
            if accepted:
                versions.append(TerritoryGeometryVersion(
                    territory_level=territory_level,
                    reference_year=reference_year,
                    territory_reference_date=expected_date,
                    territory_source=ISTAT_BOUNDARIES_SOURCE,
                    geometry_reference=entry.geometry_reference,
                ))
    return versions, inventory


def build_bigbang_historical_support_matrix(
    available_territory_versions: Iterable[TerritoryGeometryVersion | Mapping[str, object]],
) -> list[dict]:
    rows = []
    materialized = tuple(available_territory_versions)
    for reference_year in range(FIRST_BIGBANG_YEAR, LAST_BIGBANG_YEAR + 1):
        for territory_level in TERRITORY_LEVELS:
            rows.append(resolve_bigbang_territory_policy(reference_year, territory_level, materialized).to_dict())
    return rows


def write_bigbang_historical_support_report(canonical_root: Path, report_path: Path) -> dict:
    versions, inventory = inspect_canonical_territories(canonical_root)
    matrix = build_bigbang_historical_support_matrix(versions)
    report = {
        "schemaVersion": 1,
        "policy": "bigbang-historical-territory-support-v1",
        "yearRange": [FIRST_BIGBANG_YEAR, LAST_BIGBANG_YEAR],
        "territoryInventory": [asdict(entry) for entry in inventory],
        "supportMatrix": matrix,
    }
    json_dump(report_path, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the local BIGBANG historical territory support matrix")
    parser.add_argument("--canonical-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = write_bigbang_historical_support_report(args.canonical_root, args.report)
    print(json.dumps({
        "report": str(args.report),
        "inventoryEntries": len(report["territoryInventory"]),
        "matrixRows": len(report["supportMatrix"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
