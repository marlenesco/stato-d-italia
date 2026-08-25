from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from .analytics import build_soil_analytics
from .common import json_dump, now_iso
from .delivery import generate_soil_delivery
from .emissions import fetch_emissions, ingest_emissions
from .emissions_delivery import generate_emissions_delivery
from .emissions_national import fetch_national_emissions, ingest_national_emissions
from .dissesto import fetch_dissesto, ingest_dissesto
from .dissesto_delivery import generate_dissesto_delivery
from .release import LocalObjectStore, R2ObjectStore, ReleaseArtifact, publish_release, rollback
from .soil import ingest_soil
from .territories import SOURCE_YEARS, ingest_boundaries
from .water import ingest_water
from .water_delivery import generate_water_delivery
from .tiles import build_pmtiles


def _release_id() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ") + "-local"


def _bytes_under(root: Path, suffixes: tuple[str, ...] | None = None) -> int:
    return sum(
        path.stat().st_size for path in root.rglob("*")
        if path.is_file() and (suffixes is None or path.suffix in suffixes)
    )


def run(args: argparse.Namespace) -> int:
    started = time.monotonic()
    started_at = now_iso()
    root = Path(args.workdir)
    output = Path(args.output)
    canonical = root / "canonical"
    derived = root / "derived"
    delivery = root / "delivery"
    release_id = args.release_id or _release_id()
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
    changed = boundaries["changed"] or soil["changed"] or water["changed"] or emissions["changed"] or dissesto["changed"] or bool(dissesto_fetch and dissesto_fetch["changed"]) or analytics["changed"]
    pmtiles: dict[str, dict] = {}
    for level in ("municipality", "province", "region"):
        pmtiles_path = delivery / "soil" / "geometry" / f"istat-{level}-2025.pmtiles"
        if boundaries["changed"] or not pmtiles_path.exists():
            pmtiles[level] = build_pmtiles(canonical / "territories" / "reference_year=2025" / f"{level}.parquet", pmtiles_path)
        else:
            pmtiles[level] = {"path": str(pmtiles_path), "bytes": pmtiles_path.stat().st_size, "skipped": True}
    dissesto_pmtiles: dict[str, dict] = {}
    for level in ("municipality", "province", "region"):
        pmtiles_path = delivery / "dissesto" / "geometry" / f"istat-{level}-2024.pmtiles"
        if dissesto["changed"] or not pmtiles_path.exists():
            dissesto_pmtiles[level] = build_pmtiles(canonical / "territories" / "reference_year=2024" / f"{level}.parquet", pmtiles_path)
        else:
            dissesto_pmtiles[level] = {"path": str(pmtiles_path), "bytes": pmtiles_path.stat().st_size, "skipped": True}
    delivery_report = generate_soil_delivery(
        canonical / "soil" / "dataset_version=2025-2024-observations" / "observations.parquet",
        derived / "soil" / "algorithm_version=soil-analytics-v1" / "analytics.parquet",
        canonical,
        root,
        delivery,
        release_id,
        force=args.force or boundaries["changed"] or soil["changed"] or analytics["changed"],
    )
    water_delivery = generate_water_delivery(
        canonical / "water" / "dataset_version=bigbang-10-1951-2025" / "observations.parquet",
        delivery, release_id, force=args.force or water["changed"],
    )
    dissesto_delivery = generate_dissesto_delivery(
        canonical / "dissesto" / "dataset_version=idrogeo-risk-2024" / "observations.parquet",
        delivery, release_id, {level: Path(info["path"]) for level, info in dissesto_pmtiles.items()},
        force=args.force or dissesto["changed"],
    )
    emissions_delivery = generate_emissions_delivery(
        canonical / "emissions" / "national" / "greenhouse-gases" / "dataset_version=2026-1990-2024" / "observations.parquet",
        canonical / "emissions" / "national" / "air-pollutants-nfr" / "dataset_version=2026-1990-2024" / "observations.parquet",
        canonical / "emissions" / "dataset_version=2026-2023-disaggregation" / "observations.parquet",
        delivery, release_id, force=args.force or emissions["changed"],
    )
    changed = changed or water_delivery["changed"]
    changed = changed or dissesto_delivery["changed"]
    changed = changed or emissions_delivery["changed"]
    changed = changed or delivery_report["changed"]
    artifacts = [
        *[ReleaseArtifact(path, str(path.relative_to(root))) for path in (root / "raw").rglob("*") if path.is_file() and path.suffix in {".zip", ".xlsx", ".json", ".pdf"}],
        *[ReleaseArtifact(path, str(path.relative_to(root))) for path in canonical.rglob("*.parquet")],
        *[ReleaseArtifact(path, str(path.relative_to(root))) for path in derived.rglob("*.parquet")],
        *[ReleaseArtifact(path, str(path.relative_to(root))) for path in delivery.rglob("*.json")],
        *[ReleaseArtifact(Path(info["path"]), str(Path(info["path"]).relative_to(root))) for info in [*pmtiles.values(), *dissesto_pmtiles.values()]],
    ]
    artifacts.sort(key=lambda artifact: artifact.logical_path)
    store = R2ObjectStore() if args.publish == "r2" else LocalObjectStore(output / "object-store")
    manifest = publish_release(store, release_id, artifacts) if changed else store.read_json("manifest.json")
    raw_soil_bytes = soil["source"]["bytes"]
    soil_parquet_bytes = soil["canonical_bytes"]
    territory_parquet_bytes = _bytes_under(canonical / "territories", (".parquet",))
    raw_all_bytes = _bytes_under(root / "raw", (".zip", ".xlsx", ".json", ".pdf"))
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
        "status": "success" if changed else "noop",
        "changed": changed,
        "boundaries": boundaries,
        "pmtiles": pmtiles,
        "dissesto_pmtiles": dissesto_pmtiles,
        "soil": soil,
        "water": water,
        "emissions": emissions,
        "dissesto": dissesto,
        "dissesto_fetch": dissesto_fetch,
        "analytics": analytics,
        "delivery": {key: value for key, value in delivery_report.items() if key != "files"},
        "water_delivery": {key: value for key, value in water_delivery.items() if key != "files"},
        "dissesto_delivery": {key: value for key, value in dissesto_delivery.items() if key != "files"},
        "emissions_delivery": {key: value for key, value in emissions_delivery.items() if key != "files"},
        "storage": {
            "raw_all_bytes": raw_all_bytes,
            "raw_soil_bytes": raw_soil_bytes,
            "canonical_soil_parquet_bytes": soil_parquet_bytes,
            "canonical_territories_parquet_bytes": territory_parquet_bytes,
            "pmtiles_bytes": sum(info["bytes"] for info in [*pmtiles.values(), *dissesto_pmtiles.values()]),
            "analogue_domain_estimate": estimate,
        },
        "manifest": manifest,
    }
    json_dump(Path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
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
    fetch_parser = sub.add_parser("fetch", help="acquire official raw assets for one domain")
    fetch_parser.add_argument("domain", choices=("dissesto", "emissions"))
    fetch_parser.add_argument("--workdir", default="data")
    rollback_parser = sub.add_parser("rollback", help="atomically repoint local or R2 manifest")
    rollback_parser.add_argument("release_id")
    rollback_parser.add_argument("--output", default="artifacts")
    rollback_parser.add_argument("--publish", choices=("local", "r2"), default="local")
    args = parser.parse_args()
    if args.command == "run":
        return run(args)
    if args.command == "fetch":
        if args.domain == "emissions":
            result = {
                "national": fetch_national_emissions(Path(args.workdir)),
                "territories": {"provincial": fetch_emissions(Path(args.workdir))},
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        print(json.dumps(fetch_dissesto(Path(args.workdir)), ensure_ascii=False, indent=2))
        return 0
    store = R2ObjectStore() if args.publish == "r2" else LocalObjectStore(Path(args.output) / "object-store")
    print(json.dumps(rollback(store, args.release_id), ensure_ascii=False, indent=2))
    return 0
