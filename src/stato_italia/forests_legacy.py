"""CLMS legacy ZIP acquisition and validation; no CDSE or implicit auth exchange."""
from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import time
import zipfile
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
import rasterio
import requests

from .common import json_dump, sha256_file
from .registry import load_source

LEGACY = load_source("copernicus-forests-legacy")


def legacy_enabled() -> bool:
    value = os.getenv(LEGACY["enabled_environment"], "0")
    if value not in {"0", "1"}:
        raise ValueError("FOREST_LEGACY_ENABLED must be 0 or 1")
    return value == "1"


def environment_token() -> str:
    """Operational bridge: the caller provisions/refreshes the CLMS bearer."""
    token = os.getenv(LEGACY["token_environment"], "")
    if not token or any(c.isspace() for c in token):
        raise ValueError("CLMS bearer unavailable; configure a token provider")
    return token


def product_contract(asset: dict, year: int) -> dict:
    if year not in (2012, 2015) or year not in asset["years"]:
        raise ValueError("Unsupported legacy Forest period")
    product = asset["products"][year]
    return {
        "source_id": LEGACY["source_id"], "asset_id": asset["id"],
        "methodology_family": LEGACY["methodology_family"], "reference_year": year,
        "territory_reference_year": year, "native_resolution_m": asset["native_resolution_m"],
        "resolution_m": asset["resolution_m"], "crs": LEGACY["crs"],
        "product": product, "series_break_to_modern": LEGACY["series_break_to_modern"],
    }


def raw_path(root: Path, asset: dict, year: int) -> Path:
    return root / "raw" / LEGACY["source_id"] / asset["id"] / str(year) / "product.zip"


