from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd

from .bigbang_historical_territory_policy import (
    FIRST_BIGBANG_YEAR,
    LAST_BIGBANG_YEAR,
    TerritoryGeometryVersion,
    inspect_canonical_territories,
    resolve_bigbang_territory_policy,
)
from .bigbang_raster_poc import (
    ALGORITHM_VERSION,
    METRIC_SPECS,
    SOURCE,
    RasterMetricSpec,
    _coverage_summary,
    _write_parquet_atomic,
    compare_official_regions,
    derive_prepared_territories,
    extract_raster,
    inspect_raster,
    prepare_territories_for_zonal,
    validate_archive_structure,
)
from .common import json_dump, sha256_file


HISTORICAL_DERIVED_LOGICAL_PATH = (
    f"derived/water/historical/dataset_version={SOURCE['dataset_version']}/"
    f"algorithm_version={ALGORITHM_VERSION}/observations.parquet"
)


@dataclass(frozen=True)
class HistoricalProcessingPlanEntry:
    reference_year: int
    support_status: str
    territory_reference_date: str | None
    geometry_reference: str | None
    process_provinces: bool
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def build_bigbang_historical_processing_plan(
    available_territory_versions: Iterable[TerritoryGeometryVersion],
) -> list[HistoricalProcessingPlanEntry]:
    """Build the province-only historical plan by delegating every year to the policy resolver."""
    versions = tuple(available_territory_versions)
    plan = []
    for reference_year in range(FIRST_BIGBANG_YEAR, LAST_BIGBANG_YEAR + 1):
        decision = resolve_bigbang_territory_policy(reference_year, "province", versions)
        process_provinces = (
            decision.support_status == "derived_supported"
            and decision.territory_reference_date is not None
            and decision.geometry_reference is not None
        )
        plan.append(HistoricalProcessingPlanEntry(
            reference_year=reference_year,
            support_status=decision.support_status,
            territory_reference_date=decision.territory_reference_date,
            geometry_reference=decision.geometry_reference,
            process_provinces=process_provinces,
            reason=decision.reason,
        ))
    return plan


def _geometry_path(canonical_root: Path, geometry_reference: str) -> Path:
    prefix = "canonical/"
    if not geometry_reference.startswith(prefix):
        raise ValueError(f"Unexpected territory geometry reference: {geometry_reference}")
    return canonical_root / geometry_reference.removeprefix(prefix)


def load_bound_territories(
    canonical_root: Path,
    *,
    territory_level: str,
    territory_reference_date: str,
    geometry_reference: str,
) -> pd.DataFrame:
    path = _geometry_path(canonical_root, geometry_reference)
    if not path.exists():
        raise ValueError(f"Approved territory geometry does not exist: {geometry_reference}")
    territories = pd.read_parquet(path)
    required = {"territory_version_id", "level", "reference_date", "geometry_wkb"}
    if missing := required - set(territories.columns):
        raise ValueError(f"Territory geometry lacks fields: {sorted(missing)}")
    if set(territories["level"]) != {territory_level}:
        raise ValueError(f"Approved geometry is not exclusively {territory_level}")
    if set(territories["reference_date"].astype(str)) != {territory_reference_date}:
        raise ValueError("Approved geometry reference_date differs from territorial policy")
    version_ids = territories["territory_version_id"].astype(str)
    if not version_ids.str.endswith(f"@{territory_reference_date}").all():
        raise ValueError("Approved geometry territory_version_id differs from territorial policy")
    if version_ids.duplicated().any():
        raise ValueError("Approved geometry has duplicate territory_version_id")
    return territories


def _exact_geometry_version(
    versions: Iterable[TerritoryGeometryVersion], reference_year: int, territory_level: str,
) -> TerritoryGeometryVersion | None:
    candidates = [
        version for version in versions
        if version.territory_level == territory_level and version.reference_year == reference_year
    ]
    if len(candidates) > 1:
        raise ValueError(f"Ambiguous regional geometry for {territory_level}/{reference_year}")
    return candidates[0] if candidates else None


def _reject_structural_regional_mismatch(comparison: pd.DataFrame, symbol: str, reference_year: int) -> None:
    derived = comparison["derived_raster_value_mm"]
    official = comparison["official_value_mm"]
    for factor in (0.001, 1000.0):
        if (derived == official * factor).all():
            raise ValueError(
                f"Regional {symbol}/{reference_year} validation has a structural {factor:g} unit-scale mismatch"
            )


def _historical_destination(derived_root: Path) -> Path:
    return derived_root.parent / HISTORICAL_DERIVED_LOGICAL_PATH


