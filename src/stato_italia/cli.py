from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from .analytics import build_soil_analytics
from .common import json_dump, now_iso
from .delivery import generate_soil_delivery
from .emissions import fetch_emissions, ingest_emissions
from .emissions_delivery import generate_emissions_delivery
from .emissions_national import fetch_national_emissions, ingest_national_emissions
from .forests import ZONAL_ALGORITHM_VERSION, fetch_forests, ingest_forests, ingest_infc_forests
from .forests_delivery import generate_forests_delivery
from .ingestion_plan import (
    PLAN_SCHEMA_VERSION,
    active_ingestion_plan,
    catalog_changed as planned_catalog_changed,
    clear_ingestion_plan,
    load_ingestion_plan,
    planned_entries,
    source_family_changed,
)
from .dissesto import fetch_dissesto, ingest_dissesto
from .dissesto_delivery import generate_dissesto_delivery
from .release import CarriedArtifact, LocalObjectStore, R2ObjectStore, ReleaseArtifact, active_release, active_source_state, artifact_scope, carry_forward_active_artifacts, hydrate_active_artifact, publish_release, rollback
from .source_state import SOURCE_STATE_LOGICAL_PATH, build_source_state_from_metadata_paths, changed_source_entries, check_persisted_sources, merge_source_families, merge_source_states, scoped_source_state, source_family, source_state_changed, source_state_counts, source_state_entry
from .soil import ingest_soil
from .territories import SOURCE_YEARS, ingest_boundaries
from .water import ingest_water
from .water_delivery import generate_water_delivery
from .tiles import build_pmtiles, is_readable_pmtiles
from .territory_insights_delivery import generate_territory_insights_delivery


def load_local_env(path: Path = Path(".env")) -> None:
    """Load a local, ignored dotenv file without replacing real process secrets."""
    if not path.exists():
        return
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            raise ValueError(f"Invalid .env line {number}: expected KEY=VALUE")
        key, value = (part.strip() for part in line.split("=", 1))
        if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
            raise ValueError(f"Invalid .env key on line {number}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _release_id() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ") + "-local"


def _bytes_under(root: Path, suffixes: tuple[str, ...] | None = None) -> int:
    return sum(
        path.stat().st_size for path in root.rglob("*")
        if path.is_file() and (suffixes is None or path.suffix in suffixes)
    )


def _existing_artifacts(paths: list[Path], root: Path) -> list[ReleaseArtifact]:
    """Keep release membership explicit; silently missing declared output is a contract error."""
    artifacts: list[ReleaseArtifact] = []
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"Declared release artifact missing: {path}")
        artifacts.append(ReleaseArtifact(path, str(path.relative_to(root))))
    return artifacts


def _declared_raw_paths(value: object) -> list[Path]:
    """Collect only adapter-returned raw and metadata paths, not raw directory contents."""
    paths: set[Path] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"local_path", "metadata_path"} and isinstance(item, str):
                paths.add(Path(item))
            elif key == "raw_files" and isinstance(item, list):
                paths.update(Path(path) for path in item if isinstance(path, str))
            else:
                paths.update(_declared_raw_paths(item))
    elif isinstance(value, list):
        for item in value:
            paths.update(_declared_raw_paths(item))
    return sorted(paths)


def _release_artifacts(root: Path, declared_paths: list[Path], source_state_path: Path) -> list[ReleaseArtifact]:
    """Release membership comes only from phase declarations."""
    artifacts = [*_existing_artifacts(declared_paths, root), ReleaseArtifact(source_state_path, SOURCE_STATE_LOGICAL_PATH)]
    logical_paths = [artifact.logical_path for artifact in artifacts]
    if len(logical_paths) != len(set(logical_paths)):
        raise ValueError("Pipeline declared duplicate release artifact paths")
    return sorted(artifacts, key=lambda artifact: artifact.logical_path)


def _territory_paths(canonical: Path) -> list[Path]:
    return [canonical / "territories" / f"reference_year={year}" / f"{level}.parquet" for year in SOURCE_YEARS for level in ("municipality", "province", "region")]


def _hydrate(store: LocalObjectStore | R2ObjectStore, root: Path, logical_paths: list[str]) -> None:
    for logical_path in logical_paths:
        hydrate_active_artifact(store, logical_path, root / logical_path)


def _changed_source_families() -> set[str]:
    families = {
        source_family(str(entry["source_id"]))
        for entry in planned_entries()
        if entry.get("status") == "changed"
    }
    if planned_catalog_changed():
        families.add("copernicus")
    return families


def _hydrate_planned_raw_dependencies(
    store: LocalObjectStore | R2ObjectStore, root: Path, families: set[str],
) -> None:
    """Hydrate only unchanged raw assets consumed by changed-family adapters."""
    logical_paths: list[str] = []
    for entry in planned_entries():
        if source_family(str(entry["source_id"])) not in families or entry.get("status") == "changed":
            continue
        raw = f"raw/{entry['asset_path']}"
        logical_paths.extend((raw, f"{raw}.metadata.json"))
    _hydrate(store, root, sorted(set(logical_paths)))