def _identifier(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 256


def _json_request(client, method: str, url: str, token_provider, *, request_timeout=30, **kwargs):
    response = None
    try:
        token = token_provider()
        if not isinstance(token, str) or not token or any(c.isspace() for c in token):
            raise ValueError()
        response = client.request(method, url, headers={"Authorization": f"Bearer {token}"},
                                  timeout=request_timeout, allow_redirects=False, **kwargs)
        if response.status_code != 200:
            raise ValueError()
        return response.json()
    except Exception:
        raise ValueError("CLMS authenticated request failed or returned invalid JSON") from None
    finally:
        if response is not None:
            response.close()


def request_download_url(asset: dict, year: int, *, client, token_provider=environment_token,
                         timeout: float = 600, max_polls: int = 60,
                         clock=time.monotonic, sleep=time.sleep) -> tuple[str, str]:
    if not math.isfinite(timeout) or timeout <= 0 or max_polls <= 0:
        raise ValueError("Invalid CLMS polling limits")
    product = product_contract(asset, year)["product"]
    payload = _json_request(client, "POST", LEGACY["request_url"], token_provider,
                            json={"Datasets": [{key: product[key] for key in ("DatasetID", "FileID")}]})
    # A single submitted dataset must resolve to exactly one task.
    if isinstance(payload, list) and len(payload) == 1:
        payload = payload[0]
    if not isinstance(payload, dict) or not _identifier(payload.get("TaskID")):
        raise ValueError("CLMS submission lacks one unambiguous TaskID")
    task_id = payload["TaskID"]
    deadline = clock() + timeout
    for attempt in range(max_polls):
        if clock() >= deadline:
            break
        payload = _json_request(client, "GET", LEGACY["search_url"], token_provider,
                                params={"status": "Finished_ok"}, request_timeout=min(30, max(0.001, deadline - clock())))
        if clock() >= deadline:
            break
        items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(items, list) or any(not isinstance(item, dict) or not _identifier(item.get("TaskID")) for item in items):
            raise ValueError("CLMS completed-task response is malformed")
        matches = [item for item in items if item["TaskID"] == task_id]
        if len(matches) > 1:
            raise ValueError("CLMS completed task is ambiguous")
        if matches:
            url = matches[0].get("DownloadURL")
            try:
                parsed = urlsplit(url) if isinstance(url, str) and not any(c.isspace() for c in url) else None
                valid = parsed and parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password and not parsed.fragment
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("CLMS completed task lacks a valid HTTPS download URL")
            return task_id, url
        remaining = deadline - clock()
        if remaining > 0 and attempt + 1 < max_polls:
            sleep(min(2 ** min(attempt, 5), remaining))
    raise TimeoutError("CLMS completion polling timed out")


def validate_raster(path: Path, asset: dict) -> None:
    """Validate every source cell, including cells masked by source metadata."""
    try:
        with rasterio.open(path) as dataset:
            resolution = asset["resolution_m"]
            if (dataset.crs != rasterio.crs.CRS.from_epsg(3035) or dataset.count != 1
                    or dataset.transform.b != 0 or dataset.transform.d != 0
                    or not math.isclose(dataset.transform.a, resolution, abs_tol=1e-8, rel_tol=0)
                    or not math.isclose(dataset.transform.e, -resolution, abs_tol=1e-8, rel_tol=0)
                    or dataset.nodata not in (None, 254, 255)
                    or dataset.scales != (1.0,) or dataset.offsets != (0.0,)
                    or not np.issubdtype(np.dtype(dataset.dtypes[0]), np.integer)):
                raise ValueError()
            allowed = list(range(101)) + [254, 255] if asset["kind"] == "tree_cover_density" else [0, 1, 2, 3, 254, 255]
            for _, window in dataset.block_windows(1):
                if not np.isin(dataset.read(1, window=window, masked=False), allowed).all():
                    raise ValueError()
    except Exception:
        raise ValueError("Legacy Forest raster violates CRS, resolution, band, NoData or value contract") from None


def extract_validated_raster(archive: Path, destination: Path, asset: dict) -> str:
    try:
        with zipfile.ZipFile(archive) as bundle:
            rasters = [info for info in bundle.infolist() if not info.is_dir() and Path(info.filename).suffix.lower() in {".tif", ".tiff"}]
            if len(rasters) != 1:
                raise ValueError()
            # Fixed destination: ZIP paths are never extracted into the filesystem.
            with bundle.open(rasters[0]) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
        validate_raster(destination, asset)
        return sha256_file(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise ValueError("Legacy Forest ZIP/raster is invalid or ambiguous") from None


def retained_product(root: Path, asset: dict, year: int) -> dict:
    path = raw_path(root, asset, year)
    metadata_path = path.with_suffix(".zip.metadata.json")
    try:
        metadata = json.loads(metadata_path.read_text())
        if (metadata["contract"] != product_contract(asset, year)
                or metadata["sha256"] != sha256_file(path)
                or metadata["bytes"] != path.stat().st_size):
            raise ValueError()
    except Exception:
        raise ValueError("Legacy Forest retained ZIP provenance is missing or incompatible") from None
    return {"local_path": str(path), "metadata_path": str(metadata_path), "changed": False, **metadata}


def acquire_product(root: Path, asset: dict, year: int, *, offline: bool = False,
                    token_provider=environment_token, client=None) -> dict:
    path = raw_path(root, asset, year)
    if path.exists():
        return retained_product(root, asset, year)
    if offline:
        raise FileNotFoundError("Legacy Forest ZIP unavailable offline")
    owned_client = client is None
    if owned_client:
        client = requests.Session()
        client.trust_env = False
    response = None
    temporary = None
    try:
        task_id, url = request_download_url(asset, year, client=client, token_provider=token_provider)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".partial", delete=False) as output:
            temporary = Path(output.name)
            # A signed DownloadURL is sufficient; never forward the CLMS bearer.
            response = client.request("GET", url, timeout=60, stream=True, allow_redirects=False)
            if response.status_code != 200:
                raise ValueError()
            digest = sha256()
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
        with tempfile.TemporaryDirectory() as directory:
            raster_hash = extract_validated_raster(temporary, Path(directory) / "raster.tif", asset)
        metadata = {"source_id": LEGACY["source_id"], "sha256": digest.hexdigest(),
                    "bytes": temporary.stat().st_size, "contract": product_contract(asset, year),
                    "raster_sha256": raster_hash, "TaskID": task_id,
                    "dataset_version": asset["products"][year]["version"], "period": [year, year],
                    "resolved_url": LEGACY["request_url"]}
        temporary.rename(path)
        json_dump(path.with_suffix(".zip.metadata.json"), metadata)
        return retained_product(root, asset, year) | {"changed": True}
    except Exception:
        raise ValueError("CLMS legacy acquisition failed; no credentials or download URL retained") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if response is not None:
            response.close()
        if owned_client:
            client.close()


def fetch_legacy_forests(root: Path, *, offline: bool = False) -> list[dict]:
    return [acquire_product(root, asset, year, offline=offline)
            for asset in LEGACY["assets"] for year in asset["years"]]


def legacy_zonal_records(root: Path, canonical_root: Path) -> tuple[list[dict], list[dict], dict[int, set[str]]]:
    """Validate ZIPs, then reuse the Forest zonal engine on exact ISTAT populations."""
    from . import forests
    from .territories import territory_reference_date

    records, coverage, regions_by_year = [], [], {}
    for asset in LEGACY["assets"]:
        for year in asset["years"]:
            metadata = retained_product(root, asset, year)
            territories = forests._slice_territories_with_region_code(canonical_root, year)
            if not territories["territory_version_id"].str.endswith("@" + territory_reference_date(year)).all():
                raise ValueError("Legacy Forest requires the exact ISTAT territory version")
            regions_by_year[year] = forests._expected_region_codes(canonical_root, year)
            contract = product_contract(asset, year)
            signature = sha256(json.dumps({"contract": contract, "sha256": metadata["sha256"]}, sort_keys=True).encode()).hexdigest()
            archive = Path(metadata["local_path"])
            with tempfile.TemporaryDirectory() as directory:
                raster = Path(directory) / "raster.tif"
                if extract_validated_raster(archive, raster, asset) != metadata["raster_sha256"]:
                    raise ValueError("Legacy Forest extracted raster checksum mismatch")
                for region in sorted(regions_by_year[year]):
                    group = {"region_istat_code": region, "paths": [raster], "manifest_path": archive,
                             "source_hash": metadata["sha256"], "snapshot_signature": signature,
                             "start_year": year, "end_year": year}
                    rows, nodata = forests._process_raster_records(asset | {"source_id": LEGACY["source_id"]}, group, territories)
                    for row in rows:
                        row.update({"methodology_family": LEGACY["methodology_family"],
                                    "native_resolution_m": asset["native_resolution_m"],
                                    "input_resolution_m": asset["resolution_m"],
                                    "source_product_json": json.dumps(contract, sort_keys=True),
                                    "derived_metric_id": forests.stable_id(forests.ZONAL_ALGORITHM_VERSION, signature,
                                        row["territory_version_id"], row["metric_id"], year, year)})
                    records.extend(rows)
                    subset = territories[territories["region_istat_code"] == region]
                    for level in forests.MAPPABLE_LEVELS:
                        expected = set(subset.loc[subset.level == level, "territory_id"])
                        numeric = {row["territory_id"] for row in rows if row["territory_level"] == level}
                        coverage.append({"assetId": asset["id"], "period": f"{year}-{year}",
                            "territoryLevel": level, "territoryReferenceYear": year,
                            "territoryGeometryReference": f"istat-{level}-{year}.pmtiles",
                            "expectedTerritoryIds": sorted(expected), "numericTerritoryIds": sorted(numeric),
                            "validNoDataTerritoryIds": sorted(expected & set(nodata))})
    return records, coverage, regions_by_year
