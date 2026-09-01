from __future__ import annotations

import json
import os
import tempfile
import zipfile
from datetime import date
from hashlib import sha256
from pathlib import Path

import pandas as pd
import requests

from .common import json_dump, now_iso, sha256_file, stable_id
from .download import download
from .ingestion_plan import materialize_planned_asset
from .registry import load_source
from .territories import load_territory_index

SOURCE = load_source("ispra-idrogeo-risk-2024")
SOURCE_ID = SOURCE["source_id"]
API_BASE_URL = SOURCE["source_contract"]["api_base_url"].rstrip("/")
METRICS = SOURCE["source_contract"]["metrics"]
RAW_ARCHIVE = "idrogeo-risk-api-responses.zip"
EXPORTS = SOURCE["source_contract"]["json_exports"]


def _raw_metadata_path(archive: Path) -> Path:
    return archive.with_suffix(archive.suffix + ".metadata.json")


def _get_json(url: str) -> bytes:
    response = requests.get(
        url, timeout=(15, 120), headers={"Accept": "application/json", "User-Agent": "stato-italia-data/0.1"},
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError(f"IdroGEO returned non-JSON content: {url}") from exc
    if not isinstance(payload, (dict, list)):
        raise ValueError(f"IdroGEO returned unexpected JSON value: {url}")
    return response.content


def _export_payloads() -> dict[str, bytes]:
    """Read every real component of the composite IdroGEO raw asset."""
    return {level: _get_json(f"{API_BASE_URL}/{endpoint}") for level, endpoint in EXPORTS.items()}


def _exports_signature(responses: dict[str, bytes]) -> str:
    """Hash canonical JSON payloads with level boundaries and stable ordering."""
    digest = sha256()
    if set(responses) != set(EXPORTS):
        raise ValueError("Incomplete IdroGEO composite export set")
    for level in EXPORTS:
        try:
            payload = json.loads(responses[level])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid IdroGEO {level} export JSON") from exc
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        digest.update(level.encode())
        digest.update(b"\0")
        digest.update(len(canonical).to_bytes(8, "big"))
        digest.update(canonical)
    return digest.hexdigest()


def check_dissesto_source(expected_signature: str | None, *, staged_path: Path | None = None) -> dict:
    """Read-only remote check for the four payloads composing the bundle."""
    responses = _export_payloads()
    signature = _exports_signature(responses)
    result = {
        "changed": expected_signature != signature,
        "signature": signature,
        "exports": len(EXPORTS),
        "checked_at": now_iso(),
    }
    if staged_path is not None:
        _write_exports_archive(responses, staged_path)
        result |= {
            "staged_path": str(staged_path),
            "sha256": sha256_file(staged_path),
            "bytes": staged_path.stat().st_size,
        }
    return result


def _archive_exports_signature(archive: Path) -> str:
    with zipfile.ZipFile(archive) as bundle:
        return _exports_signature({level: bundle.read(_entry(level)) for level in EXPORTS})


def _entry(level: str) -> str:
    return f"{level}/export.json"


def _write_entry(archive: zipfile.ZipFile, name: str, body: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, body)


def _write_exports_archive(responses: dict[str, bytes], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".partial", dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w") as bundle:
            for level in EXPORTS:
                _write_entry(bundle, _entry(level), responses[level])
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_metadata_assets(raw_dir: Path) -> None:
    """Fail when IdroGEO metadata redirects or changes its binary contract."""
    metadata = raw_dir / "Metadati_open_data_PIR.xlsx"
    licence = raw_dir / "Licenza_Condizioni_Uso_Pericolosita_Indicatori_Rischio_Frane_Alluvioni_ISPRA.pdf"
    try:
        with zipfile.ZipFile(metadata) as workbook:
            if "[Content_Types].xml" not in workbook.namelist():
                raise ValueError("missing [Content_Types].xml")
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        raise ValueError("Unexpected IdroGEO metadata contract: expected an XLSX workbook, not a redirect or HTML page") from exc
    if not licence.read_bytes().startswith(b"%PDF-"):
        raise ValueError("Unexpected IdroGEO licence contract: expected a PDF document")


def fetch_dissesto(raw_root: Path) -> dict:
    """Acquire official IdroGEO aggregated exports into one raw archive."""
    raw_dir = raw_root / "raw" / SOURCE_ID
    archive = raw_dir / RAW_ARCHIVE
    metadata_path = _raw_metadata_path(archive)
    raw_dir.mkdir(parents=True, exist_ok=True)
    metadata_assets = {
        name: download(url, raw_dir / name, SOURCE_ID)
        for name, url in SOURCE["source_contract"]["metadata_urls"].items()
    }
    _validate_metadata_assets(raw_dir)
    planned = materialize_planned_asset(
        API_BASE_URL,
        archive,
        SOURCE_ID,
        source_context={"preflight_method": "idrogeo_exports_v1"},
    )
    if planned is not None:
        signature = _archive_exports_signature(archive)
        if planned.get("source_signature") != signature:
            raise ValueError("Planned IdroGEO bundle signature mismatch")
        return {
            "changed": planned.get("plan_status") == "changed",
            "source": planned,
            "metadata_assets": metadata_assets,
        }
    requests_to_fetch = [(level, f"{API_BASE_URL}/{endpoint}") for level, endpoint in EXPORTS.items()]
    file_descriptor, temporary_name = tempfile.mkstemp(prefix="stato-italia-idrogeo-", suffix=".zip", dir=raw_dir)
    os.close(file_descriptor)
    temporary = Path(temporary_name)
    try:
        responses = _export_payloads()
        source_signature = _exports_signature(responses)
        with zipfile.ZipFile(temporary, "w") as bundle:
            for level, _url in requests_to_fetch:
                _write_entry(bundle, _entry(level), responses[level])
        checksum = sha256_file(temporary)
        prior = json.loads(metadata_path.read_text()) if archive.exists() and metadata_path.exists() else None
        prior_signature = prior.get("source_signature") if prior else None
        if prior_signature is None and archive.exists():
            prior_signature = _archive_exports_signature(archive)
        unchanged = prior_signature == source_signature
        if unchanged:
            temporary.unlink()
            checksum = sha256_file(archive)
        else:
            temporary.replace(archive)
        metadata = {
            "source_id": SOURCE_ID, "acquired_at": now_iso(), "acquisition_mode": "official_public_api",
            "requested_url": API_BASE_URL, "resolved_url": API_BASE_URL, "filename": archive.name,
            "bytes": archive.stat().st_size, "sha256": checksum, "content_type": "application/zip",
            "etag": None, "last_modified": None, "response_count": len(requests_to_fetch),
            "exports_by_level": {level: 1 for level in EXPORTS},
            "preflight_method": "idrogeo_exports_v1", "source_signature": source_signature,
            "unchanged": unchanged,
        }
        json_dump(metadata_path, metadata)
        return {"changed": not unchanged, "source": metadata | {"local_path": str(archive), "metadata_path": str(metadata_path)}, "metadata_assets": metadata_assets}
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _code(value: object, width: int, field: str) -> str:
    if value is None:
        raise ValueError(f"missing IdroGEO {field}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid IdroGEO {field}: {value!r}") from exc
    if not number.is_integer():
        raise ValueError(f"non-integral IdroGEO {field}: {value!r}")
    return str(int(number)).zfill(width)


def _records_from_archive(archive: Path, level: str) -> list[dict]:
    with zipfile.ZipFile(archive) as bundle:
        entry = _entry(level)
        if entry not in bundle.namelist():
            raise ValueError(f"Unexpected IdroGEO raw archive: no {level} responses")
        payload = json.loads(bundle.read(entry))
        if level == "country":
            if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
                raise ValueError("Unexpected IdroGEO country export contract: one-row array expected")
            return payload
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise ValueError(f"Unexpected IdroGEO {level} export contract: array of objects expected")
        return payload


def _territory(row: dict, level: str, index: dict[str, dict]) -> dict:
    if level == "country":
        return index["it:country:IT"]
    field, width = {"region": ("cod_reg", 2), "province": ("cod_prov", 3), "municipality": ("pro_com", 6)}[level]
    territory_id = f"it:{level}:{_code(row.get(field), width, field)}"
    territory = index.get(territory_id)
    if territory is None:
        raise ValueError(f"IdroGEO {level} code does not exist in 2024 ISTAT boundaries: {territory_id}")
    return territory


def _record(*, row: dict, row_number: int, level: str, territory: dict, field: str, spec: dict, source_hash: str, ingested_at: str) -> dict:
    if field not in row:
        raise ValueError(f"Unexpected IdroGEO {level} response contract: missing indicator {field!r}")
    raw_value = row[field]
    unavailable = raw_value == -1 or raw_value == "-1"
    if raw_value is None:
        raise ValueError(f"Unexpected IdroGEO {level} response contract: null indicator {field!r}")
    if unavailable:
        value = None
    else:
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid IdroGEO indicator {field!r}: {raw_value!r}") from exc
    year = int(spec["reference_year"])
    return {
        "observation_id": stable_id(SOURCE_ID, source_hash, territory["territory_id"], field),
        "dataset_id": SOURCE_ID, "dataset_version": "idrogeo-risk-2024", "source_asset_sha256": source_hash,
        "source_row_locator": f"api:{level}:{territory['istat_code']}:{field}", "metric_id": spec["metric_id"],
        "territory_id": territory["territory_id"], "territory_version_id": territory["territory_version_id"],
        "territory_level": territory["level"], "period_start": date(year, 1, 1).isoformat(),
        "period_end": date(year, 12, 31).isoformat(), "reference_year": year, "value_decimal": value,
        "value_state": "unavailable" if unavailable else "observed", "unit_ucum": spec["unit_ucum"],
        "official_status": "unknown", "quality_flags": ["source_value_unavailable"] if unavailable else [],
        "methodology_version": "idrogeo-risk-2024", "ingested_at": ingested_at,
    }


def _summarize(source: dict, destination: Path) -> dict:
    table = pd.read_parquet(destination)
    return {"source": source, "records": len(table), "records_by_level": table.groupby("territory_level").size().to_dict(),
            "records_by_metric": table.groupby("metric_id").size().to_dict(), "records_by_value_state": table.groupby("value_state").size().to_dict(),
            "canonical_path": str(destination), "canonical_bytes": destination.stat().st_size}


def ingest_dissesto(raw_root: Path, canonical_root: Path, force: bool = False) -> dict:
    archive = raw_root / "raw" / SOURCE_ID / RAW_ARCHIVE
    metadata_path = _raw_metadata_path(archive)
    if not archive.exists() or not metadata_path.exists():
        raise FileNotFoundError(f"IdroGEO raw archive missing. Run `stato-data fetch dissesto --workdir {raw_root}` first.")
    source = json.loads(metadata_path.read_text())
    if source.get("source_id") != SOURCE_ID:
        raise ValueError(f"IdroGEO raw metadata mismatch: {source.get('source_id')!r}")
    destination = canonical_root / "dissesto" / "dataset_version=idrogeo-risk-2024" / "observations.parquet"
    if source.get("unchanged") and destination.exists() and not force:
        return _summarize(source, destination) | {"changed": False, "skipped": True}
    index = load_territory_index(canonical_root, 2024)
    records: list[dict] = []
    for level in ("country", "region", "province", "municipality"):
        rows = _records_from_archive(archive, level)
        territories = [_territory(row, level, index) for row in rows]
        if level != "country":
            expected = {key for key, value in index.items() if value["level"] == level}
            actual = {territory["territory_id"] for territory in territories}
            if actual != expected:
                raise ValueError(f"Unexpected IdroGEO {level} coverage: missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}")
        for row_number, (row, territory) in enumerate(zip(rows, territories, strict=True)):
            for field, spec in METRICS.items():
                records.append(_record(row=row, row_number=row_number, level=level, territory=territory, field=field,
                                       spec=spec, source_hash=source["sha256"], ingested_at=source["acquired_at"]))
    table = pd.DataFrame(records)
    if table.duplicated(["observation_id"]).any():
        raise ValueError("Duplicate canonical IdroGEO observation IDs")
    destination.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(destination, index=False, compression="zstd")
    return _summarize(source, destination) | {"changed": True}