def run_bigbang_historical_processing(
    archive_dir: Path,
    canonical_root: Path,
    derived_root: Path,
    report_path: Path,
    *,
    metric_specs: Mapping[str, RasterMetricSpec] = METRIC_SPECS,
) -> dict:
    versions, inventory = inspect_canonical_territories(canonical_root)
    plan = build_bigbang_historical_processing_plan(versions)
    supported = [entry for entry in plan if entry.process_provinces]
    if not supported:
        raise ValueError("BIGBANG historical policy produced no supported provincial years")

    official_path = canonical_root / f"water/dataset_version={SOURCE['dataset_version']}/observations.parquet"
    official_sha256_before = sha256_file(official_path)
    official = pd.read_parquet(official_path)
    records: list[pd.DataFrame] = []
    metric_reports = {
        symbol: {
            "officialMetricId": spec.official_metric_id,
            "derivedMetricId": spec.derived_metric_id,
            "unitUcum": spec.unit_ucum,
            "years": {},
        }
        for symbol, spec in metric_specs.items()
    }

    with tempfile.TemporaryDirectory(prefix="stato-italia-bigbang-historical-") as workdir:
        work_root = Path(workdir)
        archives = {}
        for symbol, base_spec in metric_specs.items():
            archive = archive_dir / str(base_spec.contract["archive_name"])
            validate_archive_structure(archive, base_spec)
            archives[symbol] = archive
        for entry in supported:
            assert entry.territory_reference_date is not None
            assert entry.geometry_reference is not None
            reference_year = entry.reference_year
            provinces = load_bound_territories(
                canonical_root,
                territory_level="province",
                territory_reference_date=entry.territory_reference_date,
                geometry_reference=entry.geometry_reference,
            )
            regional_version = _exact_geometry_version(versions, reference_year, "region")
            regions = None
            if regional_version is not None:
                regions = load_bound_territories(
                    canonical_root,
                    territory_level="region",
                    territory_reference_date=regional_version.territory_reference_date,
                    geometry_reference=regional_version.geometry_reference,
                )
            prepared_provinces = None
            prepared_regions = None
            for symbol, base_spec in metric_specs.items():
                spec = replace(base_spec, reference_year=reference_year)
                raster = extract_raster(
                    archives[symbol],
                    work_root / symbol.lower() / str(reference_year),
                    spec,
                    reference_year,
                    validate_archive=False,
                )
                metadata = inspect_raster(raster, archives[symbol], spec, reference_year)
                if prepared_provinces is None:
                    prepared_provinces = prepare_territories_for_zonal(raster, provinces)
                    if regions is not None:
                        prepared_regions = prepare_territories_for_zonal(raster, regions)
                regional_report: dict
                if regional_version is None or regions is None:
                    regional_report = {
                        "status": "not_executable_missing_exact_geometry",
                        "reason": "No exact canonical regional geometry exists for this year.",
                    }
                else:
                    assert prepared_regions is not None
                    derived_regions = derive_prepared_territories(
                        raster,
                        regions,
                        "region",
                        metadata,
                        spec,
                        prepared_regions,
                        regional_version.territory_reference_date,
                        regional_version.geometry_reference,
                    )
                    comparison, summary = compare_official_regions(derived_regions, official, spec)
                    if (derived_regions["coverage_ratio"] <= 0).any():
                        raise ValueError(f"Regional validation found empty {symbol}/{reference_year} raster coverage")
                    _reject_structural_regional_mismatch(comparison, symbol, reference_year)
                    regional_report = {
                        "status": "executed",
                        "regionCount": int(len(comparison)),
                        "comparison": comparison.to_dict("records"),
                        "summary": summary,
                    }

                assert prepared_provinces is not None
                derived_provinces = derive_prepared_territories(
                    raster,
                    provinces,
                    "province",
                    metadata,
                    spec,
                    prepared_provinces,
                    entry.territory_reference_date,
                    entry.geometry_reference,
                )
                if derived_provinces["value_decimal"].isna().any():
                    raise ValueError(f"Provincial {symbol}/{reference_year} derivation contains empty values")
                records.append(derived_provinces)
                metric_reports[symbol]["years"][str(reference_year)] = {
                    "referenceYear": reference_year,
                    "provinceGeometryReference": entry.geometry_reference,
                    "provinceRecordCount": int(len(derived_provinces)),
                    "provinceCoverageSummary": _coverage_summary(derived_provinces),
                    "raster": asdict(metadata),
                    "regionalValidation": regional_report,
                }

    output = pd.concat(records, ignore_index=True)
    semantic_key = ["derived_metric_id", "reference_year", "territory_version_id"]
    if output.duplicated(semantic_key).any():
        raise ValueError("Historical BIGBANG derived observations duplicate their semantic key")
    if output["derived_observation_id"].duplicated().any():
        raise ValueError("Historical BIGBANG derived observation IDs collide")
    if set(output["official_status"]) != {"derived_by_stato_italia"}:
        raise ValueError("Historical BIGBANG observations have an unexpected official status")
    destination = _historical_destination(derived_root)
    _write_parquet_atomic(output, destination)
    official_sha256_after = sha256_file(official_path)
    if official_sha256_after != official_sha256_before:
        raise ValueError("Official BIGBANG canonical changed during historical derived processing")

    report = {
        "schemaVersion": 1,
        "processing": "BIGBANG historical provincial area-weighted zonal mean",
        "algorithmVersion": ALGORITHM_VERSION,
        "policy": "bigbang-historical-territory-support-v1",
        "territoryInventory": [asdict(entry) for entry in inventory],
        "processingPlan": [entry.to_dict() for entry in plan],
        "supportedProvinceYears": [entry.reference_year for entry in supported],
        "excludedProvinceYears": [entry.to_dict() for entry in plan if not entry.process_provinces],
        "metricsProcessed": list(metric_specs),
        "derivedArtifact": str(destination),
        "derivedProvinceRecords": int(len(output)),
        "overallProvinceCoverage": _coverage_summary(output),
        "officialCanonical": {
            "path": str(official_path),
            "sha256Before": official_sha256_before,
            "sha256After": official_sha256_after,
            "unchanged": True,
        },
        "metrics": metric_reports,
    }
    json_dump(report_path, report)
    return report


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Process BIGBANG historical rasters for policy-supported provinces")
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--canonical-root", type=Path, default=Path("data/canonical"))
    parser.add_argument("--derived-root", type=Path, default=Path("data/derived"))
    parser.add_argument("--report", type=Path, default=Path("artifacts/reports/bigbang-historical-processing.json"))
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = run_bigbang_historical_processing(
        args.archive_dir, args.canonical_root, args.derived_root, args.report,
    )
    print(json.dumps({
        "supportedProvinceYears": report["supportedProvinceYears"],
        "derivedProvinceRecords": report["derivedProvinceRecords"],
        "derivedArtifact": report["derivedArtifact"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
