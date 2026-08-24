from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from .common import json_dump, now_iso
from .release import LocalObjectStore, R2ObjectStore, publish_release, rollback
from .soil import ingest_soil
from .territories import SOURCE_YEARS, ingest_boundaries
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
    boundaries = ingest_boundaries(root, canonical, SOURCE_YEARS, force=args.force)
    soil = ingest_soil(root, canonical, force=args.force)
    changed = boundaries["changed"] or soil["changed"]
    pmtiles_path = output / "generated" / "istat-municipalities-2025.pmtiles"
    if changed or not pmtiles_path.exists():
        pmtiles = build_pmtiles(canonical / "territories" / "reference_year=2025" / "municipality.parquet", pmtiles_path)
    else:
        pmtiles = {"path": str(pmtiles_path), "bytes": pmtiles_path.stat().st_size, "skipped": True}
    artifacts = sorted({
        *[path for path in (root / "raw").rglob("*") if path.is_file() and path.suffix in {".zip", ".xlsx", ".json"}],
        *[path for path in canonical.rglob("*.parquet")],
        Path(pmtiles["path"]),
    })
    store = R2ObjectStore() if args.publish == "r2" else LocalObjectStore(output / "object-store")
    manifest = publish_release(store, args.release_id or _release_id(), artifacts) if changed else store.read_json("manifest.json")
    raw_soil_bytes = soil["source"]["bytes"]
    soil_parquet_bytes = soil["canonical_bytes"]
    territory_parquet_bytes = _bytes_under(canonical / "territories", (".parquet",))
    raw_all_bytes = _bytes_under(root / "raw", (".zip", ".xlsx"))
    shared_bytes = raw_all_bytes - raw_soil_bytes + territory_parquet_bytes + pmtiles["bytes"]
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
        "soil": soil,
        "storage": {
            "raw_all_bytes": raw_all_bytes,
            "raw_soil_bytes": raw_soil_bytes,
            "canonical_soil_parquet_bytes": soil_parquet_bytes,
            "canonical_territories_parquet_bytes": territory_parquet_bytes,
            "pmtiles_bytes": pmtiles["bytes"],
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
    run_parser = sub.add_parser("run", help="ingest ISTAT territories and ISPRA soil")
    run_parser.add_argument("--workdir", default="data")
    run_parser.add_argument("--output", default="artifacts")
    run_parser.add_argument("--report", default="reports/first-ingestion.json")
    run_parser.add_argument("--release-id")
    run_parser.add_argument("--publish", choices=("local", "r2"), default="local")
    run_parser.add_argument("--force", action="store_true", help="reprocess unchanged source assets; manual recovery only")
    rollback_parser = sub.add_parser("rollback", help="atomically repoint local or R2 manifest")
    rollback_parser.add_argument("release_id")
    rollback_parser.add_argument("--output", default="artifacts")
    rollback_parser.add_argument("--publish", choices=("local", "r2"), default="local")
    args = parser.parse_args()
    if args.command == "run":
        return run(args)
    store = R2ObjectStore() if args.publish == "r2" else LocalObjectStore(Path(args.output) / "object-store")
    print(json.dumps(rollback(store, args.release_id), ensure_ascii=False, indent=2))
    return 0