def _planned_noop_report(
    args: argparse.Namespace, store: LocalObjectStore | R2ObjectStore, *, started: float, started_at: str,
) -> int:
    plan = active_ingestion_plan() or {}
    manifest = store.read_json("manifest.json")
    report = {
        "run_id": manifest["releaseId"], "status": "noop", "changed": False, "scope": args.scope,
        "operationalMetrics": {
            "sourceChecks": int(plan.get("sourceChecks", 0)),
            "sourcesChanged": int(plan.get("sourcesChanged", 0)),
            "sourcesUnchanged": int(plan.get("sourcesUnchanged", 0)),
            "sourcesUnverifiable": int(plan.get("sourcesUnverifiable", 0)),
            "rawBytesAcquired": 0, "objectsUploaded": 0, "bytesUploadedToR2": 0,
            "pipelineDurationSeconds": round(time.monotonic() - started, 3),
        },
        "manifest": manifest, "startedAt": started_at, "completedAt": now_iso(),
    }
    json_dump(Path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _active_source_state_with_legacy_bootstrap(store: LocalObjectStore | R2ObjectStore) -> dict | None:
    """Migrate one legacy active release by reading its immutable raw provenance."""
    persisted = active_source_state(store, SOURCE_STATE_LOGICAL_PATH)
    if persisted is not None:
        return persisted
    release = active_release(store)
    if release is None:
        return None
    objects = {str(item["logicalPath"]): item for item in release.get("objects", [])}
    entries = []
    for logical_path, item in sorted(objects.items()):
        if not logical_path.startswith("raw/") or not logical_path.endswith(".metadata.json"):
            continue
        raw_logical = logical_path.removesuffix(".metadata.json")
        if raw_logical not in objects:
            raise ValueError(f"Legacy active release metadata lacks raw artifact: {raw_logical}")
        metadata = store.read_json(str(item["key"]))
        if not isinstance(metadata, dict) or not isinstance(metadata.get("source_id"), str):
            raise ValueError(f"Invalid legacy active raw metadata: {logical_path}")
        entries.append(source_state_entry(metadata, raw_logical.removeprefix("raw/")))
    for logical_path, item in sorted(objects.items()):
        if not logical_path.startswith("raw/copernicus-") or not logical_path.endswith("/catalog.json"):
            continue
        payload = store.read_json(str(item["key"]))
        if not isinstance(payload.get("source_id"), str) or not isinstance(payload.get("signature"), str):
            raise ValueError(f"Invalid legacy Copernicus catalog: {logical_path}")
        entries.append({
            "source_id": payload["source_id"], "asset_path": logical_path.removeprefix("raw/"),
            "resolved_url": None, "etag": None, "last_modified": None,
            "sha256": payload["signature"], "bytes": int(item["bytes"]),
            "dataset_version": None, "period": None, "checked_at": payload.get("checked_at"), "kind": "catalog",
        })
    if not entries:
        return None
    entries.sort(key=lambda entry: entry["asset_path"])
    return {"schemaVersion": 1, "sources": entries}


def _catalog_changed_from_active(previous_state: dict | None, forest_fetch: dict) -> bool:
    signature = forest_fetch.get("catalog", {}).get("signature")
    if not isinstance(signature, str):
        return False
    previous = next((
        entry for entry in (previous_state or {}).get("sources", [])
        if entry.get("kind") == "catalog" and entry.get("source_id", entry.get("sourceId")) == "copernicus-hrl-forests"
    ), None)
    return previous is None or previous.get("sha256") != signature


def _active_infc_logical_paths(previous_state: dict | None) -> list[str]:
    """Resolve reusable INFC raw objects without changing their source identity."""
    logical_paths: list[str] = []
    for entry in (previous_state or {}).get("sources", []):
        source_id = entry.get("source_id", entry.get("sourceId"))
        if source_id != "infc-2015-forests":
            continue
        asset_path = entry.get("asset_path", entry.get("assetPath"))
        if not isinstance(asset_path, str):
            raise ValueError("Persisted INFC source-state lacks asset path")
        raw_path = f"raw/{asset_path}"
        logical_paths.extend((raw_path, f"{raw_path}.metadata.json"))
    return logical_paths


def _reused_canonical(path: Path, *, mode: str) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Active release canonical dependency is missing: {path}")
    return {
        "changed": False,
        "records": len(pd.read_parquet(path)),
        "canonical_bytes": path.stat().st_size,
        "mode": mode,
    }


def _validate_data_canonical_provenance(
    root: Path, source_state: dict, logical_paths: set[str], affected_families: set[str] | None = None,
) -> None:
    provenance_contracts = (
        ("soil", "canonical/soil/dataset_version=2025-2024-observations/observations.parquet", "ispra-soil-2025", None),
        ("water", "canonical/water/dataset_version=bigbang-10-1951-2025/observations.parquet", "ispra-bigbang-10", None),
        ("dissesto", "canonical/dissesto/dataset_version=idrogeo-risk-2024/observations.parquet", "ispra-idrogeo-risk-2024", "idrogeo-risk-api-responses.zip"),
        ("emissions", "canonical/emissions/dataset_version=2026-2023-disaggregation/observations.parquet", "ispra-emissions-provincial-2026", None),
        ("emissions", "canonical/emissions/national/greenhouse-gases/dataset_version=2026-1990-2024/observations.parquet", "ispra-emissions-ghg-2026", None),
        ("emissions", "canonical/emissions/national/air-pollutants-nfr/dataset_version=2026-1990-2024/observations.parquet", "ispra-emissions-nfr-2026", None),
    )
    for family, logical_path, source_id, asset_name in provenance_contracts:
        if affected_families is not None and family not in affected_families:
            continue
        if logical_path not in logical_paths:
            raise ValueError(f"Data release lacks canonical artifact: {logical_path}")
        expected_hashes = {
            str(entry["sha256"]) for entry in source_state["sources"]
            if entry.get("source_id") == source_id
            and (asset_name is None or str(entry.get("asset_path", "")).endswith(f"/{asset_name}"))
        }
        table = pd.read_parquet(root / logical_path, columns=["source_asset_sha256"])
        canonical_hashes = set(table["source_asset_sha256"].dropna().astype(str))
        if not expected_hashes or canonical_hashes != expected_hashes:
            raise ValueError(f"Source-state and canonical provenance differ: {logical_path}")


def _validate_infc_canonical_provenance(root: Path, source_state: dict, logical_paths: set[str]) -> None:
    logical_path = "canonical/forests/dataset_version=infc2015-published-tables/observations.parquet"
    if logical_path not in logical_paths:
        raise ValueError(f"Geospatial release lacks INFC canonical artifact: {logical_path}")
    expected_hashes = {
        str(entry["sha256"])
        for entry in source_state["sources"]
        if entry.get("source_id", entry.get("sourceId")) == "infc-2015-forests"
    }
    table = pd.read_parquet(root / logical_path, columns=["source_asset_sha256"])
    canonical_hashes = set(table["source_asset_sha256"].dropna().astype(str))
    if not expected_hashes or canonical_hashes != expected_hashes:
        raise ValueError(f"Source-state and canonical provenance differ: {logical_path}")


def _validate_release_coherence(
    root: Path, source_state: dict, artifacts: list[ReleaseArtifact | CarriedArtifact], *, scope: str,
    affected_families: set[str] | None = None,
) -> None:
    """Fail before upload when provenance, scope ownership, or Copernicus canonical diverge."""
    logical_paths = {item.logical_path for item in artifacts}
    for item in artifacts:
        artifact_scope(item.logical_path)
    for entry in source_state["sources"]:
        raw_path = f"raw/{entry['asset_path']}"
        if raw_path not in logical_paths:
            raise ValueError(f"Release source-state lacks declared raw artifact: {raw_path}")
        if entry.get("kind") != "catalog" and f"{raw_path}.metadata.json" not in logical_paths:
            raise ValueError(f"Release source-state lacks raw provenance sidecar: {raw_path}.metadata.json")
    required_shared = {
        str(path.relative_to(root))
        for path in _territory_paths(root / "canonical")
    }
    missing_shared = required_shared - logical_paths
    if missing_shared:
        raise ValueError(f"Release lacks shared territory canonical artifacts: {sorted(missing_shared)}")
    _validate_data_canonical_provenance(root, source_state, logical_paths, affected_families)
    if scope == "data":
        return
    if affected_families is None or "infc" in affected_families:
        _validate_infc_canonical_provenance(root, source_state, logical_paths)
    if affected_families is not None and "copernicus" not in affected_families:
        return
    catalog = next((entry for entry in source_state["sources"] if entry.get("kind") == "catalog"), None)
    if catalog is None:
        raise ValueError("Geospatial release lacks Copernicus catalog source-state")
    zonal_logical = f"canonical/forests/algorithm_version={ZONAL_ALGORITHM_VERSION}/zonal_statistics.parquet"
    if zonal_logical not in logical_paths:
        raise ValueError("Geospatial release lacks forest zonal canonical")
    if os.getenv("FOREST_PROCESSING_MODE", "raster") == "statistical-api":
        table = pd.read_parquet(root / zonal_logical, columns=["source_asset_sha256"])
        hashes = set(table["source_asset_sha256"].dropna().astype(str))
        if hashes != {catalog["sha256"]}:
            raise ValueError("Copernicus source-state and forest canonical signatures differ")


def _publish_scoped(
    *, store: LocalObjectStore | R2ObjectStore, root: Path, output: Path, release_id: str,
    scope: str, previous_state: dict | None, current_state: dict, declared_paths: list[Path], changed: bool,
    affected_families: set[str] | None = None,
) -> tuple[dict, dict, dict]:
    source_state = (
        merge_source_families(
            previous_state, current_state, scope=scope,
            replace_families={family for family in (affected_families or set()) if family in {"boundaries", "soil", "water", "dissesto", "emissions", "infc", "copernicus"}},
        )
        if affected_families is not None
        else merge_source_states(previous_state, current_state, scope=scope)
    )
    state_changed = source_state_changed(previous_state, source_state)
    previous_scope = scoped_source_state(previous_state, scope)
    source_counts = source_state_counts(previous_scope, current_state)
    changed_sources = changed_source_entries(previous_scope, current_state)
    changed = changed or state_changed
    state_path = output / "release-metadata" / f"{release_id}-source-state.json"
    json_dump(state_path, source_state)
    fresh = _release_artifacts(root, declared_paths, state_path)
    carried: list[CarriedArtifact] = carry_forward_active_artifacts(
        store, {item.logical_path for item in fresh}, scope=scope, affected_families=affected_families,
    )
    _validate_release_coherence(
        root, source_state, [*fresh, *carried], scope=scope, affected_families=affected_families,
    )
    manifest = publish_release(store, release_id, [*fresh, *carried]) if changed else store.read_json("manifest.json")
    carried_sources = len(source_state["sources"]) - len(current_state["sources"])
    plan = active_ingestion_plan()
    plan_metrics = plan if plan and plan.get("scope") == scope else None
    metrics = {
        "sourceChecks": int(plan_metrics["sourceChecks"]) if plan_metrics else source_counts["checked"],
        "sourcesChanged": int(plan_metrics["sourcesChanged"]) if plan_metrics else source_counts["changed"],
        "sourcesUnchanged": int(plan_metrics["sourcesUnchanged"]) if plan_metrics else source_counts["unchanged"],
        "sourcesUnverifiable": int(plan_metrics.get("sourcesUnverifiable", 0)) if plan_metrics else 0,
        "rawBytesAcquired": sum(entry["bytes"] for entry in changed_sources),
        "objectsUploaded": manifest.get("publishMetrics", {}).get("objectsUploaded", 0),
        "objectsReused": manifest.get("publishMetrics", {}).get("objectsReused", 0),
        "bytesUploadedToR2": manifest.get("publishMetrics", {}).get("bytesUploaded", 0),
        "releaseReferencedBytes": manifest.get("publishMetrics", {}).get("releaseReferencedBytes", sum(item["bytes"] for item in (active_release(store) or {}).get("objects", []))),
        "totalSourcesInRelease": len(source_state["sources"]), "carriedSources": carried_sources,
        "carriedArtifacts": len(carried),
    }
    return manifest, metrics, {"changed": changed, "source_state": source_state, "carried": len(carried)}


def _process_geospatial_forest_sources(
    args: argparse.Namespace, *, root: Path, canonical: Path, previous_state: dict | None,
) -> tuple[dict, dict, dict]:
    """Acquire and rebuild only the changed Forest source family."""
    plan = active_ingestion_plan()
    infc_changed = source_family_changed("infc-2015-forests")
    copernicus_changed = source_family_changed("copernicus-") or planned_catalog_changed()
    process_infc = plan is None or infc_changed or args.force
    process_copernicus = plan is None or copernicus_changed or args.force
    forest_fetch = fetch_forests(
        root,
        offline=args.offline,
        include_infc=process_infc,
        check_geospatial=plan is None or copernicus_changed,
    )
    infc_path = canonical / "forests" / "dataset_version=infc2015-published-tables" / "observations.parquet"
    zonal_path = canonical / "forests" / f"algorithm_version={ZONAL_ALGORITHM_VERSION}" / "zonal_statistics.parquet"
    infc = (
        ingest_infc_forests(root, canonical, force=args.force or infc_changed)
        if process_infc
        else _reused_canonical(infc_path, mode="active_release")
    )
    catalog_was_changed = _catalog_changed_from_active(previous_state, forest_fetch)
    zonal = (
        ingest_forests(
            root, canonical, force=args.force or catalog_was_changed,
            mode=os.getenv("FOREST_PROCESSING_MODE", "raster"),
        )
        if process_copernicus
        else _reused_canonical(zonal_path, mode="active_release")
    )
    return forest_fetch, infc, zonal


def _run_geospatial(args: argparse.Namespace, *, root: Path, output: Path, canonical: Path, delivery: Path, store: LocalObjectStore | R2ObjectStore, previous_state: dict | None, release_id: str, started: float, started_at: str) -> int:
    plan = active_ingestion_plan()
    families = _changed_source_families()
    if plan is None:
        families = {"infc", "copernicus"}
        _hydrate(store, root, _active_infc_logical_paths(previous_state))
    if args.force:
        families = {"infc", "copernicus"}
    _hydrate(store, root, _territory_logical_paths((2015, 2023)))
    if "infc" in families:
        _hydrate_planned_raw_dependencies(store, root, {"infc"})
    infc_logical = "canonical/forests/dataset_version=infc2015-published-tables/observations.parquet"
    zonal_logical = f"canonical/forests/algorithm_version={ZONAL_ALGORITHM_VERSION}/zonal_statistics.parquet"
    if "infc" not in families:
        _hydrate(store, root, [infc_logical])
    if "copernicus" not in families:
        _hydrate(store, root, [zonal_logical])
    forest_fetch, infc, zonal = _process_geospatial_forest_sources(
        args, root=root, canonical=canonical, previous_state=previous_state,
    )
    forests_pmtiles = {
        **{
            level: {"path": str(delivery / "foreste/geometry" / f"istat-{level}-2023.pmtiles"), "carried": True}
            for level in ("municipality", "province", "region")
        },
        "region_2015": {"path": str(delivery / "foreste/geometry/istat-region-2015.pmtiles"), "carried": True},
    }
    forest_delivery = generate_forests_delivery(
        root / zonal_logical, root / infc_logical, canonical, delivery, release_id,
        {level: Path(info["path"]) for level, info in forests_pmtiles.items()},
        force=True,
    )
    insights = {"changed": False, "files": [], "carried": True}
    if "copernicus" in families:
        _hydrate(store, root, [
            "canonical/soil/dataset_version=2025-2024-observations/observations.parquet",
            "canonical/water/dataset_version=bigbang-10-1951-2025/observations.parquet",
            "canonical/dissesto/dataset_version=idrogeo-risk-2024/observations.parquet",
            "canonical/emissions/dataset_version=2026-2023-disaggregation/observations.parquet",
            *_territory_logical_paths((2025,)),
        ])
        insights = generate_territory_insights_delivery(
            canonical / "soil/dataset_version=2025-2024-observations/observations.parquet",
            root / zonal_logical,
            canonical / "water/dataset_version=bigbang-10-1951-2025/observations.parquet",
            canonical / "dissesto/dataset_version=idrogeo-risk-2024/observations.parquet",
            canonical / "emissions/dataset_version=2026-2023-disaggregation/observations.parquet",
            canonical, delivery, release_id, force=True,
        )
    fetched_raw_paths = _declared_raw_paths(forest_fetch)
    catalog_value = forest_fetch.get("catalog", {}).get("path")
    catalog_path = Path(catalog_value) if isinstance(catalog_value, str) else None
    raw_paths = sorted(set(fetched_raw_paths) | ({catalog_path} if catalog_path else set()))
    metadata_paths = [path for path in raw_paths if path.name.endswith(".metadata.json")]
    current_state = build_source_state_from_metadata_paths(
        root / "raw", metadata_paths, include_catalog=catalog_path,
    )
    declared = [*raw_paths, *forest_delivery.get("files", []), *insights.get("files", [])]
    if "infc" in families:
        declared.append(root / infc_logical)
    if "copernicus" in families:
        declared.append(root / zonal_logical)
    affected_artifacts = {*families, "forest_delivery"}
    if "copernicus" in families:
        affected_artifacts.add("territory_insights")
    manifest, metrics, publication = _publish_scoped(
        store=store, root=root, output=output, release_id=release_id, scope="geospatial", previous_state=previous_state,
        current_state=current_state, declared_paths=declared,
        changed=infc["changed"] or zonal["changed"] or forest_delivery["changed"] or insights["changed"],
        affected_families=affected_artifacts,
    )
    report = {"run_id": manifest["releaseId"], "status": "success" if publication["changed"] else "noop", "changed": publication["changed"], "scope": "geospatial", "forests": {"fetch": forest_fetch, "infc": infc, "zonal": zonal}, "operationalMetrics": metrics | {"canonicalBytesGenerated": sum(item.get("canonical_bytes", 0) for item in (infc, zonal) if item["changed"]), "derivedBytesGenerated": 0, "deliveryBytesGenerated": sum(item.get("bytes", 0) for item in (forest_delivery, insights) if item.get("changed")), "pipelineDurationSeconds": round(time.monotonic() - started, 3)}, "manifest": manifest, "carriedArtifacts": publication["carried"], "startedAt": started_at, "completedAt": now_iso()}
    json_dump(Path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _data_scope_forests(canonical: Path) -> dict:
    """Expose carried Copernicus canonical as a read-only shared-delivery input."""
    zonal_path = canonical / "forests" / f"algorithm_version={ZONAL_ALGORITHM_VERSION}" / "zonal_statistics.parquet"
    if not zonal_path.exists():
        raise RuntimeError("Data scope requires active geospatial forest canonical; run ingest-geospatial first")
    return {
        "fetch": {"status": "out_of_scope", "scope": "geospatial"},
        "zonal": {"changed": False, "canonical_bytes": zonal_path.stat().st_size, "mode": "carried_forward"},
    }


def _territory_logical_paths(years: Iterable[int]) -> list[str]:
    return [
        f"canonical/territories/reference_year={year}/{level}.parquet"
        for year in years for level in ("municipality", "province", "region")
    ]


def _data_geometry_logical_paths() -> dict[str, list[str]]:
    return {
        "soil": [f"delivery/soil/geometry/istat-{level}-2025.pmtiles" for level in ("municipality", "province", "region")],
        "dissesto": [f"delivery/dissesto/geometry/istat-{level}-2024.pmtiles" for level in ("municipality", "province", "region")],
        "emissions": [f"delivery/emissions/geometry/istat-province-{year}.pmtiles" for year in (2019, 2023)],
    }


def _run_incremental_data(
    args: argparse.Namespace, *, root: Path, output: Path, canonical: Path, derived: Path, delivery: Path,
    store: LocalObjectStore | R2ObjectStore, previous_state: dict | None, release_id: str,
    started: float, started_at: str,
) -> int:
    families = _changed_source_families()
    if args.force:
        families = {"boundaries", "soil", "water", "dissesto", "emissions"}
    _hydrate_planned_raw_dependencies(store, root, families)

    territory_years: set[int] = set(SOURCE_YEARS) if "boundaries" in families else set()
    if "soil" in families or "water" in families:
        territory_years.add(2025)
    if "dissesto" in families:
        territory_years.add(2024)
    if "emissions" in families:
        territory_years.update((2019, 2023))
    if territory_years:
        _hydrate(store, root, _territory_logical_paths(sorted(territory_years)))

    boundaries = ingest_boundaries(root, canonical, SOURCE_YEARS, force=args.force, offline=args.offline) if "boundaries" in families else {"changed": False, "years": [], "carried": True}
    soil = ingest_soil(root, canonical, force=args.force, offline=args.offline) if "soil" in families else {"changed": False, "carried": True}
    water = ingest_water(root, canonical, force=args.force, offline=args.offline) if "water" in families else {"changed": False, "carried": True}
    national_emissions = ingest_national_emissions(root, canonical, force=args.force, offline=args.offline) if "emissions" in families else {"changed": False, "carried": True}
    provincial_emissions = ingest_emissions(root, canonical, force=args.force, offline=args.offline) if "emissions" in families else {"changed": False, "carried": True}
    emissions = {
        "changed": bool(national_emissions["changed"] or provincial_emissions["changed"]),
        "national": national_emissions, "territories": {"provincial": provincial_emissions},
    }
    dissesto_fetch = fetch_dissesto(root) if "dissesto" in families and not args.offline else None
    dissesto = ingest_dissesto(root, canonical, force=args.force) if "dissesto" in families else {"changed": False, "carried": True}
    analytics = (
        build_soil_analytics(
            canonical / "soil/dataset_version=2025-2024-observations/observations.parquet",
            canonical, derived / "soil/algorithm_version=soil-analytics-v1/analytics.parquet",
            force=args.force or bool(soil["changed"]),
        )
        if "soil" in families else {"changed": False, "carried": True}
    )

    geometry_paths = _data_geometry_logical_paths()
    fresh_geometry: list[Path] = []
    geometry_reports: dict[str, dict] = {"soil": {}, "dissesto": {}, "emissions": {}}
    if "boundaries" in families:
        for level in ("municipality", "province", "region"):
            target = delivery / "soil/geometry" / f"istat-{level}-2025.pmtiles"
            geometry_reports["soil"][level] = build_pmtiles(canonical / f"territories/reference_year=2025/{level}.parquet", target)
            fresh_geometry.append(target)
            target = delivery / "dissesto/geometry" / f"istat-{level}-2024.pmtiles"
            geometry_reports["dissesto"][level] = build_pmtiles(canonical / f"territories/reference_year=2024/{level}.parquet", target)
            fresh_geometry.append(target)
        for year in (2019, 2023):
            target = delivery / "emissions/geometry" / f"istat-province-{year}.pmtiles"
            geometry_reports["emissions"][year] = build_pmtiles(canonical / f"territories/reference_year={year}/province.parquet", target)
            fresh_geometry.append(target)
    else:
        for family in families & {"soil", "dissesto", "emissions"}:
            _hydrate(store, root, geometry_paths[family])
        geometry_reports["soil"] = {
            level: {"path": str(root / path)} for level, path in zip(("municipality", "province", "region"), geometry_paths["soil"], strict=True)
        }
        geometry_reports["dissesto"] = {
            level: {"path": str(root / path)} for level, path in zip(("municipality", "province", "region"), geometry_paths["dissesto"], strict=True)
        }
        geometry_reports["emissions"] = {
            year: {"path": str(root / path)} for year, path in zip((2019, 2023), geometry_paths["emissions"], strict=True)
        }

    soil_delivery = generate_soil_delivery(
        canonical / "soil/dataset_version=2025-2024-observations/observations.parquet",
        derived / "soil/algorithm_version=soil-analytics-v1/analytics.parquet", canonical, root, delivery,
        release_id, force=True,
    ) if "soil" in families else {"changed": False, "files": [], "carried": True}
    water_delivery = generate_water_delivery(
        canonical / "water/dataset_version=bigbang-10-1951-2025/observations.parquet", delivery, release_id, force=True,
    ) if "water" in families else {"changed": False, "files": [], "carried": True}
    dissesto_delivery = generate_dissesto_delivery(
        canonical / "dissesto/dataset_version=idrogeo-risk-2024/observations.parquet", delivery, release_id,
        {level: Path(info["path"]) for level, info in geometry_reports["dissesto"].items()}, force=True,
    ) if "dissesto" in families else {"changed": False, "files": [], "carried": True}
    emissions_delivery = generate_emissions_delivery(
        canonical / "emissions/national/greenhouse-gases/dataset_version=2026-1990-2024/observations.parquet",
        canonical / "emissions/national/air-pollutants-nfr/dataset_version=2026-1990-2024/observations.parquet",
        canonical / "emissions/dataset_version=2026-2023-disaggregation/observations.parquet",
        {year: Path(info["path"]) for year, info in geometry_reports["emissions"].items()},
        delivery, release_id, force=True,
    ) if "emissions" in families else {"changed": False, "files": [], "carried": True}

    changed_source_ids = {
        str(entry["source_id"]) for entry in planned_entries() if entry.get("status") == "changed"
    }
    insights_changed = args.force or bool(changed_source_ids & {
        "istat-administrative-boundaries", "ispra-soil-2025", "ispra-bigbang-10",
        "ispra-idrogeo-risk-2024", "ispra-emissions-provincial-2026",
    })
    insights = {"changed": False, "files": [], "carried": True}
    if insights_changed:
        insight_dependencies = []
        for family, logical in (
            ("soil", "canonical/soil/dataset_version=2025-2024-observations/observations.parquet"),
            ("water", "canonical/water/dataset_version=bigbang-10-1951-2025/observations.parquet"),
            ("dissesto", "canonical/dissesto/dataset_version=idrogeo-risk-2024/observations.parquet"),
            ("emissions", "canonical/emissions/dataset_version=2026-2023-disaggregation/observations.parquet"),
        ):
            if family not in families:
                insight_dependencies.append(logical)
        insight_dependencies.append(f"canonical/forests/algorithm_version={ZONAL_ALGORITHM_VERSION}/zonal_statistics.parquet")
        if "boundaries" not in families:
            insight_dependencies.extend(_territory_logical_paths((2025,)))
        _hydrate(store, root, insight_dependencies)
        insights = generate_territory_insights_delivery(
            canonical / "soil/dataset_version=2025-2024-observations/observations.parquet",
            canonical / f"forests/algorithm_version={ZONAL_ALGORITHM_VERSION}/zonal_statistics.parquet",
            canonical / "water/dataset_version=bigbang-10-1951-2025/observations.parquet",
            canonical / "dissesto/dataset_version=idrogeo-risk-2024/observations.parquet",
            canonical / "emissions/dataset_version=2026-2023-disaggregation/observations.parquet",
            canonical, delivery, release_id, force=True,
        )

    raw_declarations = _declared_raw_paths({
        "boundaries": boundaries, "soil": soil, "water": water,
        "national_emissions": national_emissions, "provincial_emissions": provincial_emissions,
        "dissesto": dissesto_fetch,
    })
    metadata_paths = [path for path in raw_declarations if path.name.endswith(".metadata.json")]
    current_state = build_source_state_from_metadata_paths(root / "raw", metadata_paths)
    canonical_by_family = {
        "boundaries": [*_territory_paths(canonical)],
        "soil": [canonical / "soil/dataset_version=2025-2024-observations/observations.parquet", derived / "soil/algorithm_version=soil-analytics-v1/analytics.parquet"],
        "water": [canonical / "water/dataset_version=bigbang-10-1951-2025/observations.parquet"],
        "dissesto": [canonical / "dissesto/dataset_version=idrogeo-risk-2024/observations.parquet"],
        "emissions": [
            canonical / "emissions/dataset_version=2026-2023-disaggregation/observations.parquet",
            canonical / "emissions/national/greenhouse-gases/dataset_version=2026-1990-2024/observations.parquet",
            canonical / "emissions/national/air-pollutants-nfr/dataset_version=2026-1990-2024/observations.parquet",
        ],
    }
    delivery_reports = [soil_delivery, water_delivery, dissesto_delivery, emissions_delivery, insights]
    declared = [
        *raw_declarations,
        *[path for family in families for path in canonical_by_family[family]],
        *fresh_geometry,
        *[path for report in delivery_reports for path in report.get("files", [])],
    ]
    affected_artifacts = set(families)
    if "boundaries" in families:
        affected_artifacts.add("data_geometry")
    if insights_changed:
        affected_artifacts.add("territory_insights")
    manifest, metrics, publication = _publish_scoped(
        store=store, root=root, output=output, release_id=release_id, scope="data",
        previous_state=previous_state, current_state=current_state, declared_paths=declared,
        changed=any(report.get("changed", False) for report in [boundaries, soil, water, emissions, dissesto, analytics, *delivery_reports]),
        affected_families=affected_artifacts,
    )
    report = {
        "run_id": manifest["releaseId"], "status": "success" if publication["changed"] else "noop",
        "changed": publication["changed"], "scope": "data", "affectedFamilies": sorted(affected_artifacts),
        "boundaries": boundaries, "soil": soil, "water": water, "emissions": emissions,
        "dissesto": dissesto, "analytics": analytics, "territory_insights_delivery": insights,
        "operationalMetrics": metrics | {"pipelineDurationSeconds": round(time.monotonic() - started, 3)},
        "manifest": manifest, "carriedArtifacts": publication["carried"],
        "startedAt": started_at, "completedAt": now_iso(),
    }
    json_dump(Path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _run_combined_scope_forests(
    args: argparse.Namespace, root: Path, canonical: Path, previous_source_state: dict | None,
) -> dict:
    """Run Forest only when the combined pipeline owns the geospatial scope."""
    if args.scope == "data":
        return _data_scope_forests(canonical)
    forest_fetch = fetch_forests(root, offline=args.offline)
    forests: dict = {"fetch": forest_fetch}
    infc_raw = root / "raw" / "infc-2015-forests" / "volume.zip"
    if not infc_raw.exists():
        return forests
    forests["infc"] = ingest_infc_forests(root, canonical, force=args.force)
    mode = os.getenv("FOREST_PROCESSING_MODE", "raster")
    zonal_raw = any(
        path
        for source in ("copernicus-hrl-forests", "copernicus-corine-forests")
        for path in (root / "raw" / source).glob("**/*.tif")
    )
    catalog_changed = _catalog_changed_from_active(previous_source_state, forest_fetch)
    if mode == "statistical-api" and forest_fetch.get("catalog", {}).get("status") != "blocked":
        forests["zonal"] = ingest_forests(root, canonical, force=args.force or catalog_changed, mode=mode)
    elif zonal_raw:
        forests["zonal"] = ingest_forests(root, canonical, force=args.force, mode="raster")
    return forests


def run(args: argparse.Namespace) -> int:
    clear_ingestion_plan()
    started = time.monotonic()
    started_at = now_iso()
    root = Path(args.workdir)
    output = Path(args.output)
    canonical = root / "canonical"
    derived = root / "derived"
    delivery = root / "delivery"
    release_id = args.release_id or _release_id()
    store = R2ObjectStore() if args.publish == "r2" else LocalObjectStore(output / "object-store")
    previous_source_state = _active_source_state_with_legacy_bootstrap(store)
    plan_path = getattr(args, "plan", None)
    if plan_path:
        if args.scope == "all":
            raise ValueError("Incremental ingestion plans are supported only for scoped runs")
        release = active_release(store)
        if release is None:
            raise FileNotFoundError("Incremental ingestion plan requires an active release")
        load_ingestion_plan(
            Path(plan_path), scope=args.scope, active_release_id=str(release["releaseId"]), raw_root=root / "raw",
        )
        if not active_ingestion_plan().get("changed") and not args.force:
            return _planned_noop_report(args, store, started=started, started_at=started_at)
    if args.scope == "geospatial":
        return _run_geospatial(
            args, root=root, output=output, canonical=canonical, delivery=delivery, store=store,
            previous_state=previous_source_state, release_id=release_id, started=started, started_at=started_at,
        )
    if args.scope == "data" and plan_path:
        return _run_incremental_data(
            args, root=root, output=output, canonical=canonical, derived=derived, delivery=delivery,
            store=store, previous_state=previous_source_state, release_id=release_id,
            started=started, started_at=started_at,
        )
    if args.scope == "data":
        _hydrate(store, root, [f"canonical/forests/algorithm_version={ZONAL_ALGORITHM_VERSION}/zonal_statistics.parquet"])
    boundaries = ingest_boundaries(root, canonical, SOURCE_YEARS, force=args.force, offline=args.offline)
    soil = ingest_soil(root, canonical, force=args.force, offline=args.offline)
    water = ingest_water(root, canonical, force=args.force, offline=args.offline)
    national_emissions = ingest_national_emissions(root, canonical, force=args.force, offline=args.offline)
    provincial_emissions = ingest_emissions(root, canonical, force=args.force, offline=args.offline)
    emissions = {
        "changed": national_emissions["changed"] or provincial_emissions["changed"],
        "national": national_emissions,
        "territories": {"provincial": provincial_emissions},
    }
    dissesto_fetch = None if args.offline else fetch_dissesto(root)
    dissesto = ingest_dissesto(root, canonical, force=args.force)
    analytics = build_soil_analytics(
        canonical / "soil" / "dataset_version=2025-2024-observations" / "observations.parquet",
        canonical,
        derived / "soil" / "algorithm_version=soil-analytics-v1" / "analytics.parquet",
        force=args.force or soil["changed"],
    )
    forests = _run_combined_scope_forests(args, root, canonical, previous_source_state)
    forest_fetch = forests["fetch"]
    changed = boundaries["changed"] or soil["changed"] or water["changed"] or emissions["changed"] or dissesto["changed"] or bool(dissesto_fetch and dissesto_fetch["changed"]) or analytics["changed"] or bool(forests.get("infc", {}).get("changed")) or bool(forests.get("zonal", {}).get("changed"))
    pmtiles: dict[str, dict] = {}
    for level in ("municipality", "province", "region"):
        pmtiles_path = delivery / "soil" / "geometry" / f"istat-{level}-2025.pmtiles"
        if boundaries["changed"] or not is_readable_pmtiles(pmtiles_path):
            pmtiles[level] = build_pmtiles(canonical / "territories" / "reference_year=2025" / f"{level}.parquet", pmtiles_path)
        else:
            pmtiles[level] = {"path": str(pmtiles_path), "bytes": pmtiles_path.stat().st_size, "skipped": True}
    soil_geometry_changed = any(not info.get("skipped", False) for info in pmtiles.values())
    dissesto_pmtiles: dict[str, dict] = {}
    for level in ("municipality", "province", "region"):
        pmtiles_path = delivery / "dissesto" / "geometry" / f"istat-{level}-2024.pmtiles"
        if dissesto["changed"] or not is_readable_pmtiles(pmtiles_path):
            dissesto_pmtiles[level] = build_pmtiles(canonical / "territories" / "reference_year=2024" / f"{level}.parquet", pmtiles_path)
        else:
            dissesto_pmtiles[level] = {"path": str(pmtiles_path), "bytes": pmtiles_path.stat().st_size, "skipped": True}
    dissesto_geometry_changed = any(not info.get("skipped", False) for info in dissesto_pmtiles.values())
    emissions_pmtiles: dict[int, dict] = {}
    for year in (2019, 2023):
        emissions_pmtiles_path = delivery / "emissions" / "geometry" / f"istat-province-{year}.pmtiles"
        if provincial_emissions["changed"] or not is_readable_pmtiles(emissions_pmtiles_path):
            emissions_pmtiles[year] = build_pmtiles(
                canonical / "territories" / f"reference_year={year}" / "province.parquet",
                emissions_pmtiles_path,
            )
        else:
            emissions_pmtiles[year] = {"path": str(emissions_pmtiles_path), "bytes": emissions_pmtiles_path.stat().st_size, "skipped": True}
    emissions_geometry_changed = any(not info.get("skipped", False) for info in emissions_pmtiles.values())
    forests_pmtiles: dict[str, dict] = {}
    if args.scope != "data" and "zonal" in forests:
        reference_year = 2023
        for level in ("municipality", "province", "region"):
            path = delivery / "foreste" / "geometry" / f"istat-{level}-{reference_year}.pmtiles"
            if boundaries["changed"] or forests["zonal"]["changed"] or not is_readable_pmtiles(path):
                forests_pmtiles[level] = build_pmtiles(canonical / "territories" / f"reference_year={reference_year}" / f"{level}.parquet", path)
            else:
                forests_pmtiles[level] = {"path": str(path), "bytes": path.stat().st_size, "skipped": True}
        # INFC remains a complementary official 2015 regional dataset. Keep its
        # own geometry alongside the 2023 Copernicus slice; delivery maps select
        # the matching one rather than relabelling 2015 values with 2023 borders.
        path = delivery / "foreste" / "geometry" / "istat-region-2015.pmtiles"
        if boundaries["changed"] or not is_readable_pmtiles(path):
            forests_pmtiles["region_2015"] = build_pmtiles(canonical / "territories" / "reference_year=2015" / "region.parquet", path)
        else:
            forests_pmtiles["region_2015"] = {"path": str(path), "bytes": path.stat().st_size, "skipped": True}
    elif args.scope != "data" and "infc" in forests:
        path = delivery / "foreste" / "geometry" / "istat-region-2015.pmtiles"
        if boundaries["changed"] or not is_readable_pmtiles(path):
            forests_pmtiles["region"] = build_pmtiles(canonical / "territories" / "reference_year=2015" / "region.parquet", path)
        else:
            forests_pmtiles["region"] = {"path": str(path), "bytes": path.stat().st_size, "skipped": True}
    forests_geometry_changed = any(not info.get("skipped", False) for info in forests_pmtiles.values())
    delivery_report = generate_soil_delivery(
        canonical / "soil" / "dataset_version=2025-2024-observations" / "observations.parquet",
        derived / "soil" / "algorithm_version=soil-analytics-v1" / "analytics.parquet",
        canonical,
        root,
        delivery,
        release_id,
        force=args.force or boundaries["changed"] or soil["changed"] or analytics["changed"] or soil_geometry_changed,
    )
    water_delivery = generate_water_delivery(
        canonical / "water" / "dataset_version=bigbang-10-1951-2025" / "observations.parquet",
        delivery, release_id, force=args.force or water["changed"],
    )
    dissesto_delivery = generate_dissesto_delivery(
        canonical / "dissesto" / "dataset_version=idrogeo-risk-2024" / "observations.parquet",
        delivery, release_id, {level: Path(info["path"]) for level, info in dissesto_pmtiles.items()},
        force=args.force or dissesto["changed"] or dissesto_geometry_changed,
    )
    emissions_delivery = generate_emissions_delivery(
        canonical / "emissions" / "national" / "greenhouse-gases" / "dataset_version=2026-1990-2024" / "observations.parquet",
        canonical / "emissions" / "national" / "air-pollutants-nfr" / "dataset_version=2026-1990-2024" / "observations.parquet",
        canonical / "emissions" / "dataset_version=2026-2023-disaggregation" / "observations.parquet",
        {year: Path(info["path"]) for year, info in emissions_pmtiles.items()},
        delivery, release_id, force=args.force or emissions["changed"] or emissions_geometry_changed,
    )
    forests_delivery = {"changed": False, "files": []}
    if args.scope != "data" and "infc" in forests:
        forests_delivery = generate_forests_delivery(
            (canonical / "forests" / f"algorithm_version={ZONAL_ALGORITHM_VERSION}" / "zonal_statistics.parquet") if "zonal" in forests else None,
            canonical / "forests" / "dataset_version=infc2015-published-tables" / "observations.parquet", canonical, delivery, release_id,
            {level: Path(info["path"]) for level, info in forests_pmtiles.items()},
            force=args.force or forests["infc"]["changed"] or bool(forests.get("zonal", {}).get("changed")) or forests_geometry_changed,
        )
    territory_insights_delivery = generate_territory_insights_delivery(
        canonical / "soil" / "dataset_version=2025-2024-observations" / "observations.parquet",
        (canonical / "forests" / f"algorithm_version={ZONAL_ALGORITHM_VERSION}" / "zonal_statistics.parquet") if "zonal" in forests else None,
        canonical / "water" / "dataset_version=bigbang-10-1951-2025" / "observations.parquet",
        canonical / "dissesto" / "dataset_version=idrogeo-risk-2024" / "observations.parquet",
        canonical / "emissions" / "dataset_version=2026-2023-disaggregation" / "observations.parquet",
        canonical, delivery, release_id,
        force=args.force or soil["changed"] or water["changed"] or dissesto["changed"] or emissions["changed"] or bool(forests.get("zonal", {}).get("changed")),
    )
    changed = changed or soil_geometry_changed or dissesto_geometry_changed or emissions_geometry_changed or forests_geometry_changed
    changed = changed or water_delivery["changed"]
    changed = changed or dissesto_delivery["changed"]
    changed = changed or emissions_delivery["changed"]
    changed = changed or delivery_report["changed"]
    changed = changed or forests_delivery["changed"]
    changed = changed or territory_insights_delivery["changed"]
    reports_with_files = [delivery_report, water_delivery, dissesto_delivery, emissions_delivery, forests_delivery, territory_insights_delivery]
    raw_declarations = _declared_raw_paths({
        "boundaries": boundaries, "soil": soil, "water": water,
        "national_emissions": national_emissions, "provincial_emissions": provincial_emissions,
        "dissesto": dissesto_fetch, "forests": forest_fetch,
    })
    metadata_paths = [path for path in raw_declarations if path.name.endswith(".metadata.json")]
    catalog_path = Path(forest_fetch["catalog"]["path"]) if args.scope == "all" and forest_fetch.get("catalog", {}).get("path") else None
    current_source_state = build_source_state_from_metadata_paths(root / "raw", metadata_paths, include_catalog=catalog_path)
    canonical_declarations = [
        *_territory_paths(canonical),
        canonical / "soil" / "dataset_version=2025-2024-observations" / "observations.parquet",
        canonical / "water" / "dataset_version=bigbang-10-1951-2025" / "observations.parquet",
        canonical / "dissesto" / "dataset_version=idrogeo-risk-2024" / "observations.parquet",
        canonical / "emissions" / "dataset_version=2026-2023-disaggregation" / "observations.parquet",
        canonical / "emissions" / "national" / "greenhouse-gases" / "dataset_version=2026-1990-2024" / "observations.parquet",
        canonical / "emissions" / "national" / "air-pollutants-nfr" / "dataset_version=2026-1990-2024" / "observations.parquet",
    ]
    if args.scope == "all":
        canonical_declarations.extend((
            canonical / "forests" / "dataset_version=infc2015-published-tables" / "observations.parquet",
            canonical / "forests" / f"algorithm_version={ZONAL_ALGORITHM_VERSION}" / "zonal_statistics.parquet",
        ))
    declared_paths = [
        *raw_declarations, *canonical_declarations,
        derived / "soil" / "algorithm_version=soil-analytics-v1" / "analytics.parquet",
        *[path for report in reports_with_files for path in report.get("files", [])],
        *[Path(info["path"]) for info in [*pmtiles.values(), *dissesto_pmtiles.values(), *emissions_pmtiles.values(), *forests_pmtiles.values()]],
    ]
    if catalog_path is not None:
        declared_paths.append(catalog_path)
    manifest, scoped_metrics, publication = _publish_scoped(
        store=store, root=root, output=output, release_id=release_id, scope=args.scope,
        previous_state=previous_source_state, current_state=current_source_state, declared_paths=declared_paths, changed=changed,
    )
    source_state = publication["source_state"]
    raw_soil_bytes = soil["source"]["bytes"]
    soil_parquet_bytes = soil["canonical_bytes"]
    territory_parquet_bytes = _bytes_under(canonical / "territories", (".parquet",))
    raw_all_bytes = sum(entry["bytes"] for entry in source_state["sources"])
    shared_bytes = raw_all_bytes - raw_soil_bytes + territory_parquet_bytes + sum(info["bytes"] for info in pmtiles.values())
    estimate = {
        "assumption": "Each analogous domain has ISPRA-soil-sized raw and canonical table; historical ISTAT and PMTiles are shared once.",
        "domains_5_bytes": shared_bytes + 5 * (raw_soil_bytes + soil_parquet_bytes),
        "domains_10_bytes": shared_bytes + 10 * (raw_soil_bytes + soil_parquet_bytes),
    }
    report = {
        "run_id": manifest["releaseId"],
        "startedAt": started_at,
        "completedAt": now_iso(),
        "durationSeconds": round(time.monotonic() - started, 3),
        "status": "success" if publication["changed"] else "noop",
        "changed": publication["changed"],
        "boundaries": boundaries,
        "pmtiles": pmtiles,
        "dissesto_pmtiles": dissesto_pmtiles,
        "emissions_pmtiles": emissions_pmtiles,
        "forests_pmtiles": forests_pmtiles,
        "soil": soil,
        "water": water,
        "emissions": emissions,
        "dissesto": dissesto,
        "dissesto_fetch": dissesto_fetch,
        "forests": forests,
        "analytics": analytics,
        "delivery": {key: value for key, value in delivery_report.items() if key != "files"},
        "water_delivery": {key: value for key, value in water_delivery.items() if key != "files"},
        "dissesto_delivery": {key: value for key, value in dissesto_delivery.items() if key != "files"},
        "emissions_delivery": {key: value for key, value in emissions_delivery.items() if key != "files"},
        "forests_delivery": {key: value for key, value in forests_delivery.items() if key != "files"},
        "territory_insights_delivery": {key: value for key, value in territory_insights_delivery.items() if key != "files"},
        "storage": {
            "raw_all_bytes": raw_all_bytes,
            "raw_soil_bytes": raw_soil_bytes,
            "canonical_soil_parquet_bytes": soil_parquet_bytes,
            "canonical_territories_parquet_bytes": territory_parquet_bytes,
            "pmtiles_bytes": sum(info["bytes"] for info in [*pmtiles.values(), *dissesto_pmtiles.values()]),
            "analogue_domain_estimate": estimate,
        },
        "operationalMetrics": {
            "sourceChecks": scoped_metrics["sourceChecks"],
            "sourcesChanged": scoped_metrics["sourcesChanged"],
            "sourcesUnchanged": scoped_metrics["sourcesUnchanged"],
            "sourcesUnverifiable": scoped_metrics["sourcesUnverifiable"],
            "rawBytesAcquired": scoped_metrics["rawBytesAcquired"],
            "canonicalBytesGenerated": sum(info.get("canonical_bytes", 0) for info in [soil, water, national_emissions, provincial_emissions, dissesto, forests.get("infc", {}), forests.get("zonal", {})] if info.get("changed")),
            "derivedBytesGenerated": analytics.get("bytes", 0) if analytics.get("changed") else 0,
            "deliveryBytesGenerated": sum(report.get("bytes", 0) for report in reports_with_files if report.get("changed")),
            "objectsUploaded": scoped_metrics["objectsUploaded"],
            "objectsReused": scoped_metrics["objectsReused"],
            "bytesUploadedToR2": scoped_metrics["bytesUploadedToR2"],
            "releaseReferencedBytes": scoped_metrics["releaseReferencedBytes"],
            "totalSourcesInRelease": scoped_metrics["totalSourcesInRelease"],
            "carriedSources": scoped_metrics["carriedSources"],
            "carriedArtifacts": scoped_metrics["carriedArtifacts"],
            "pipelineDurationSeconds": round(time.monotonic() - started, 3),
        },
        "manifest": manifest,
        "scope": args.scope,
        "carriedArtifacts": publication["carried"],
    }
    json_dump(Path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    load_local_env()
    parser = argparse.ArgumentParser(prog="stato-data")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="ingest every configured official-data domain")
    run_parser.add_argument("--workdir", default="data")
    run_parser.add_argument("--output", default="artifacts")
    run_parser.add_argument("--report", default="reports/first-ingestion.json")
    run_parser.add_argument("--release-id")
    run_parser.add_argument("--publish", choices=("local", "r2"), default="local")
    run_parser.add_argument("--force", action="store_true", help="reprocess unchanged source assets; manual recovery only")
    run_parser.add_argument("--offline", action="store_true", help="use only pre-existing official raw assets; never make HTTP requests")
    run_parser.add_argument("--scope", choices=("all", "data", "geospatial"), default="all", help="workflow ownership; data reuses validated geospatial canonical")
    run_parser.add_argument("--plan", help="ephemeral check-sources report tied to the active release")
    fetch_parser = sub.add_parser("fetch", help="acquire official raw assets for one domain")
    fetch_parser.add_argument("domain", choices=("dissesto", "emissions", "foreste"))
    fetch_parser.add_argument("--workdir", default="data")
    state_parser = sub.add_parser("check-sources", help="GET-check persisted source state before a scoped workflow")
    state_parser.add_argument("--scope", choices=("data", "geospatial"), required=True)
    state_parser.add_argument("--output", default="artifacts")
    state_parser.add_argument("--workdir", default="data")
    state_parser.add_argument("--publish", choices=("local", "r2"), default="local")
    state_parser.add_argument("--report")
    state_parser.add_argument("--force", action="store_true")
    rollback_parser = sub.add_parser("rollback", help="atomically repoint local or R2 manifest")
    rollback_parser.add_argument("release_id")
    rollback_parser.add_argument("--output", default="artifacts")
    rollback_parser.add_argument("--publish", choices=("local", "r2"), default="local")
    args = parser.parse_args()
    if args.command == "run":
        return run(args)
    if args.command == "fetch":
        if args.domain == "foreste":
            print(json.dumps(fetch_forests(Path(args.workdir)), ensure_ascii=False, indent=2))
            return 0
        if args.domain == "emissions":
            result = {
                "national": fetch_national_emissions(Path(args.workdir)),
                "territories": {"provincial": fetch_emissions(Path(args.workdir))},
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        print(json.dumps(fetch_dissesto(Path(args.workdir)), ensure_ascii=False, indent=2))
        return 0
    if args.command == "check-sources":
        store = R2ObjectStore() if args.publish == "r2" else LocalObjectStore(Path(args.output) / "object-store")
        persisted = _active_source_state_with_legacy_bootstrap(store)
        release = active_release(store)
        result = check_persisted_sources(
            persisted,
            scope=args.scope,
            stage_dir=Path(args.workdir) / ".preflight" / args.scope,
        )
        result["schemaVersion"] = PLAN_SCHEMA_VERSION
        result["activeReleaseId"] = release.get("releaseId") if release else None
        if args.scope == "geospatial":
            from .forests import HRL, _cdse_token, _check_catalog

            previous_catalog = next((entry for entry in (persisted or {}).get("sources", []) if entry.get("kind") == "catalog" and entry.get("source_id", entry.get("sourceId")) == HRL["source_id"]), None)
            result["sourceChecks"] += 1
            try:
                catalog = _check_catalog(HRL, _cdse_token(HRL))
                catalog_changed = previous_catalog is None or previous_catalog.get("sha256") != catalog["signature"]
                result["catalog"] = {
                    "checked": True,
                    "status": "changed" if catalog_changed else "unchanged",
                    "changed": catalog_changed,
                    "products": catalog["products"],
                    "signature": catalog["signature"],
                }
                if catalog_changed:
                    staged_catalog = Path(args.workdir) / ".preflight" / args.scope / "copernicus-catalog.json"
                    json_dump(staged_catalog, catalog)
                    result["catalog"]["stagedPath"] = str(staged_catalog)
                result["changed"] = bool(result["changed"] or catalog_changed)
                if catalog_changed:
                    result["sourcesChanged"] += 1
                else:
                    result["sourcesUnchanged"] += 1
            except Exception as exc:
                has_baseline = previous_catalog is not None
                result["catalog"] = {
                    "checked": False,
                    "status": "unverifiable" if has_baseline else "changed",
                    "changed": not has_baseline,
                    "reason": type(exc).__name__,
                }
                if has_baseline:
                    result["sourcesUnverifiable"] = result.get("sourcesUnverifiable", 0) + 1
                else:
                    result["changed"] = True
                    result["sourcesChanged"] += 1
        if args.force:
            result["changed"] = True
            result["reason"] = "force"
        if args.report:
            json_dump(Path(args.report), result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    store = R2ObjectStore() if args.publish == "r2" else LocalObjectStore(Path(args.output) / "object-store")
    print(json.dumps(rollback(store, args.release_id), ensure_ascii=False, indent=2))
    return 0
