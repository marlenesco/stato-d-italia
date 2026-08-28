from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from .analytics import build_soil_analytics
from .common import json_dump, now_iso
from .delivery import generate_soil_delivery
from .emissions import fetch_emissions, ingest_emissions
from .emissions_delivery import generate_emissions_delivery
from .emissions_national import fetch_national_emissions, ingest_national_emissions
from .forests import ZONAL_ALGORITHM_VERSION, fetch_forests, ingest_forests, ingest_infc_forests
from .forests_delivery import generate_forests_delivery
from .dissesto import fetch_dissesto, ingest_dissesto
from .dissesto_delivery import generate_dissesto_delivery
from .release import LocalObjectStore, R2ObjectStore, ReleaseArtifact, publish_release, rollback
from .soil import ingest_soil
from .territories import SOURCE_YEARS, ingest_boundaries
from .water import ingest_water
from .water_delivery import generate_water_delivery
from .tiles import build_pmtiles, is_readable_pmtiles


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
    forest_fetch = fetch_forests(root, offline=args.offline)
    forests: dict = {"fetch": forest_fetch}
    infc_raw = root / "raw" / "infc-2015-forests" / "volume.zip"
    if infc_raw.exists():
        forests["infc"] = ingest_infc_forests(root, canonical, force=args.force)
        mode = os.getenv("FOREST_PROCESSING_MODE", "raster")
        zonal_raw = any(path for source in ("copernicus-hrl-forests", "copernicus-corine-forests") for path in (root / "raw" / source).glob("**/*.tif"))
        catalog_changed = bool(forest_fetch.get("catalog", {}).get("changed"))
        if mode == "statistical-api" and forest_fetch.get("catalog", {}).get("status") != "blocked":
            forests["zonal"] = ingest_forests(root, canonical, force=args.force or catalog_changed, mode=mode)
        elif zonal_raw:
            forests["zonal"] = ingest_forests(root, canonical, force=args.force, mode="raster")
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
    if "zonal" in forests:
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
    elif "infc" in forests:
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
    if "infc" in forests:
        forests_delivery = generate_forests_delivery(
            (canonical / "forests" / f"algorithm_version={ZONAL_ALGORITHM_VERSION}" / "zonal_statistics.parquet") if "zonal" in forests else None,
            canonical / "forests" / "dataset_version=infc2015-published-tables" / "observations.parquet", canonical, delivery, release_id,
            {level: Path(info["path"]) for level, info in forests_pmtiles.items()},
            force=args.force or forests["infc"]["changed"] or bool(forests.get("zonal", {}).get("changed")) or forests_geometry_changed,
        )
    changed = changed or soil_geometry_changed or dissesto_geometry_changed or emissions_geometry_changed or forests_geometry_changed
    changed = changed or water_delivery["changed"]
    changed = changed or dissesto_delivery["changed"]
    changed = changed or emissions_delivery["changed"]
    changed = changed or delivery_report["changed"]
    changed = changed or forests_delivery["changed"]
    raw_suffixes = {".zip", ".xlsx", ".json", ".pdf"} | ({".tif", ".tiff"} if os.getenv("FORESTS_RAW_RETENTION", "retain") == "retain" else set())
    artifacts = [
        *[ReleaseArtifact(path, str(path.relative_to(root))) for path in (root / "raw").rglob("*") if path.is_file() and path.suffix in raw_suffixes],
        *[ReleaseArtifact(path, str(path.relative_to(root))) for path in canonical.rglob("*.parquet")],
        *[ReleaseArtifact(path, str(path.relative_to(root))) for path in derived.rglob("*.parquet")],
        *[ReleaseArtifact(path, str(path.relative_to(root))) for path in delivery.rglob("*.json")],
        *[ReleaseArtifact(Path(info["path"]), str(Path(info["path"]).relative_to(root))) for info in [*pmtiles.values(), *dissesto_pmtiles.values(), *emissions_pmtiles.values(), *forests_pmtiles.values()]],
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
    fetch_parser = sub.add_parser("fetch", help="acquire official raw assets for one domain")
    fetch_parser.add_argument("domain", choices=("dissesto", "emissions", "foreste"))
    fetch_parser.add_argument("--workdir", default="data")
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
    store = R2ObjectStore() if args.publish == "r2" else LocalObjectStore(Path(args.output) / "object-store")
    print(json.dumps(rollback(store, args.release_id), ensure_ascii=False, indent=2))
    return 0
