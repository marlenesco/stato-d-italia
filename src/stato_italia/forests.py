from __future__ import annotations

import json
import math
import os
import re
import zipfile
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from hashlib import sha256
from datetime import date, timedelta
from pathlib import Path
from threading import Lock
from time import sleep
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import rasterio
import requests
from pyproj import Transformer
from rasterio.mask import mask
from shapely import wkb
from shapely.geometry import box, mapping
from shapely.ops import transform

from .common import json_dump, now_iso, sha256_file, stable_id
from .download import download
from .ingestion_plan import planned_catalog_check
from .registry import load_source
from .forests_legacy import LEGACY, legacy_enabled, fetch_legacy_forests, legacy_zonal_records, raw_path
from .territories import validate_territory_hierarchy

HRL = load_source("copernicus-forests")
CORINE = load_source("copernicus-corine-forests")
INFC = load_source("infc-2015-forests")
ZONAL_ALGORITHM_VERSION = "forests-zonal-statistics-v3"
MAPPABLE_LEVELS = ("municipality", "province", "region")
CATALOG_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
CATALOG_MAX_ATTEMPTS = 5


def forest_coverage_mode() -> str:
    """Return an explicit coverage policy; national is the safe default."""
    mode = os.getenv(HRL["coverage_mode_environment"], HRL["coverage_default"])
    if mode not in HRL["coverage_modes"]:
        raise ValueError(f"Unsupported {HRL['coverage_mode_environment']}: {mode}")
    return mode


def territory_reference_year_for_period(asset: dict, start_year: int, end_year: int) -> int:
    """Resolve the official geometry year for one source snapshot or change period."""
    if asset["kind"] == "tree_cover_change":
        return end_year
    if start_year != end_year:
        raise ValueError(f"Annual forest asset has a non-annual period: {asset['id']} {start_year}-{end_year}")
    return start_year


def forest_coverage_report_path(destination: Path) -> Path:
    """Sidecar for the complete expected/published/valid-nodata population."""
    return destination.with_suffix(".coverage.json")


def _expected_region_codes(canonical_root: Path, year: int, *, mode: str | None = None) -> set[str]:
    regions = pd.read_parquet(canonical_root / "territories" / f"reference_year={year}" / "region.parquet")
    codes = set(regions["istat_code"].astype(str))
    if not codes:
        raise ValueError("Forest processing lacks ISTAT regions")
    if (mode or forest_coverage_mode()) == "development_slice":
        configured = set(HRL["development_slice"]["region_istat_codes"])
        if not configured <= codes:
            raise ValueError("Configured forest development slice is absent from ISTAT reference")
        return configured
    return codes


def _cdse_token(source: dict) -> str:
    """Request a short-lived CDSE token. Never persist or include it in errors."""
    client_id = os.getenv(source["client_id_environment"])
    client_secret = os.getenv(source["client_secret_environment"])
    if not client_id or not client_secret:
        raise RuntimeError(f"{source['source_id']} requires {source['client_id_environment']} and {source['client_secret_environment']}")
    response = requests.post(
        source["token_url"],
        data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
        timeout=(15, 60),
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    payload = response.json()
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise ValueError("Unexpected CDSE OAuth response: access_token missing")
    return token


class _CdseTokenProvider:
    """Keep a short-lived CDSE token fresh across long concurrent runs."""

    def __init__(self, source: dict) -> None:
        self._source = source
        self._token = _cdse_token(source)
        self._lock = Lock()

    def get(self) -> str:
        with self._lock:
            return self._token

    def refresh(self, stale_token: str) -> str:
        """Refresh once per expired token even when several workers see 401."""
        with self._lock:
            if self._token == stale_token:
                self._token = _cdse_token(self._source)
            return self._token


def _close_response(response: requests.Response) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        close()


def _catalog_retry_delay(response: requests.Response | None, attempt: int) -> float:
    retry_after = getattr(response, "headers", {}).get("Retry-After") if response is not None else None
    if isinstance(retry_after, str):
        try:
            return min(max(float(retry_after), 0), 60)
        except ValueError:
            pass
    return min(2 ** attempt, 16)


def _get_catalog(source: dict, params: dict) -> requests.Response:
    """GET CDSE OData without Sentinel Hub credentials, retrying only transients."""
    last_error: Exception | None = None
    for attempt in range(CATALOG_MAX_ATTEMPTS):
        response: requests.Response | None = None
        try:
            response = requests.get(
                source["catalog_api_url"], params=params, timeout=(15, 90),
                headers={"Accept": "application/json"},
            )
            status = getattr(response, "status_code", None)
            if status in CATALOG_RETRYABLE_STATUSES:
                last_error = requests.HTTPError(
                    f"CDSE catalogue transient product discovery failure: HTTP {status}",
                    response=response,
                )
                delay = _catalog_retry_delay(response, attempt)
                _close_response(response)
            elif status in {401, 403}:
                _close_response(response)
                raise requests.HTTPError(
                    f"CDSE catalogue denied unauthenticated product discovery: HTTP {status}",
                    response=response,
                )
            else:
                response.raise_for_status()
                return response
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError) as exc:
            last_error = exc
            delay = _catalog_retry_delay(None, attempt)
        if attempt < CATALOG_MAX_ATTEMPTS - 1:
            sleep(delay)
    if isinstance(last_error, requests.HTTPError):
        raise last_error
    raise RuntimeError("CDSE catalogue product discovery failed after transient retries") from last_error


def _catalog_products(source: dict) -> list[dict]:
    products: list[dict] = []
    for asset in source["assets"]:
        for start_year, end_year in _asset_periods(asset):
            start = f"{start_year}-01-01T00:00:00.000000Z"
            end = f"{end_year + 1}-01-01T00:00:00.000000Z"
            name_contains = str(asset["catalog_name_contains_template"]).format(start_year=start_year, end_year=end_year)
            name_pattern = re.compile(str(asset["catalog_name_regex_template"]).format(start_year=start_year, end_year=end_year))
            params = {
                "$filter": (
                    "Collection/Name eq 'CLMS' and "
                    f"contains(Name,'{name_contains}') and "
                    f"ContentDate/Start ge {start} and ContentDate/Start lt {end}"
                ),
                "$select": "Id,Name,ContentDate,PublicationDate,ModificationDate,Checksum,S3Path,OriginDate",
                "$orderby": "ContentDate/Start asc,Name asc",
                "$top": "1000",
            }
            response = _get_catalog(source, params)
            try:
                values = response.json().get("value")
            finally:
                _close_response(response)
            if not isinstance(values, list) or not values:
                raise ValueError(f"CDSE catalog has no {asset['id']} snapshot for {start_year}-{end_year}")
            items = []
            for item in values:
                if not isinstance(item, dict) or not isinstance(item.get("Id"), str) or not isinstance(item.get("Name"), str):
                    raise ValueError("Unexpected CDSE OData product shape")
                content_date = item.get("ContentDate")
                if asset.get("snapshot_timestamp") != "content_date_start_at_reference_year":
                    raise ValueError(f"Unsupported CDSE snapshot timestamp contract for {asset['id']}")
                if not name_pattern.fullmatch(item["Name"]):
                    raise ValueError(f"CDSE catalog returned an unexpected product name for {asset['id']}: {item['Name']}")
                if (
                    not isinstance(content_date, dict)
                    or not str(content_date.get("Start", "")).startswith(f"{start_year}-01-01")
                    or not str(content_date.get("End", "")).startswith(f"{end_year}-")
                ):
                    raise ValueError(f"CDSE catalog returned an unexpected timestamp for {asset['id']} {start_year}-{end_year}")
                items.append({key: item.get(key) for key in ("Id", "Name", "ContentDate", "PublicationDate", "ModificationDate", "Checksum", "S3Path", "OriginDate")})
            products.append({"asset_id": asset["id"], "period": [start_year, end_year], "items": sorted(items, key=lambda item: (item["Name"], item["Id"]))})
    if not products:
        raise ValueError("CDSE OData returned no supported Tree Cover & Forest products")
    return sorted(products, key=lambda item: (item["asset_id"], item["period"]))


def _catalog_snapshot(catalog: dict, asset: dict, start_year: int, end_year: int) -> dict:
    matches = [item for item in catalog.get("products_payload", catalog.get("products", [])) if item.get("asset_id") == asset["id"] and item.get("period") == [start_year, end_year]]
    if len(matches) != 1 or not isinstance(matches[0].get("items"), list) or not matches[0]["items"]:
        raise ValueError(f"CDSE catalog snapshot is missing or ambiguous for {asset['id']} {start_year}-{end_year}")
    snapshot = matches[0]
    items = snapshot["items"]
    content_dates = {
        (str(item.get("ContentDate", {}).get("Start", "")), str(item.get("ContentDate", {}).get("End", "")))
        for item in items if isinstance(item, dict)
    }
    if len(content_dates) != 1:
        raise ValueError(f"CDSE catalog has ambiguous content dates for {asset['id']} {start_year}-{end_year}")
    content_start, content_end = content_dates.pop()
    if not content_start or not content_end:
        raise ValueError(f"CDSE catalog content date is not interpretable for {asset['id']} {start_year}-{end_year}")
    signature = sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "assetId": asset["id"], "logicalPeriod": [start_year, end_year],
        "productIds": [str(item["Id"]) for item in items], "productNames": [str(item["Name"]) for item in items],
        "contentDateStart": content_start, "contentDateEnd": content_end,
        "snapshotSignature": signature, "signature": signature, "items": items,
    }


def _catalog_state(root: Path) -> Path:
    return root / "raw" / HRL["source_id"] / "catalog.json"


def _check_catalog(source: dict) -> dict:
    """Read remote catalog and compute signature without changing local state."""
    products = _catalog_products(source)
    signature = sha256(json.dumps(products, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "source_id": source["source_id"], "signature": signature, "products_payload": products,
        "products": len(products), "checked_at": now_iso(),
    }


def _persist_catalog(root: Path, catalog: dict) -> dict:
    """Advance local catalog state only inside the real geospatial run."""
    destination = _catalog_state(root)
    previous = json.loads(destination.read_text()) if destination.exists() else None
    changed = previous is None or previous.get("signature") != catalog["signature"]
    if changed:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps({
            "source_id": catalog["source_id"], "signature": catalog["signature"],
            "products": catalog["products_payload"], "checked_at": catalog["checked_at"],
        }, ensure_ascii=False, separators=(",", ":")) + "\n")
    return {
        "changed": changed, "signature": catalog["signature"],
        "products": catalog["products"], "path": str(destination),
    }


def _asset_periods(asset: dict) -> list[tuple[int, int]]:
    return [(int(year), int(year)) for year in asset.get("years", [])] + [tuple(map(int, period)) for period in asset.get("periods", [])]


def forest_zonal_territory_years() -> frozenset[int]:
    """Resolve unique exact boundary years from enabled HRL logical periods."""
    return frozenset(
        territory_reference_year_for_period(asset, start, end)
        for asset in [*HRL["assets"], *(LEGACY["assets"] if legacy_enabled() else [])] if asset.get("statistical_api_enabled", True)
        for start, end in _asset_periods(asset)
    )


def _process_evalscript(asset: dict) -> str:
    """Keep the source band intact and reserve a distinct nodata value."""
    return (
        "//VERSION=3\n"
        f"function setup() {{ return {{ input: [\"{asset['band']}\", \"dataMask\"], output: {{ bands: 1, sampleType: \"INT16\" }} }}; }}\n"
        f"function evaluatePixel(s) {{ return [s.dataMask ? s.{asset['band']} : {asset['process_no_data']}]; }}"
    )


def _process_tile_grid(geometry_wkb: bytes, resolution_m: int, max_pixels: int) -> list[tuple[tuple[float, float, float, float], int, int, int, int]]:
    """Produce an EPSG:3035-aligned, non-overlapping grid for one region."""
    if resolution_m <= 0 or max_pixels <= 0:
        raise ValueError("Process raster resolution and maximum pixels must be positive")
    project = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True).transform
    minx, miny, maxx, maxy = transform(project, wkb.loads(geometry_wkb)).bounds
    minx = math.floor(minx / resolution_m) * resolution_m
    miny = math.floor(miny / resolution_m) * resolution_m
    maxx = math.ceil(maxx / resolution_m) * resolution_m
    maxy = math.ceil(maxy / resolution_m) * resolution_m
    columns = math.ceil((maxx - minx) / (resolution_m * max_pixels))
    rows = math.ceil((maxy - miny) / (resolution_m * max_pixels))
    tiles: list[tuple[tuple[float, float, float, float], int, int, int, int]] = []
    for row in range(rows):
        for column in range(columns):
            left = minx + column * resolution_m * max_pixels
            bottom = miny + row * resolution_m * max_pixels
            right = min(maxx, left + resolution_m * max_pixels)
            top = min(maxy, bottom + resolution_m * max_pixels)
            tiles.append(((left, bottom, right, top), round((right - left) / resolution_m), round((top - bottom) / resolution_m), row, column))
    return tiles


def _source_time_range(asset: dict, snapshot: dict) -> dict[str, str]:
    """Resolve the source interval from catalog provenance, never logical years."""
    timestamp = snapshot.get("contentDateStart")
    content_end = snapshot.get("contentDateEnd")
    if not isinstance(timestamp, str) or not isinstance(content_end, str):
        raise ValueError(f"CDSE catalog snapshot lacks an interpretable time range for {asset['id']}")
    # Annual HRL snapshots retain their established single-source-date request.
    # TCPC is a change product: its catalogued content interval is authoritative.
    end = content_end if asset["kind"] == "tree_cover_change" else f"{(date.fromisoformat(timestamp[:10]) + timedelta(days=1)).isoformat()}T00:00:00Z"
    return {"from": timestamp, "to": end}


def _process_payload(asset: dict, bbox: tuple[float, float, float, float], width: int, height: int, snapshot: dict) -> dict:
    time_range = _source_time_range(asset, snapshot)
    return {
        "input": {
            "bounds": {"bbox": list(bbox), "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/3035"}},
            "data": [{"type": f"byoc-{asset['byoc_collection_id']}", "dataFilter": {"timeRange": time_range}}],
        },
        "output": {"width": width, "height": height, "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}]},
        "evalscript": _process_evalscript(asset),
    }


def _process_request_contract(
    asset: dict, bbox: tuple[float, float, float, float], width: int, height: int,
    snapshot: dict, reference_year: int, region_istat_code: str,
    start_year: int, end_year: int,
) -> tuple[dict, str, dict]:
    """Bind a reusable raster slice to its exact CDSE Process request."""
    payload = _process_payload(asset, bbox, width, height, snapshot)
    request_sha256 = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    expected = {
        "asset_id": asset["id"], "period": [start_year, end_year],
        "territory_reference_year": reference_year, "region_istat_code": region_istat_code,
        "bbox_epsg3035": list(bbox), "width": width, "height": height,
        "snapshot_signature": snapshot["signature"], "process_request_sha256": request_sha256,
    }
    return payload, request_sha256, expected


def _legacy_annual_slice_matches(
    prior: dict, expected: dict, snapshot: dict, asset: dict, target: Path,
) -> bool:
    """Reuse pre-v2 annual slices only after a complete semantic verification."""
    if asset["kind"] == "tree_cover_change" or prior.get("sha256") != sha256_file(target):
        return False
    prior_request = prior.get("request")
    if not isinstance(prior_request, dict):
        return False
    legacy_expected = {key: value for key, value in expected.items() if key not in {"territory_reference_year", "process_request_sha256", "snapshot_signature"}}
    prior_request = {key: value for key, value in prior_request.items() if key != "snapshot_signature"}
    if prior_request != legacy_expected:
        return False
    old_snapshot = prior.get("snapshot")
    if not isinstance(old_snapshot, dict) or not isinstance(old_snapshot.get("items"), list):
        return False
    old_items = [{key: item.get(key) for key in ("Id", "Name", "ContentDate")} for item in old_snapshot["items"] if isinstance(item, dict)]
    new_items = [{key: item.get(key) for key in ("Id", "Name", "ContentDate")} for item in snapshot["items"] if isinstance(item, dict)]
    return bool(old_items) and old_items == new_items


def _post_process_raster(payload: dict, token: str) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            response = requests.post(HRL["process_api_url"], json=payload, headers={"Accept": "image/tiff", "Authorization": f"Bearer {token}"}, timeout=(15, 300))
            if response.status_code not in {429, 500, 502, 503, 504}:
                return response
            retry_after = response.headers.get("Retry-After")
            last_error = requests.HTTPError(f"CDSE Processing API transient status {response.status_code}")
            response.close()
            delay = min(float(retry_after), 120) if retry_after and retry_after.replace(".", "", 1).isdigit() else min(2 ** attempt, 60)
        except requests.RequestException as exc:
            last_error = exc
            delay = min(2 ** attempt, 60)
        if attempt < 5:
            sleep(delay)
    raise RuntimeError("CDSE Processing API failed after transient retries") from last_error


def _process_slice_path(root: Path, asset: dict, start_year: int, end_year: int, region_istat_code: str, row: int, column: int) -> Path:
    return root / "raw" / HRL["source_id"] / asset["id"] / f"{start_year}-{end_year}" / region_istat_code / f"r{row:02d}-c{column:02d}.tif"


def _fetch_process_raster_slices(
    root: Path, canonical_root: Path, token: str, catalog: dict, *, force: bool = False,
) -> dict:
    """Acquire resumable Process API slices for the configured national coverage."""
    changed = False
    requests_made = 0
    tiles_reused = 0
    bytes_downloaded = 0
    request_plan: dict[str, dict[str, int]] = {}
    files: list[dict] = []
    raw_files: list[str] = []
    assets = [asset for asset in HRL["assets"] if asset.get("statistical_api_enabled", True)]
    for asset in assets:
        for start_year, end_year in _asset_periods(asset):
            snapshot = _catalog_snapshot(catalog, asset, start_year, end_year)
            reference_year = territory_reference_year_for_period(asset, start_year, end_year)
            territories = _slice_territories(canonical_root, reference_year)
            regions = territories[territories["level"] == "region"]
            selected = _expected_region_codes(canonical_root, reference_year)
            if set(regions["istat_code"]) != selected:
                raise ValueError(f"Forest process slice lacks configured ISTAT regions for {reference_year}")
            plan_key = f"{asset['id']}:{start_year}-{end_year}"
            request_plan.setdefault(plan_key, {"assetId": asset["id"], "period": f"{start_year}-{end_year}", "territoryReferenceYear": reference_year, "planned": 0, "executed": 0, "reused": 0})
            for region in regions.sort_values("istat_code").to_dict("records"):
                manifest_path = _process_slice_path(root, asset, start_year, end_year, region["istat_code"], 0, 0).parent / "slice-manifest.json"
                entries: list[dict] = []
                for bbox, width, height, row, column in _process_tile_grid(region["geometry_wkb"], int(asset["process_resolution_m"]), int(asset["process_max_pixels"])):
                    request_plan[plan_key]["planned"] += 1
                    target = _process_slice_path(root, asset, start_year, end_year, region["istat_code"], row, column)
                    sidecar = target.with_suffix(target.suffix + ".metadata.json")
                    payload, process_request_sha256, expected = _process_request_contract(
                        asset, bbox, width, height, snapshot, reference_year,
                        str(region["istat_code"]), start_year, end_year,
                    )
                    prior = json.loads(sidecar.read_text()) if target.exists() and sidecar.exists() else None
                    if prior and prior.get("request") == expected and prior.get("processRequestSha256") == process_request_sha256 and prior.get("sha256") == sha256_file(target):
                        metadata = prior
                        tiles_reused += 1
                        request_plan[plan_key]["reused"] += 1
                    elif prior and _legacy_annual_slice_matches(prior, expected, snapshot, asset, target):
                        metadata = prior | {"request": expected, "snapshot": snapshot, "processRequestSha256": process_request_sha256}
                        json_dump(sidecar, metadata)
                        changed = True
                        tiles_reused += 1
                        request_plan[plan_key]["reused"] += 1
                    else:
                        with _post_process_raster(payload, token) as response:
                            response.raise_for_status()
                            content_type = response.headers.get("Content-Type", "")
                            if not content_type.startswith("image/tiff") or response.content[:4] not in {b"II*\x00", b"MM\x00*"}:
                                raise ValueError(f"Unexpected CDSE Processing API raster response for {asset['id']}")
                            target.parent.mkdir(parents=True, exist_ok=True)
                            temporary = target.with_suffix(target.suffix + ".partial")
                            temporary.write_bytes(response.content)
                            temporary.replace(target)
                            metadata = {
                                "source_id": HRL["source_id"], "acquisition_mode": "cdse_process_api_raster_slice",
                                "acquired_at": now_iso(), "requested_url": HRL["process_api_url"], "resolved_url": HRL["process_api_url"],
                                "content_type": content_type, "bytes": target.stat().st_size, "sha256": sha256_file(target),
                                "request": expected, "asset_id": asset["id"], "band": asset["band"], "byoc_collection_id": asset["byoc_collection_id"], "snapshot": snapshot,
                                "processRequestSha256": process_request_sha256,
                                "source_resolution_m": asset["resolution_m"], "slice_resolution_m": asset["process_resolution_m"],
                                "license": HRL["license"], "methodology_url": HRL["methodology_url"],
                            }
                            json_dump(sidecar, metadata)
                            changed = True
                            requests_made += 1
                            bytes_downloaded += target.stat().st_size
                            request_plan[plan_key]["executed"] += 1
                    entries.append({"path": target.name, "sha256": metadata["sha256"], "bytes": metadata["bytes"], "request": expected})
                    raw_files.extend([str(target), str(sidecar)])
                signature = sha256(json.dumps({"asset_id": asset["id"], "period": [start_year, end_year], "territory_reference_year": reference_year, "territory_geometry_reference": f"istat-region-{reference_year}.pmtiles", "region_istat_code": region["istat_code"], "snapshot_signature": snapshot["signature"], "entries": entries}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                manifest = {"schemaVersion": 2, "source_id": HRL["source_id"], "asset_id": asset["id"], "period": [start_year, end_year], "territoryReferenceYear": reference_year, "territoryGeometryReference": f"istat-region-{reference_year}.pmtiles", "region_istat_code": region["istat_code"], "slice_resolution_m": asset["process_resolution_m"], "source_signature": signature, "snapshot_signature": snapshot["signature"], "snapshot": snapshot, "entries": entries}
                prior_manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
                if prior_manifest != manifest:
                    json_dump(manifest_path, manifest)
                    changed = True
                raw_files.append(str(manifest_path))
                files.append({"path": str(manifest_path), "bytes": sum(item["bytes"] for item in entries), "tiles": len(entries), "asset": asset["id"], "period": f"{start_year}-{end_year}", "region": region["istat_code"]})
    return {
        "changed": changed, "requests": requests_made, "requests_planned": sum(item["planned"] for item in request_plan.values()),
        "tiles_reused": tiles_reused, "tiles_downloaded": requests_made, "bytes_downloaded": bytes_downloaded,
        "request_plan": list(request_plan.values()), "files": files, "raw_files": raw_files,
        "raw_bytes": sum(item["bytes"] for item in files),
    }


def forest_process_request_plan(canonical_root: Path) -> list[dict]:
    """Calculate the actual national Process API request plan from ISTAT geometry."""
    plan: list[dict] = []
    for asset in HRL["assets"]:
        if not asset.get("statistical_api_enabled", True):
            continue
        for start_year, end_year in _asset_periods(asset):
            reference_year = territory_reference_year_for_period(asset, start_year, end_year)
            regions = _slice_territories(canonical_root, reference_year)
            regions = regions[regions["level"] == "region"]
            planned = sum(
                len(_process_tile_grid(region["geometry_wkb"], int(asset["process_resolution_m"]), int(asset["process_max_pixels"])))
                for region in regions.to_dict("records")
            )
            plan.append({"assetId": asset["id"], "period": f"{start_year}-{end_year}", "territoryReferenceYear": reference_year, "planned": planned})
    return plan


def fetch_forests(root: Path, offline: bool = False, *, check_geospatial: bool = True, include_infc: bool = True) -> dict:
    """Acquire INFC, check CDSE, and optionally retain bounded local raster slices."""
    infc = []
    if include_infc:
        for asset in INFC["assets"]:
            target = root / "raw" / INFC["source_id"] / f"{asset['id']}.zip"
            infc.append(download(asset["url"], target, INFC["source_id"], offline=offline, user_agent=INFC["download_user_agent"], source_context={"asset_id": asset["id"], "metric_id": asset["metric_id"]}))
    legacy = fetch_legacy_forests(root, offline=offline) if check_geospatial and legacy_enabled() else []
    if offline:
        return {"legacy": legacy, "infc": infc, "catalog": {"status": "offline"}, "raw_retention": os.getenv("FORESTS_RAW_RETENTION", HRL["raw_retention_default"])}
    if not check_geospatial:
        return {"legacy": legacy, "infc": infc, "catalog": {"status": "deferred"}, "raw_retention": os.getenv("FORESTS_RAW_RETENTION", HRL["raw_retention_default"])}
    planned_catalog = planned_catalog_check()
    catalog_check = planned_catalog or _check_catalog(HRL)
    catalog = _persist_catalog(root, catalog_check)
    raster = None
    if os.getenv(HRL["processing_mode_environment"], "raster") == "raster":
        if not os.getenv(HRL["client_id_environment"]) or not os.getenv(HRL["client_secret_environment"]):
            return {"legacy": legacy, "infc": infc, "catalog": catalog | {"status": "blocked", "reason": "CDSE OAuth credentials unavailable"}, "raw_retention": os.getenv("FORESTS_RAW_RETENTION", HRL["raw_retention_default"])}
        token = _cdse_token(HRL)
        raster = _fetch_process_raster_slices(
            root, root / "canonical", token, catalog_check, force=planned_catalog is not None,
        )
    return {"legacy": legacy, "infc": infc, "catalog": catalog, "raster": raster, "raw_retention": os.getenv("FORESTS_RAW_RETENTION", HRL["raw_retention_default"])}


def declared_forest_raw_paths(root: Path) -> list[Path]:
    """Declare only raw artifacts implied by the current Forest configuration."""
    paths: list[Path] = []
    for asset in INFC["assets"]:
        raw = root / "raw" / INFC["source_id"] / f"{asset['id']}.zip"
        paths.extend((raw, raw.with_suffix(raw.suffix + ".metadata.json")))
    if legacy_enabled():
        for asset in LEGACY["assets"]:
            for year in asset["years"]:
                raw = raw_path(root, asset, year)
                paths.extend((raw, raw.with_suffix(".zip.metadata.json")))
    paths.append(_catalog_state(root))
    if os.getenv(HRL["processing_mode_environment"], "raster") != "raster":
        return paths
    for asset in HRL["assets"]:
        if not asset.get("statistical_api_enabled", True):
            continue
        for start_year, end_year in _asset_periods(asset):
            reference_year = territory_reference_year_for_period(asset, start_year, end_year)
            for region_code in sorted(_expected_region_codes(root / "canonical", reference_year)):
                manifest = _process_slice_path(root, asset, start_year, end_year, region_code, 0, 0).parent / "slice-manifest.json"
                if not manifest.is_file():
                    raise FileNotFoundError(f"Declared CDSE Process API slice manifest missing: {manifest}")
                payload = json.loads(manifest.read_text())
                if (
                    payload.get("source_id") != HRL["source_id"]
                    or payload.get("asset_id") != asset["id"]
                    or payload.get("period") != [start_year, end_year]
                    or payload.get("region_istat_code") != region_code
                    or not isinstance(payload.get("entries"), list)
                ):
                    raise ValueError(f"Declared CDSE Process API slice manifest mismatch: {manifest}")
                paths.append(manifest)
                for entry in payload["entries"]:
                    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                        raise ValueError(f"Invalid CDSE Process API slice entry: {manifest}")
                    raw = manifest.parent / entry["path"]
                    if raw.parent != manifest.parent:
                        raise ValueError(f"CDSE Process API slice path escapes manifest directory: {manifest}")
                    paths.extend((raw, raw.with_suffix(raw.suffix + ".metadata.json")))
    return paths


def _year_from_path(path: Path) -> int:
    values = [int(value) for value in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", path.name)]
    if len(values) != 1:
        raise ValueError(f"Raster filename must contain exactly one reference year: {path.name}")
    return values[0]


def _reference_years_for_asset(asset: dict, path: Path) -> tuple[int, int]:
    if asset["kind"] == "tree_cover_change":
        values = [int(value) for value in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", path.name)]
        if len(values) != 2:
            raise ValueError(f"Change raster filename must contain start and end year: {path.name}")
        return tuple(values)  # type: ignore[return-value]
    year = _year_from_path(path)
    return year, year


def _pixels(dataset: rasterio.io.DatasetReader, geometry_wkb: bytes) -> np.ndarray:
    geometry = wkb.loads(geometry_wkb)
    if dataset.crs is None:
        raise ValueError(f"Raster lacks CRS: {dataset.name}")
    project = Transformer.from_crs("EPSG:4326", dataset.crs, always_xy=True).transform
    cropped, _ = mask(dataset, [mapping(transform(project, geometry))], crop=True, filled=False)
    values = cropped[0]
    return values.compressed() if np.ma.isMaskedArray(values) else values.ravel()


def _territory_area_ha(geometry_wkb: bytes, dataset: rasterio.io.DatasetReader) -> float:
    geometry = wkb.loads(geometry_wkb)
    project = Transformer.from_crs("EPSG:4326", dataset.crs, always_xy=True).transform
    area = transform(project, geometry).area / 10_000
    if area <= 0:
        raise ValueError("ISTAT territory geometry has non-positive area")
    return float(area)


def _pixel_area_ha(dataset: rasterio.io.DatasetReader) -> float:
    if not dataset.crs or not dataset.crs.is_projected:
        raise ValueError(f"Zonal area requires projected raster CRS: {dataset.name}")
    return abs(dataset.transform.a * dataset.transform.e) / 10_000


def _record(asset: dict, path: Path | str, source_hash: str, territory: dict, metric_id: str, value: float, start_year: int, end_year: int) -> dict:
    units = {"forest_cover_hrl": "ha", "forest_cover_corine": "ha", "forest_area_ha": "ha", "forest_share_pct": "%", "tree_cover_mean": "%", "tree_cover_p25": "%", "tree_cover_p50": "%", "tree_cover_p75": "%", "broadleaved_area_hrl_ha": "ha", "coniferous_area_hrl_ha": "ha", "mixed_forest_area_hrl_ha": "ha", "broadleaved_area_dlt_ha": "ha", "coniferous_area_dlt_ha": "ha", "broadleaved_area_corine_ha": "ha", "coniferous_area_corine_ha": "ha", "mixed_forest_area_corine_ha": "ha", "tree_cover_gain_ha": "ha", "tree_cover_loss_ha": "ha"}
    return {
        "derived_metric_id": stable_id(ZONAL_ALGORITHM_VERSION, source_hash, territory["territory_version_id"], metric_id, start_year, end_year),
        "dataset_id": asset["source_id"], "source_asset_sha256": source_hash, "source_row_locator": f"{path}:{territory['territory_id']}",
        "metric_id": metric_id, "territory_id": territory["territory_id"], "territory_version_id": territory["territory_version_id"],
        "territory_level": territory["level"], "period_start": date(start_year, 1, 1).isoformat(), "period_end": date(end_year, 12, 31).isoformat(),
        "reference_year": end_year, "value_decimal": value, "unit_ucum": units[metric_id], "value_state": "observed", "official_status": "derived_by_stato_italia",
        "algorithm_version": ZONAL_ALGORITHM_VERSION, "methodology_version": asset["id"], "quality_flags": [], "ingested_at": now_iso(),
    }


def _raster_records(asset: dict, path: Path, source_hash: str, territories: pd.DataFrame) -> list[dict]:
    start, end = _reference_years_for_asset(asset, path)
    rows: list[dict] = []
    with rasterio.open(path) as dataset:
        pixel_area = _pixel_area_ha(dataset)
        for territory in territories.to_dict("records"):
            values = _pixels(dataset, territory["geometry_wkb"])
            if not len(values):
                continue
            values = _valid_source_values(asset, values)
            if not len(values):
                continue
            def add(metric: str, value: float) -> None:
                rows.append(_record(asset, path, source_hash, territory, metric, float(value), start, end))
            if asset["kind"] == "tree_cover_density":
                for metric, value in (("tree_cover_mean", np.mean(values)), ("tree_cover_p25", np.quantile(values, .25)), ("tree_cover_p50", np.quantile(values, .5)), ("tree_cover_p75", np.quantile(values, .75))): add(metric, value)
            elif asset["kind"] == "forest_type":
                codes = asset["class_codes"]
                broad = float(np.count_nonzero(values == codes["broadleaved"]) * pixel_area)
                conifer = float(np.count_nonzero(values == codes["coniferous"]) * pixel_area)
                mixed = float(np.count_nonzero(values == codes.get("mixed", -1)) * pixel_area)
                total = broad + conifer + mixed
                add("forest_cover_hrl", total); add("forest_area_ha", total); add("forest_share_pct", total / _territory_area_ha(territory["geometry_wkb"], dataset) * 100)
                add("broadleaved_area_hrl_ha", broad); add("coniferous_area_hrl_ha", conifer); add("mixed_forest_area_hrl_ha", mixed)
            elif asset["kind"] == "corine_forest":
                broad = float(np.count_nonzero(values == 311) * pixel_area); conifer = float(np.count_nonzero(values == 312) * pixel_area); mixed = float(np.count_nonzero(values == 313) * pixel_area)
                add("forest_cover_corine", broad + conifer + mixed); add("broadleaved_area_corine_ha", broad); add("coniferous_area_corine_ha", conifer); add("mixed_forest_area_corine_ha", mixed)
            elif asset["kind"] == "tree_cover_change":
                codes = asset["class_codes"]
                add("tree_cover_gain_ha", float(np.count_nonzero(values == codes["new_tree_cover"]) * pixel_area)); add("tree_cover_loss_ha", float(np.count_nonzero(values == codes["loss_tree_cover"]) * pixel_area))
            elif asset["kind"] == "dominant_leaf_type":
                codes = asset["class_codes"]
                add("broadleaved_area_dlt_ha", float(np.count_nonzero(values == codes["broadleaved"]) * pixel_area)); add("coniferous_area_dlt_ha", float(np.count_nonzero(values == codes["coniferous"]) * pixel_area))
            else: raise ValueError(f"Unknown forest raster kind: {asset['kind']}")
    return rows


def _raster_files(root: Path, source: dict, asset: dict) -> list[Path]:
    files = sorted((root / "raw" / source["source_id"] / asset["id"]).glob("**/*"))
    rasters = [path for path in files if path.suffix.lower() in {".tif", ".tiff"}]
    if not rasters:
        return []
    return rasters


def _process_raster_groups(root: Path, asset: dict) -> list[dict]:
    """Read only complete, checksummed Process API slice manifests."""
    manifests = sorted((root / "raw" / HRL["source_id"] / asset["id"]).glob("*/*/slice-manifest.json"))
    groups: list[dict] = []
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text())
        if (
            manifest.get("schemaVersion") != 2
            or manifest.get("source_id") != HRL["source_id"]
            or manifest.get("asset_id") != asset["id"]
            or not isinstance(manifest.get("period"), list)
            or len(manifest["period"]) != 2
            or not isinstance(manifest.get("region_istat_code"), str)
            or not isinstance(manifest.get("territoryReferenceYear"), int)
            or manifest.get("territoryGeometryReference") != f"istat-region-{manifest.get('territoryReferenceYear')}.pmtiles"
            or not isinstance(manifest.get("source_signature"), str)
            or len(manifest["source_signature"]) != 64
            or not isinstance(manifest.get("entries"), list)
            or not manifest["entries"]
        ):
            raise ValueError(f"Invalid CDSE Process API slice manifest: {manifest_path}")
        paths: list[Path] = []
        for entry in manifest["entries"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("sha256"), str):
                raise ValueError(f"Invalid CDSE Process API slice entry: {manifest_path}")
            path = manifest_path.parent / entry["path"]
            if not path.exists() or sha256_file(path) != entry["sha256"]:
                raise ValueError(f"CDSE Process API slice checksum mismatch: {path}")
            paths.append(path)
        snapshot_signature = manifest.get("snapshot_signature")
        if not isinstance(snapshot_signature, str) or len(snapshot_signature) != 64:
            raise ValueError(f"CDSE Process API slice snapshot provenance missing: {manifest_path}")
        groups.append({"manifest_path": manifest_path, "source_hash": manifest["source_signature"], "snapshot_signature": snapshot_signature, "region_istat_code": manifest["region_istat_code"], "territory_reference_year": int(manifest["territoryReferenceYear"]), "territory_geometry_reference": manifest["territoryGeometryReference"], "start_year": int(manifest["period"][0]), "end_year": int(manifest["period"][1]), "paths": paths})
    return groups


def _valid_source_values(asset: dict, values: np.ndarray) -> np.ndarray:
    """Exclude processing and documented source NoData while preserving real zero."""
    result = values[np.isfinite(values)]
    if "process_no_data" in asset:
        result = result[result != asset["process_no_data"]]
    allowed_codes = asset.get("source_value_codes")
    if allowed_codes is not None:
        if not isinstance(allowed_codes, list) or not all(isinstance(code, (int, float)) for code in allowed_codes):
            raise ValueError(f"Invalid source value-code contract for {asset['id']}")
        unexpected = result[~np.isin(result, allowed_codes)]
        if len(unexpected):
            raise ValueError(f"Unexpected source raster class for {asset['id']}: {sorted(set(unexpected.tolist()))}")
    source_nodata = asset.get("source_nodata_codes", [])
    if not isinstance(source_nodata, list) or not all(isinstance(code, (int, float)) for code in source_nodata):
        raise ValueError(f"Invalid source NoData contract for {asset['id']}")
    if source_nodata:
        result = result[~np.isin(result, source_nodata)]
    return result


def _slice_territories_with_region_code(canonical_root: Path, year: int) -> pd.DataFrame:
    territories = _slice_territories(canonical_root, year).copy()
    provinces = territories[territories["level"] == "province"]
    province_regions = dict(zip(provinces["istat_code"], provinces["parent_istat_code"], strict=True))

    def region_code(record: pd.Series) -> str:
        if record["level"] == "region":
            return str(record["istat_code"])
        if record["level"] == "province":
            return str(record["parent_istat_code"])
        return str(province_regions[record["parent_istat_code"]])

    territories["region_istat_code"] = territories.apply(region_code, axis=1)
    return territories


def _process_raster_records(asset: dict, group: dict, territories: pd.DataFrame) -> tuple[list[dict], list[str]]:
    """Aggregate chunks; preserve legitimate raster NoData separately from gaps."""
    subset = territories[territories["region_istat_code"] == group["region_istat_code"]]
    if subset.empty:
        raise ValueError(f"Process slice has no configured territory: {group['region_istat_code']}")
    rows: list[dict] = []
    valid_nodata: list[str] = []
    with rasterio.open(group["paths"][0]) as first:
        if first.crs is None or not first.crs.is_projected:
            raise ValueError(f"CDSE Process API slice lacks projected CRS: {first.name}")
        pixel_area = _pixel_area_ha(first)
        crs = first.crs
    datasets = [rasterio.open(path) for path in group["paths"]]
    try:
        for dataset in datasets:
            if dataset.crs != crs or not math.isclose(_pixel_area_ha(dataset), pixel_area):
                raise ValueError(f"Incompatible CDSE Process API slice tiles: {dataset.name}")
        project = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
        for territory in subset.to_dict("records"):
            geometry = transform(project, wkb.loads(territory["geometry_wkb"]))
            values_by_chunk: list[np.ndarray] = []
            for dataset in datasets:
                if not geometry.intersects(box(*dataset.bounds)):
                    continue
                try:
                    cropped, _ = mask(dataset, [mapping(geometry)], crop=True, filled=False)
                except ValueError:
                    continue
                values = cropped[0]
                values = values.compressed() if np.ma.isMaskedArray(values) else values.ravel()
                values = _valid_source_values(asset, values)
                if len(values):
                    values_by_chunk.append(values)
            if not values_by_chunk:
                # A masked/no-data territory is an observed source state, not a
                # silently missing processing result. It is accounted for in the
                # coverage sidecar and never promoted as a numeric observation.
                valid_nodata.append(str(territory["territory_id"]))
                continue
            values = np.concatenate(values_by_chunk)

            def add(metric: str, value: float) -> None:
                record = _record(asset | {"source_id": asset.get("source_id", HRL["source_id"])}, group["manifest_path"].relative_to(group["manifest_path"].parents[4]), group["source_hash"], territory, metric, float(value), group["start_year"], group["end_year"])
                record["source_snapshot_signature"] = group["snapshot_signature"]
                rows.append(record)

            if asset["kind"] == "tree_cover_density":
                add("tree_cover_mean", np.mean(values))
                add("tree_cover_p25", np.quantile(values, .25))
                add("tree_cover_p50", np.quantile(values, .5))
                add("tree_cover_p75", np.quantile(values, .75))
            elif asset["kind"] == "forest_type":
                codes = asset["class_codes"]
                broad = float(np.count_nonzero(values == codes["broadleaved"]) * pixel_area)
                conifer = float(np.count_nonzero(values == codes["coniferous"]) * pixel_area)
                mixed = float(np.count_nonzero(values == codes["mixed"]) * pixel_area)
                total = broad + conifer + mixed
                area_ha = geometry.area / 10_000
                if area_ha <= 0:
                    raise ValueError(f"ISTAT territory geometry has non-positive area: {territory['territory_version_id']}")
                add("forest_cover_hrl", total)
                add("forest_area_ha", total)
                add("forest_share_pct", total / area_ha * 100)
                add("broadleaved_area_hrl_ha", broad)
                add("coniferous_area_hrl_ha", conifer)
                add("mixed_forest_area_hrl_ha", mixed)
            elif asset["kind"] == "tree_cover_change":
                codes = asset["class_codes"]
                add("tree_cover_gain_ha", np.count_nonzero(values == codes["new_tree_cover"]) * pixel_area)
                add("tree_cover_loss_ha", np.count_nonzero(values == codes["loss_tree_cover"]) * pixel_area)
            else:
                raise ValueError(f"Unsupported CDSE Process API raster kind: {asset['kind']}")
    finally:
        for dataset in datasets:
            dataset.close()
    return rows, valid_nodata


def _infc_rows(root: Path, canonical_root: Path) -> list[dict]:
    """Read only published national/regional total-forest tables, never microdata."""
    from .common import normalize_name
    from .territories import load_territory_index
    index = load_territory_index(canonical_root, 2015)
    regions = {normalize_name(item["name"]): item for item in index.values() if item["level"] == "region"}
    aliases = {normalize_name(key): normalize_name(value) for key, value in INFC.get("region_aliases", {}).items()}
    units = {"forest_volume_infc": "m3", "forest_volume_increment_infc": "m3/year", "forest_biomass_infc": "Mg", "forest_carbon_infc": "Mg"}
    rows: list[dict] = []
    for asset in INFC["assets"]:
        archive = root / "raw" / INFC["source_id"] / f"{asset['id']}.zip"
        metadata = json.loads(archive.with_suffix(".zip.metadata.json").read_text())
        with zipfile.ZipFile(archive) as source:
            files = sorted(name for name in source.namelist() if name.lower().endswith((".xlsx", ".xls")))
            if len(files) != 3 or not files[0].endswith(".1_2015.xlsx"):
                raise ValueError(f"Unexpected INFC archive contract for {asset['id']}: {files}")
            frame = pd.read_excel(source.open(files[0]), header=None)
        header_row = next((i for i, value in enumerate(frame.iloc[:, 0]) if isinstance(value, str) and "Region" in value), None)
        if header_row is None: raise ValueError(f"Unexpected INFC table contract: Region header missing in {files[0]}")
        total_column = next((column for column in range(1, frame.shape[1]) if any("Total Forest" in str(frame.iat[row, column]) or "Totale Bosco" in str(frame.iat[row, column]) for row in range(header_row, min(header_row + 4, len(frame))))), None)
        if total_column is None: raise ValueError(f"Unexpected INFC table contract: Total Forest column missing in {files[0]}")
        for row_number in range(header_row + 4, len(frame)):
            name, value = frame.iat[row_number, 0], frame.iat[row_number, total_column]
            if not isinstance(name, str) or pd.isna(value): continue
            normalized = normalize_name(name)
            territory = index["it:country:IT"] if normalized == "italia" else regions.get(aliases.get(normalized, normalized))
            if territory is None: continue
            try: numeric = float(value)
            except (TypeError, ValueError): continue
            rows.append({
                "observation_id": stable_id(INFC["source_id"], metadata["sha256"], files[0], row_number, asset["metric_id"]),
                "dataset_id": INFC["source_id"], "dataset_version": "infc2015-published-tables", "source_asset_sha256": metadata["sha256"],
                "source_row_locator": f"{files[0]}:row={row_number + 1}:column={total_column + 1}", "metric_id": asset["metric_id"],
                "territory_id": territory["territory_id"], "territory_version_id": territory["territory_version_id"], "territory_level": territory["level"],
                "period_start": "2015-01-01", "period_end": "2015-12-31", "reference_year": 2015, "value_decimal": numeric, "value_state": "observed",
                "unit_ucum": units[asset["metric_id"]], "official_status": "published_official_statistics", "quality_flags": [],
                "methodology_version": "infc2015", "ingested_at": metadata["acquired_at"],
            })
    return rows


def ingest_infc_forests(root: Path, canonical_root: Path, force: bool = False) -> dict:
    destination = canonical_root / "forests" / "dataset_version=infc2015-published-tables" / "observations.parquet"
    if destination.exists() and not force:
        table = pd.read_parquet(destination)
        return {"changed": False, "records": len(table), "canonical_bytes": destination.stat().st_size, "records_by_level": table.groupby("territory_level").size().to_dict()}
    rows = _infc_rows(root, canonical_root)
    if not rows: raise ValueError("INFC published tables produced no official observations")
    table = pd.DataFrame(rows)
    # INFC publishes Trento and Bolzano separately. Do not fabricate a regional
    # aggregate for Trentino-Alto Adige/Südtirol from those two official rows.
    expected = len(INFC["assets"]) * 20
    if len(table) != expected or table.duplicated(["observation_id"]).any():
        raise ValueError(f"Unexpected INFC published-table coverage: records={len(table)}, expected={expected}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(destination, index=False, compression="zstd")
    return {"changed": True, "records": len(table), "canonical_bytes": destination.stat().st_size, "records_by_level": table.groupby("territory_level").size().to_dict()}


def _slice_territories(canonical_root: Path, year: int) -> pd.DataFrame:
    """Return the national ISTAT population, or an explicitly selected dev slice."""
    frames = {level: pd.read_parquet(canonical_root / "territories" / f"reference_year={year}" / f"{level}.parquet") for level in MAPPABLE_LEVELS}
    validate_territory_hierarchy(frames)
    selected_regions = _expected_region_codes(canonical_root, year)
    regions = frames["region"][frames["region"]["istat_code"].isin(selected_regions)]
    provinces = frames["province"][frames["province"]["parent_istat_code"].isin(selected_regions)]
    municipalities = frames["municipality"][frames["municipality"]["parent_istat_code"].isin(set(provinces["istat_code"]))]
    province_regions = dict(zip(frames["province"]["istat_code"].astype(str), frames["province"]["parent_istat_code"].astype(str), strict=True))
    expected_municipalities = frames["municipality"][
        frames["municipality"]["parent_istat_code"].astype(str).map(province_regions).isin(selected_regions)
    ]
    if set(municipalities["territory_id"]) != set(expected_municipalities["territory_id"]):
        raise ValueError("Forest territory selection would exclude canonical municipalities")
    if forest_coverage_mode() == "national" and len(municipalities) != len(frames["municipality"]):
        raise ValueError("National forest territory selection does not include every canonical municipality")
    result = pd.concat([municipalities, provinces, regions], ignore_index=True)
    if result.empty or result.duplicated(["territory_id", "territory_version_id"]).any():
        raise ValueError("Invalid configured forest territory coverage")
    return result


def _stats_evalscript(asset: dict) -> str:
    band = asset["band"]
    if asset["kind"] == "tree_cover_density":
        return f"//VERSION=3\nfunction setup() {{ return {{ input: [\"{band}\", \"dataMask\"], output: [{{ id: \"default\", bands: 1, sampleType: \"FLOAT32\" }}, {{ id: \"dataMask\", bands: 1 }}] }}; }}\nfunction evaluatePixel(s) {{ return {{ default: [s.{band}], dataMask: [s.dataMask] }}; }}"
    codes = asset["class_codes"]
    classes = [(name, code) for name, code in codes.items() if name not in {"non_forest", "non_tree"}]
    outputs = ", ".join(f"s.{band} === {code} ? 1 : 0" for _, code in classes)
    return f"//VERSION=3\nfunction setup() {{ return {{ input: [\"{band}\", \"dataMask\"], output: [{{ id: \"default\", bands: {len(classes)}, sampleType: \"UINT8\" }}, {{ id: \"dataMask\", bands: 1 }}] }}; }}\nfunction evaluatePixel(s) {{ return {{ default: [{outputs}], dataMask: [s.dataMask] }}; }}"


def _stats_payload(asset: dict, territory: dict, snapshot: dict) -> dict:
    geometry = wkb.loads(territory["geometry_wkb"])
    project = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True).transform
    time_range = _source_time_range(asset, snapshot)
    calculation: dict = {"statistics": {"default": {}}}
    if asset["kind"] == "tree_cover_density":
        calculation["statistics"]["default"] = {"percentiles": {"k": [25, 50, 75]}}
    return {
        "input": {"bounds": {"geometry": mapping(transform(project, geometry)), "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/3035"}}, "data": [{"type": f"byoc-{asset['byoc_collection_id']}", "dataFilter": {"timeRange": time_range}}]},
        "aggregation": {"timeRange": time_range, "aggregationInterval": {"of": "P3Y" if asset["kind"] == "tree_cover_change" else "P1D"}, "evalscript": _stats_evalscript(asset), "resx": asset.get("statistical_resolution_m", asset["resolution_m"]), "resy": asset.get("statistical_resolution_m", asset["resolution_m"])},
        "calculations": {"default": calculation},
    }


def _statistical_response(response: requests.Response, asset: dict) -> list[dict]:
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") not in {"OK", "PARTIAL"} or not isinstance(payload.get("data"), list) or len(payload["data"]) != 1:
        raise ValueError(f"Unexpected CDSE Statistical API response for {asset['id']}")
    bands = payload["data"][0].get("outputs", {}).get("default", {}).get("bands", {})
    if not isinstance(bands, dict) or not bands:
        raise ValueError(f"CDSE Statistical API bands missing for {asset['id']}")
    parsed = []
    for name, item in sorted(bands.items()):
        stats = item.get("stats") if isinstance(item, dict) else None
        if not isinstance(stats, dict) or not isinstance(stats.get("sampleCount"), (int, float)):
            raise ValueError(f"CDSE Statistical API statistics missing for {asset['id']}/{name}")
        parsed.append(stats)
    return parsed


def _post_statistics(payload: dict, tokens: _CdseTokenProvider) -> requests.Response:
    """Retry only transient CDSE failures; a persistent contract/API error stops release activation."""
    last_error: Exception | None = None
    transient_attempt = 0
    auth_refreshed = False
    while transient_attempt < 6:
        token = tokens.get()
        try:
            response = requests.post(HRL["statistical_api_url"], json=payload, headers={"Accept": "application/json", "Authorization": f"Bearer {token}"}, timeout=(15, 180))
            if response.status_code == 401 and not auth_refreshed:
                response.close()
                tokens.refresh(token)
                auth_refreshed = True
                continue
            if response.status_code not in {429, 500, 502, 503, 504}:
                return response
            last_error = requests.HTTPError(f"CDSE Statistical API transient status {response.status_code}")
            response.close()
            retry_after = response.headers.get("Retry-After")
            delay = min(float(retry_after), 120) if retry_after and retry_after.replace(".", "", 1).isdigit() else min(2 ** transient_attempt, 60)
        except requests.RequestException as exc:
            last_error = exc
            delay = min(2 ** transient_attempt, 8)
        transient_attempt += 1
        if transient_attempt < 6:
            sleep(delay)
    raise RuntimeError("CDSE Statistical API failed after transient retries") from last_error


def _statistical_records(
    asset: dict, territory: dict, start: int, end: int, snapshot: dict,
    tokens: _CdseTokenProvider, source_hash: str,
) -> list[dict]:
    records: list[dict] = []
    with _post_statistics(_stats_payload(asset, territory, snapshot), tokens) as response:
        stats = _statistical_response(response, asset)
    locator = f"statistical-api:{asset['id']}:{start}-{end}"
    def add(metric: str, value: float) -> None:
        record = _record(asset | {"source_id": HRL["source_id"]}, locator, source_hash, territory, metric, value, start, end)
        record["source_snapshot_signature"] = snapshot["signature"]
        records.append(record)
    if asset["kind"] == "tree_cover_density":
        values = stats[0]
        percentiles = values.get("percentiles")
        if not isinstance(percentiles, dict) or any(str(key) not in percentiles for key in ("25.0", "50.0", "75.0")):
            raise ValueError("CDSE Statistical API percentiles missing for Tree Cover Density")
        add("tree_cover_mean", float(values["mean"])); add("tree_cover_p25", float(percentiles["25.0"])); add("tree_cover_p50", float(percentiles["50.0"])); add("tree_cover_p75", float(percentiles["75.0"]))
    else:
        pixel_ha = asset.get("statistical_resolution_m", asset["resolution_m"]) ** 2 / 10_000
        classes = [(name, code) for name, code in asset["class_codes"].items() if name not in {"non_forest", "non_tree"}]
        areas = {name: float(stats[index]["mean"]) * float(stats[index]["sampleCount"]) * pixel_ha for index, (name, _) in enumerate(classes)}
        if asset["kind"] == "forest_type":
            total = sum(areas.values())
            geometry = transform(Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True).transform, wkb.loads(territory["geometry_wkb"]))
            add("forest_cover_hrl", total); add("forest_area_ha", total); add("forest_share_pct", total / (geometry.area / 10_000) * 100)
            add("broadleaved_area_hrl_ha", areas["broadleaved"]); add("coniferous_area_hrl_ha", areas["coniferous"]); add("mixed_forest_area_hrl_ha", areas["mixed"])
        elif asset["kind"] == "tree_cover_change":
            add("tree_cover_gain_ha", areas["new_tree_cover"]); add("tree_cover_loss_ha", areas["loss_tree_cover"])
        elif asset["kind"] == "dominant_leaf_type":
            add("broadleaved_area_dlt_ha", areas["broadleaved"]); add("coniferous_area_dlt_ha", areas["coniferous"])
    return records


def _checkpoint_path(destination: Path, asset: dict, territory: dict, start: int, end: int) -> Path:
    """Stable local-only checkpoint; source signature is validated in its payload."""
    key = sha256(f"{asset['id']}:{start}-{end}:{territory['territory_version_id']}".encode()).hexdigest()
    return destination.parent / "statistical-api-checkpoints" / asset["id"] / f"{key}.json"


def _expected_statistical_records(asset: dict) -> int:
    per_period = {"tree_cover_density": 4, "forest_type": 6, "tree_cover_change": 2, "dominant_leaf_type": 2}.get(asset["kind"])
    if per_period is None:
        raise ValueError(f"Unknown statistical forest asset kind: {asset['kind']}")
    return per_period


def _read_statistical_checkpoint(destination: Path, asset: dict, territory: dict, start: int, end: int, snapshot: dict, source_hash: str, force: bool) -> list[dict] | None:
    if force:
        return None
    path = _checkpoint_path(destination, asset, territory, start, end)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid local CDSE checkpoint: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid local CDSE checkpoint shape: {path}")
    if payload.get("schemaVersion") != 2 or payload.get("sourceHash") != source_hash or payload.get("sourceSnapshotSignature") != snapshot["signature"] or payload.get("assetId") != asset["id"] or payload.get("logicalPeriod") != [start, end] or payload.get("territoryVersionId") != territory["territory_version_id"]:
        return None
    records = payload.get("records")
    if not isinstance(records, list) or len(records) != _expected_statistical_records(asset) or not all(isinstance(record, dict) for record in records):
        raise ValueError(f"Invalid local CDSE checkpoint records: {path}")
    if any(record.get("territory_version_id") != territory["territory_version_id"] or record.get("source_asset_sha256") != source_hash or record.get("source_snapshot_signature") != snapshot["signature"] for record in records):
        raise ValueError(f"Invalid local CDSE checkpoint provenance: {path}")
    return records


def _write_statistical_checkpoint(destination: Path, asset: dict, territory: dict, start: int, end: int, snapshot: dict, source_hash: str, records: list[dict]) -> None:
    path = _checkpoint_path(destination, asset, territory, start, end)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({
        "schemaVersion": 2,
        "sourceHash": source_hash,
        "sourceSnapshotSignature": snapshot["signature"],
        "assetId": asset["id"],
        "logicalPeriod": [start, end],
        "territoryVersionId": territory["territory_version_id"],
        "records": records,
    }, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def _statistical_jobs(canonical_root: Path, catalog: dict) -> list[tuple[dict, int, int, dict, dict]]:
    """Expand one verified catalog snapshot into its matching ISTAT population."""
    jobs: list[tuple[dict, int, int, dict, dict]] = []
    for asset in (item for item in HRL["assets"] if item.get("statistical_api_enabled", True)):
        for start, end in _asset_periods(asset):
            snapshot = _catalog_snapshot(catalog, asset, start, end)
            reference_year = territory_reference_year_for_period(asset, start, end)
            for territory in _slice_territories(canonical_root, reference_year).to_dict("records"):
                jobs.append((asset, start, end, snapshot, territory))
    if not jobs:
        raise ValueError("CDSE Statistical API has no supported source snapshots")
    return jobs


def _statistical_canonical_matches_contract(table: pd.DataFrame, source_hash: str, jobs: list[tuple[dict, int, int, dict, dict]]) -> bool:
    required = {"methodology_version", "period_start", "period_end", "territory_version_id", "source_asset_sha256", "source_snapshot_signature"}
    if required - set(table.columns) or set(table["source_asset_sha256"].dropna().astype(str)) != {source_hash}:
        return False
    expected = {
        (asset["id"], start, end, territory["territory_version_id"]): snapshot["signature"]
        for asset, start, end, snapshot, territory in jobs
    }
    observed: set[tuple[str, int, int, str]] = set()
    for row in table.itertuples():
        key = (str(row.methodology_version), int(str(row.period_start)[:4]), int(str(row.period_end)[:4]), str(row.territory_version_id))
        if expected.get(key) != getattr(row, "source_snapshot_signature"):
            return False
        observed.add(key)
    return observed == set(expected)


def _ingest_statistical_api(root: Path, canonical_root: Path, destination: Path, force: bool) -> dict:
    state = _catalog_state(root)
    if not state.exists():
        raise FileNotFoundError("CDSE catalog state missing. Run `stato-data fetch foreste` first.")
    metadata = json.loads(state.read_text())
    source_hash = metadata.get("signature")
    if not isinstance(source_hash, str) or len(source_hash) != 64:
        raise ValueError("Invalid CDSE catalog state signature")
    catalog = {"products": metadata.get("products")}
    jobs = _statistical_jobs(canonical_root, catalog)
    if destination.exists() and not force:
        table = pd.read_parquet(destination)
        if _statistical_canonical_matches_contract(table, source_hash, jobs):
            return {"changed": False, "records": len(table), "canonical_bytes": destination.stat().st_size, "records_by_level": table.groupby("territory_level").size().to_dict(), "mode": "statistical-api", "requests": 0}
    records: list[dict] = []
    checkpoint_records = 0
    request_count = len(jobs)
    workers = int(os.getenv("FOREST_STATISTICAL_API_WORKERS", "4"))
    if not 1 <= workers <= 6:
        raise ValueError("FOREST_STATISTICAL_API_WORKERS must be between 1 and 6")
    pending: list[tuple[dict, int, int, dict, dict]] = []
    for asset, start, end, snapshot, territory in jobs:
        checkpoint = _read_statistical_checkpoint(destination, asset, territory, start, end, snapshot, source_hash, force)
        if checkpoint is None:
            pending.append((asset, start, end, snapshot, territory))
        else:
            records.extend(checkpoint)
            checkpoint_records += len(checkpoint)
    if pending:
        tokens = _CdseTokenProvider(HRL)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cdse-forest") as pool:
        pending_jobs = iter(pending)
        futures: dict[Future[list[dict]], tuple[dict, int, int, dict, dict]] = {}

        def submit_next() -> bool:
            try:
                asset, start, end, snapshot, territory = next(pending_jobs)
            except StopIteration:
                return False
            futures[pool.submit(_statistical_records, asset, territory, start, end, snapshot, tokens, source_hash)] = (asset, start, end, snapshot, territory)
            return True

        for _ in range(min(workers * 2, len(pending))):
            submit_next()
        while futures:
            completed, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in completed:
                asset, start, end, snapshot, territory = futures.pop(future)
                result = future.result()
                _write_statistical_checkpoint(destination, asset, territory, start, end, snapshot, source_hash, result)
                records.extend(result)
                submit_next()
    table = pd.DataFrame(records)
    if table.empty or table.duplicated(["derived_metric_id"]).any():
        raise ValueError("Invalid or duplicate CDSE statistical forest metrics")
    destination.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(destination, index=False, compression="zstd")
    return {"changed": True, "records": len(table), "checkpoint_records_reused": checkpoint_records, "canonical_bytes": destination.stat().st_size, "records_by_level": table.groupby("territory_level").size().to_dict(), "reference_years": sorted(table.reference_year.unique().tolist()), "mode": "statistical-api", "requests": request_count, "raw_retention": os.getenv("FORESTS_RAW_RETENTION", HRL["raw_retention_default"])}


def _coverage_reference_year(entries: list[dict], asset_id: str, period: str, level: str) -> int:
    years = {
        entry.get("territoryReferenceYear") for entry in entries
        if entry["assetId"] == asset_id and entry["period"] == period and entry["territoryLevel"] == level
    }
    if len(years) != 1 or not isinstance(next(iter(years), None), int):
        raise ValueError(f"Forest coverage has missing or ambiguous territory reference: {asset_id}/{period}/{level}")
    return int(next(iter(years)))


def _coverage_geometry_reference(entries: list[dict], asset_id: str, period: str, level: str) -> str:
    reference_year = _coverage_reference_year(entries, asset_id, period, level)
    references = {
        entry.get("territoryGeometryReference") for entry in entries
        if entry["assetId"] == asset_id and entry["period"] == period and entry["territoryLevel"] == level
    }
    expected = f"istat-{level}-{reference_year}.pmtiles"
    if references != {expected}:
        raise ValueError(f"Forest coverage has missing or ambiguous territory geometry: {asset_id}/{period}/{level}")
    return expected


def _coverage_state(entries: list[dict], asset_id: str, period: str, level: str) -> tuple[set[str], set[str], set[str]]:
    reference_year = _coverage_reference_year(entries, asset_id, period, level)
    _coverage_geometry_reference(entries, asset_id, period, level)
    matching = [entry for entry in entries if entry["assetId"] == asset_id and entry["period"] == period and entry["territoryLevel"] == level and entry["territoryReferenceYear"] == reference_year]
    if not matching:
        raise ValueError(f"Forest coverage lacks {asset_id}/{period}/{level}")
    expected: set[str] = set()
    numeric: set[str] = set()
    nodata: set[str] = set()
    for entry in matching:
        entry_expected = set(entry["expectedTerritoryIds"])
        entry_numeric = set(entry["numericTerritoryIds"])
        entry_nodata = set(entry["validNoDataTerritoryIds"])
        if expected & entry_expected:
            raise ValueError(f"Forest coverage has overlapping regional entries: {asset_id}/{period}/{level}")
        expected.update(entry_expected)
        numeric.update(entry_numeric)
        nodata.update(entry_nodata)
    if numeric & nodata or expected != numeric | nodata:
        raise ValueError(f"Forest coverage is incomplete or ambiguous: {asset_id}/{period}/{level}")
    return expected, numeric, nodata


def _temporal_diagnostics(table: pd.DataFrame, coverage_entries: list[dict]) -> tuple[list[dict], list[dict]]:
    """Report metric changes and reject only complete duplicate asset snapshots."""
    diagnostics: list[dict] = []
    metric_diagnostics: dict[tuple[str, str, str, str], dict] = {}
    for (_asset, metric, level), series in table.groupby(["methodology_version", "metric_id", "territory_level"], sort=True):
        snapshots: list[tuple[str, pd.DataFrame, dict]] = []
        asset_ids = set(series["methodology_version"].dropna().astype(str)) if "methodology_version" in series else set()
        if len(asset_ids) != 1:
            raise ValueError(f"Forest temporal diagnostics lack one source asset: {metric}/{level}")
        asset_id = asset_ids.pop()
        for (start, end), rows in series.groupby(["period_start", "period_end"], sort=True):
            rows = rows.sort_values("territory_id")
            period = f"{start[:4]}-{end[:4]}"
            expected, numeric, nodata = _coverage_state(coverage_entries, asset_id, period, level)
            reference_year = _coverage_reference_year(coverage_entries, asset_id, period, level)
            geometry_reference = _coverage_geometry_reference(coverage_entries, asset_id, period, level)
            row_ids = set(rows["territory_id"].astype(str))
            if row_ids != numeric:
                raise ValueError(f"Forest numeric coverage does not match canonical rows: {metric}/{level}/{period}")
            payload = [(str(row.territory_id), float(row.value_decimal)) for row in rows.itertuples()]
            digest = sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
            values = rows["value_decimal"].astype(float)
            diagnostic = {
                "metricId": metric, "territoryLevel": level, "period": period,
                "recordCount": len(rows), "minimum": float(values.min()), "maximum": float(values.max()),
                "mean": float(values.mean()), "quantiles": {"p25": float(values.quantile(.25)), "p50": float(values.quantile(.5)), "p75": float(values.quantile(.75))},
                "stablePayloadSha256": digest, "expectedCount": len(expected), "numericCount": len(numeric), "validNoDataCount": len(nodata),
                "territoryReferenceYear": reference_year, "territoryGeometryReference": geometry_reference,
            }
            diagnostics.append(diagnostic)
            metric_diagnostics[(asset_id, metric, level, period)] = diagnostic
            snapshots.append((period, rows, diagnostic))
        for (previous_period, previous, previous_diagnostic), (current_period, current, current_diagnostic) in zip(snapshots, snapshots[1:], strict=False):
            _, previous_numeric, previous_nodata = _coverage_state(coverage_entries, asset_id, previous_period, level)
            _, current_numeric, current_nodata = _coverage_state(coverage_entries, asset_id, current_period, level)
            territory_comparable = previous_diagnostic["territoryGeometryReference"] == current_diagnostic["territoryGeometryReference"]
            joined = previous[["territory_id", "value_decimal"]].merge(current[["territory_id", "value_decimal"]], on="territory_id", suffixes=("_previous", "_current"), validate="one_to_one") if territory_comparable else pd.DataFrame()
            delta = joined["value_decimal_current"].astype(float) - joined["value_decimal_previous"].astype(float) if territory_comparable else pd.Series(dtype=float)
            same_numeric_population = previous_numeric == current_numeric
            same_nodata_population = previous_nodata == current_nodata
            correlation = float(joined["value_decimal_previous"].corr(joined["value_decimal_current"])) if len(joined) > 1 else None
            metric_identical = territory_comparable and same_numeric_population and same_nodata_population and bool((delta == 0).all())
            current_diagnostic["identicalToPrevious"] = metric_identical
            current_diagnostic["comparisonWithPrevious"] = {
                "period": previous_period, "territoryComparable": territory_comparable,
                "reason": None if territory_comparable else "territory_geometry_changed",
                "numericInBoth": len(previous_numeric & current_numeric) if territory_comparable else None,
                "becameNoData": len(previous_numeric & current_nodata) if territory_comparable else None,
                "becameNumeric": len(previous_nodata & current_numeric) if territory_comparable else None,
                "noDataInBoth": len(previous_nodata & current_nodata) if territory_comparable else None,
                "percentChangedAmongComparable": float((delta != 0).mean() * 100) if len(delta) else None,
                "medianAbsoluteDifference": float(delta.abs().median()) if len(delta) else None,
                "maximumAbsoluteDifference": float(delta.abs().max()) if len(delta) else None, "correlation": correlation,
            }
    snapshot_diagnostics: list[dict] = []
    grouped = table.groupby(["methodology_version", "territory_level", "period_start", "period_end"], sort=True)
    snapshots_by_identity: dict[tuple[str, str], list[dict]] = {}
    for (asset_id, level, start, end), rows in grouped:
        period = f"{start[:4]}-{end[:4]}"
        expected, numeric, nodata = _coverage_state(coverage_entries, str(asset_id), period, str(level))
        reference_year = _coverage_reference_year(coverage_entries, str(asset_id), period, str(level))
        geometry_reference = _coverage_geometry_reference(coverage_entries, str(asset_id), period, str(level))
        metric_values: list[tuple[str, str, float]] = []
        metric_set: set[str] = set()
        source_signatures = set()
        for metric, metric_rows in rows.groupby("metric_id", sort=True):
            metric = str(metric)
            metric_set.add(metric)
            row_ids = set(metric_rows["territory_id"].astype(str))
            if row_ids != numeric:
                raise ValueError(f"Forest numeric coverage does not match canonical rows: {metric}/{level}/{period}")
            metric_values.extend((metric, str(item.territory_id), float(item.value_decimal)) for item in metric_rows.sort_values("territory_id").itertuples())
            if "source_snapshot_signature" in metric_rows:
                source_signatures.update(str(value) for value in metric_rows["source_snapshot_signature"].dropna().unique())
        if len(source_signatures) > 1:
            raise ValueError(f"Forest snapshot has ambiguous source signatures: {asset_id}/{level}/{period}")
        snapshot_payload = {
            "metrics": metric_values,
            "numericTerritoryIds": sorted(numeric),
            "validNoDataTerritoryIds": sorted(nodata),
            "territoryReferenceYear": reference_year,
            "territoryGeometryReference": geometry_reference,
        }
        snapshot_hash = sha256(json.dumps(snapshot_payload, separators=(",", ":")).encode()).hexdigest()
        snapshot = {
            "assetId": str(asset_id), "territoryLevel": str(level), "period": period,
            "metricSet": sorted(metric_set), "snapshotPayloadSha256": snapshot_hash,
            "sourceSnapshotSignature": next(iter(source_signatures), None),
            "numericTerritoryIds": sorted(numeric), "validNoDataTerritoryIds": sorted(nodata),
            "expectedCount": len(expected), "numericCount": len(numeric), "validNoDataCount": len(nodata),
            "territoryReferenceYear": reference_year, "territoryGeometryReference": geometry_reference,
        }
        snapshots_by_identity.setdefault((str(asset_id), str(level)), []).append(snapshot)
    for identity, snapshots in snapshots_by_identity.items():
        snapshots.sort(key=lambda item: item["period"])
        for previous, current in zip(snapshots, snapshots[1:], strict=False):
            same_metric_set = previous["metricSet"] == current["metricSet"]
            same_numeric = previous["numericTerritoryIds"] == current["numericTerritoryIds"]
            same_nodata = previous["validNoDataTerritoryIds"] == current["validNoDataTerritoryIds"]
            same_population = same_numeric and same_nodata
            territory_comparable = previous["territoryGeometryReference"] == current["territoryGeometryReference"]
            identical = territory_comparable and same_metric_set and same_population and previous["snapshotPayloadSha256"] == current["snapshotPayloadSha256"]
            previous_signature = previous.get("sourceSnapshotSignature")
            current_signature = current.get("sourceSnapshotSignature")
            if previous_signature and current_signature and previous_signature == current_signature:
                raise ValueError(f"Forest source snapshot signature reused across periods: {identity[0]}/{identity[1]}/{previous['period']}/{current['period']}")
            identical_metrics = [
                metric for metric in current["metricSet"]
                if metric_diagnostics.get((identity[0], metric, identity[1], current["period"]), {}).get("identicalToPrevious")
            ]
            current["comparisonWithPrevious"] = {
                "period": previous["period"], "identical": identical,
                "compatible": same_metric_set and territory_comparable, "metricSetChanged": not same_metric_set,
                "territoryComparable": territory_comparable,
                "reason": None if territory_comparable else "territory_geometry_changed",
                "identicalMetrics": identical_metrics,
                "changedMetrics": [metric for metric in current["metricSet"] if metric not in identical_metrics],
            }
            if identical:
                raise ValueError(f"Forest temporal snapshots are byte-identical complete payloads: {identity[0]}/{identity[1]}/{previous['period']}/{current['period']}")
        snapshot_diagnostics.extend(snapshots)
    return diagnostics, snapshot_diagnostics


def _coverage_report(table: pd.DataFrame, coverage: list[dict], expected_region_codes_by_year: dict[int, set[str]]) -> dict:
    """Validate the exact ISTAT population and make valid NoData auditable."""
    entries: list[dict] = []
    for item in coverage:
        reference_year = item.get("territoryReferenceYear")
        if not isinstance(reference_year, int):
            raise ValueError(f"Forest coverage lacks territory reference: {item['assetId']}/{item['period']}/{item['territoryLevel']}")
        geometry_reference = item.get("territoryGeometryReference")
        if geometry_reference != f"istat-{item['territoryLevel']}-{reference_year}.pmtiles":
            raise ValueError(f"Forest coverage lacks compatible territory geometry: {item['assetId']}/{item['period']}/{item['territoryLevel']}")
        expected = set(item["expectedTerritoryIds"])
        numeric = set(item["numericTerritoryIds"])
        nodata = set(item["validNoDataTerritoryIds"])
        if numeric & nodata or expected != numeric | nodata:
            raise ValueError(f"Forest coverage is incomplete or ambiguous: {item['assetId']}/{item['period']}/{item['territoryLevel']}")
        entries.append({
            "assetId": item["assetId"], "period": item["period"], "territoryLevel": item["territoryLevel"], "territoryReferenceYear": reference_year, "territoryGeometryReference": geometry_reference,
            "expectedCount": len(expected), "numericCount": len(numeric), "validNoDataCount": len(nodata),
            "expectedTerritoryIds": sorted(expected), "numericTerritoryIds": sorted(numeric), "validNoDataTerritoryIds": sorted(nodata),
        })
    temporal_diagnostics, snapshot_diagnostics = _temporal_diagnostics(table, entries)
    report = {
        "schemaVersion": 2, "coverageMode": forest_coverage_mode(),
        "territoryReferenceYears": sorted(expected_region_codes_by_year),
        "entries": entries, "temporalDiagnostics": temporal_diagnostics, "snapshotDiagnostics": snapshot_diagnostics,
    }
    if report["coverageMode"] == "national":
        for asset_id, period in sorted({(entry["assetId"], entry["period"]) for entry in entries}):
            regional_population, _, _ = _coverage_state(entries, asset_id, period, "region")
            reference_year = _coverage_reference_year(entries, asset_id, period, "region")
            region_codes = {territory_id.rsplit(":", 1)[-1] for territory_id in regional_population}
            expected_region_codes = expected_region_codes_by_year.get(reference_year)
            if expected_region_codes is None or region_codes != expected_region_codes:
                raise ValueError(f"Forest national regional coverage differs from ISTAT reference: {asset_id}/{period}")
    return report


def _expected_region_codes_from_coverage(entries: list[dict], asset_id: str | None = None, period: str | None = None, reference_year: int | None = None) -> set[str]:
    """Return the complete, non-overlapping regional union for one snapshot."""
    candidates = [entry for entry in entries if entry["territoryLevel"] == "region" and (asset_id is None or entry["assetId"] == asset_id) and (period is None or entry["period"] == period) and (reference_year is None or entry.get("territoryReferenceYear") == reference_year)]
    if not candidates:
        raise ValueError("Forest coverage has no regional population")
    identities: set[str] = set()
    for entry in candidates:
        expected = set(entry["expectedTerritoryIds"])
        if identities & expected:
            raise ValueError("Forest coverage has overlapping regional entries")
        identities.update(expected)
    return {territory_id.rsplit(":", 1)[-1] for territory_id in identities}


def _require_numeric_tree_cover_change_coverage(entries: list[dict]) -> None:
    """A fully NoData TCPC candidate means the source request is not usable."""
    for asset in HRL["assets"]:
        if asset["kind"] != "tree_cover_change":
            continue
        for start_year, end_year in _asset_periods(asset):
            period = f"{start_year}-{end_year}"
            _, numeric, _ = _coverage_state(entries, asset["id"], period, "region")
            if not numeric:
                raise ValueError(f"CDSE Tree Cover Presence Change has no numeric regional coverage: {period}")


_FOREST_METRICS = {
    "tree_cover_density": {"tree_cover_mean", "tree_cover_p25", "tree_cover_p50", "tree_cover_p75"},
    "forest_type": {"forest_cover_hrl", "forest_area_ha", "forest_share_pct", "broadleaved_area_hrl_ha", "coniferous_area_hrl_ha", "mixed_forest_area_hrl_ha"},
    "tree_cover_change": {"tree_cover_gain_ha", "tree_cover_loss_ha"},
}


def _forest_period_evidence(root: Path, asset: dict, start: int, end: int, groups: list[dict], territories: pd.DataFrame, catalog: dict) -> str:
    """Validate retained requests against today's source contract before any reuse."""
    year = territory_reference_year_for_period(asset, start, end)
    snapshot = _catalog_snapshot(catalog, asset, start, end)
    regions = territories[territories["level"] == "region"].set_index("istat_code")
    if len(groups) != len(regions) or {group["region_istat_code"] for group in groups} != set(regions.index):
        raise ValueError(f"Incomplete CDSE Process API slice manifests for {asset['id']}/{start}-{end}")
    for group in groups:
        if group["territory_reference_year"] != year or group["snapshot_signature"] != snapshot["signature"]:
            raise ValueError(f"Stale CDSE Process API source or geometry: {asset['id']}/{start}-{end}")
        manifest = json.loads(group["manifest_path"].read_text())
        region = regions.loc[group["region_istat_code"]]
        expected_entries = []
        grid = _process_tile_grid(region["geometry_wkb"], int(asset["process_resolution_m"]), int(asset["process_max_pixels"]))
        for bbox, width, height, row, column in grid:
            path = _process_slice_path(root, asset, start, end, group["region_istat_code"], row, column)
            _, request_hash, request = _process_request_contract(asset, bbox, width, height, snapshot, year, group["region_istat_code"], start, end)
            metadata = json.loads(path.with_suffix(path.suffix + ".metadata.json").read_text())
            digest = sha256_file(path)
            if metadata.get("request") != request or metadata.get("processRequestSha256") != request_hash or metadata.get("sha256") != digest:
                raise ValueError(f"Stale CDSE Process API request provenance: {path}")
            expected_entries.append({"path": path.name, "sha256": digest, "bytes": path.stat().st_size, "request": request})
        payload = {"asset_id": asset["id"], "period": [start, end], "territory_reference_year": year,
                   "territory_geometry_reference": f"istat-region-{year}.pmtiles", "region_istat_code": group["region_istat_code"],
                   "snapshot_signature": snapshot["signature"], "entries": expected_entries}
        signature = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if manifest["entries"] != expected_entries or group["source_hash"] != signature:
            raise ValueError(f"Stale CDSE Process API manifest provenance: {group['manifest_path']}")
    # Period inventory is excluded: adding a year must not invalidate other years.
    contract = {key: value for key, value in asset.items() if key not in {"years", "periods"}}
    population = sorted((row.territory_id, row.territory_version_id, row.level, row.region_istat_code,
                         sha256(bytes(row.geometry_wkb)).hexdigest()) for row in territories.itertuples())
    return sha256(json.dumps({"asset": contract, "period": [start, end], "algorithm": ZONAL_ALGORITHM_VERSION,
                              "population": population, "sources": sorted(group["source_hash"] for group in groups)},
                             sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _forest_period_matches(rows: pd.DataFrame, entries: list[dict], asset: dict, start: int, end: int,
                           groups: list[dict], territories: pd.DataFrame) -> bool:
    """Require the full metric/territory population and exact row provenance."""
    try:
        if rows.empty or rows.duplicated(["territory_id", "metric_id"]).any():
            return False
        metrics = _FOREST_METRICS[asset["kind"]]
        year = territory_reference_year_for_period(asset, start, end)
        period = f"{start}-{end}"
        if set(rows.metric_id) != metrics or set(entry["territoryLevel"] for entry in entries) != set(MAPPABLE_LEVELS):
            return False
        for level in MAPPABLE_LEVELS:
            expected, numeric, _ = _coverage_state(entries, asset["id"], period, level)
            if _coverage_reference_year(entries, asset["id"], period, level) != year:
                return False
            if expected != set(territories.loc[territories.level == level, "territory_id"]):
                return False
            level_rows = rows[rows.territory_level == level]
            if set(zip(level_rows.territory_id, level_rows.metric_id)) != {(tid, metric) for tid in numeric for metric in metrics}:
                return False
        population = territories.set_index("territory_id").to_dict("index")
        by_region = {group["region_istat_code"]: group for group in groups}
        if set(rows.source_asset_sha256) != {group["source_hash"] for group in groups}:
            return False
        for record in rows.to_dict("records"):
            territory = population[record["territory_id"]] | {"territory_id": record["territory_id"]}
            group = by_region[territory["region_istat_code"]]
            expected = _record(asset | {"source_id": HRL["source_id"]}, "", group["source_hash"], territory, record["metric_id"], 0, start, end)
            for key in ("derived_metric_id", "dataset_id", "source_asset_sha256", "territory_version_id", "territory_level", "period_start", "period_end", "reference_year", "unit_ucum", "value_state", "official_status", "algorithm_version", "methodology_version"):
                if record[key] != expected[key]:
                    return False
            if record["source_snapshot_signature"] != group["snapshot_signature"] or not math.isfinite(float(record["value_decimal"])):
                return False
        return True
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


def ingest_forests(root: Path, canonical_root: Path, force: bool = False, mode: str | None = None, *, active_canonical: tuple[str, str] | None = None, changed_boundary_years: set[int] | None = None) -> dict:
    destination = canonical_root / "forests" / f"algorithm_version={ZONAL_ALGORITHM_VERSION}" / "zonal_statistics.parquet"
    selected_mode = mode or os.getenv(HRL["processing_mode_environment"], "raster")
    if selected_mode not in HRL["processing_modes"]:
        raise ValueError(f"Unsupported {HRL['processing_mode_environment']}: {selected_mode}")
    if destination.exists() and not legacy_enabled() and "methodology_version" in pq.read_schema(destination).names:
        existing = pd.read_parquet(destination, columns=["methodology_version"])
        if existing["methodology_version"].isin([asset["id"] for asset in LEGACY["assets"]]).any():
            raise ValueError("Existing legacy Forest output requires FOREST_LEGACY_ENABLED=1")
    if legacy_enabled() and selected_mode != "raster":
        raise ValueError("Legacy Forest requires raster processing mode")
    if selected_mode == "statistical-api":
        return _ingest_statistical_api(root, canonical_root, destination, force)
    prior = pd.DataFrame()
    prior_report: dict = {}
    coverage_path = forest_coverage_report_path(destination)
    old_hash = sha256_file(destination) if destination.exists() else None
    old_coverage_hash = sha256_file(coverage_path) if coverage_path.exists() else None
    if active_canonical is not None and not force:
        if not destination.exists() or not coverage_path.exists() or (sha256_file(destination), sha256_file(coverage_path)) != active_canonical:
            raise ValueError("Active forest canonical/coverage checksum mismatch")
        prior = pd.read_parquet(destination)
        prior_report = json.loads(coverage_path.read_text())
        if (prior_report.get("coverageMode") != forest_coverage_mode() or prior_report.get("schemaVersion") != 2
                or not {"methodology_version", "period_start", "period_end"} <= set(prior.columns)):
            prior = pd.DataFrame()
    reused: list[str] = []
    processed: list[str] = []
    period_evidence: dict[str, str] = {}
    catalog_path = root / "raw" / HRL["source_id"] / "catalog.json"
    catalog = json.loads(catalog_path.read_text()) if catalog_path.exists() else {}
    records: list[dict] = []
    coverage: list[dict] = []
    raster_paths: list[Path] = []
    expected_region_codes_by_year: dict[int, set[str]] = {}
    expected_records = 0
    process_groups_found = False
    for original in HRL["assets"]:
        if not original.get("statistical_api_enabled", True):
            continue
        groups = _process_raster_groups(root, original)
        if not groups:
            continue
        expected_groups = sum(
            len(_expected_region_codes(canonical_root, territory_reference_year_for_period(original, start, end)))
            for start, end in _asset_periods(original)
        )
        if len(groups) != expected_groups:
            raise ValueError(f"Incomplete CDSE Process API slice manifests for {original['id']}: groups={len(groups)}, expected={expected_groups}")
        process_groups_found = True
        configured_periods = set(_asset_periods(original))
        if {(group["start_year"], group["end_year"]) for group in groups} != configured_periods:
            raise ValueError(f"Unexpected CDSE Process API periods for {original['id']}")
        metrics_per_territory = len(_FOREST_METRICS[original["kind"]])
        for start, end in sorted(configured_periods):
            period_groups = [group for group in groups if (group["start_year"], group["end_year"]) == (start, end)]
            year = territory_reference_year_for_period(original, start, end)
            territories = _slice_territories_with_region_code(canonical_root, year)
            expected_region_codes_by_year.setdefault(year, _expected_region_codes(canonical_root, year))
            key = f"{original['id']}:{start}-{end}"
            evidence = _forest_period_evidence(root, original, start, end, period_groups, territories, catalog)
            period_evidence[key] = evidence
            entries = [entry for entry in prior_report.get("entries", []) if entry.get("assetId") == original["id"] and entry.get("period") == f"{start}-{end}"]
            rows = prior.loc[(prior.methodology_version == original["id"]) & (prior.period_start == f"{start}-01-01") & (prior.period_end == f"{end}-12-31")] if not prior.empty else prior
            # Existing v3 rows already bind metric identities to exact source
            # manifests and territory versions. New sidecars additionally bind
            # the full asset contract and boundary bytes, excluding year lists.
            if (year not in (changed_boundary_years or set())
                    and prior_report.get("assetPeriodEvidence", {}).get(key, evidence) == evidence
                    and _forest_period_matches(rows, entries, original, start, end, period_groups, territories)):
                records.extend(rows.to_dict("records"))
                coverage.extend(entries)
                expected_records += len(territories) * metrics_per_territory
                reused.append(key)
                continue
            processed.append(key)
            for group in period_groups:
                expected_reference_year = territory_reference_year_for_period(original, group["start_year"], group["end_year"])
                if group["territory_reference_year"] != expected_reference_year:
                    raise ValueError(f"CDSE Process API slice has an invalid territory reference: {group['manifest_path']}")
                grouped_territories = territories[territories["region_istat_code"] == group["region_istat_code"]]
                count = len(grouped_territories)
                expected_records += count * metrics_per_territory
                raster_paths.extend(group["paths"])
                group_records, valid_nodata = _process_raster_records(original, group, territories)
                records.extend(group_records)
                for level in MAPPABLE_LEVELS:
                    expected = set(grouped_territories.loc[grouped_territories["level"] == level, "territory_id"].astype(str))
                    numeric = {str(record["territory_id"]) for record in group_records if record["territory_level"] == level}
                    coverage.append({"assetId": original["id"], "period": f"{group['start_year']}-{group['end_year']}", "territoryLevel": level, "territoryReferenceYear": expected_reference_year, "territoryGeometryReference": f"istat-{level}-{expected_reference_year}.pmtiles", "expectedTerritoryIds": sorted(expected), "numericTerritoryIds": sorted(numeric), "validNoDataTerritoryIds": sorted(set(valid_nodata) & expected)})
    if process_groups_found:
        configured = {f"{asset['id']}:{start}-{end}" for asset in HRL["assets"] if asset.get("statistical_api_enabled", True) for start, end in _asset_periods(asset)}
        if set(period_evidence) != configured:
            raise ValueError("Forest canonical lacks configured enabled asset-periods")
        if len(records) > expected_records:
            raise ValueError(f"Duplicate CDSE Process API raster coverage: records={len(records)}, expected<={expected_records}")
    else:
        # Retain support for a future national COG download adapter. It may only
        # ingest one complete raster per metric/period; tiled COG input must use
        # the manifest-based Process API path above to avoid duplicate borders.
        for source in (HRL, CORINE):
            for original in source["assets"]:
                if not original.get("statistical_api_enabled", True):
                    continue
                asset = original | {"source_id": source["source_id"]}
                for path in _raster_files(root, source, asset):
                    raster_paths.append(path)
                    meta = json.loads(path.with_suffix(path.suffix + ".metadata.json").read_text())
                    start, end = _reference_years_for_asset(asset, path)
                    if not (canonical_root / "territories" / f"reference_year={end}").exists():
                        raise ValueError(f"Missing ISTAT territory version for forest raster reference {end}")
                    frames = [pd.read_parquet(canonical_root / "territories" / f"reference_year={end}" / f"{level}.parquet") for level in (*MAPPABLE_LEVELS,)]
                    records.extend(_raster_records(asset, path, meta["sha256"], pd.concat(frames, ignore_index=True)))
    if legacy_enabled():
        legacy_records, legacy_coverage, legacy_regions = legacy_zonal_records(root, canonical_root)
        records.extend(legacy_records)
        coverage.extend(legacy_coverage)
        expected_region_codes_by_year.update(legacy_regions)
    if not records:
        raise FileNotFoundError("No Copernicus/CLC GeoTIFF raw assets. Raster mode requires retained, validated raster assets.")
    table = pd.DataFrame(records).sort_values(["methodology_version", "period_start", "period_end", "territory_level", "territory_id", "metric_id"], kind="stable").reset_index(drop=True)
    if table.duplicated(["derived_metric_id"]).any(): raise ValueError("Duplicate forest zonal metrics")
    destination.parent.mkdir(parents=True, exist_ok=True)
    coverage_path = forest_coverage_report_path(destination)
    if process_groups_found or legacy_enabled():
        report = _coverage_report(table, coverage, expected_region_codes_by_year)
        if process_groups_found:
            _require_numeric_tree_cover_change_coverage(report["entries"])
        report["assetPeriodEvidence"] = dict(sorted(period_evidence.items()))
        json_dump(coverage_path, report)
    table.to_parquet(destination, index=False, compression="zstd")
    retention = os.getenv("FORESTS_RAW_RETENTION", HRL["raw_retention_default"])
    if retention == "metadata_only":
        # Canonical and sidecar checksum/provenance now exist; only exact raster
        # payloads are removed, never their metadata or any unrelated raw asset.
        for path in raster_paths: path.unlink()
    elif retention != "retain":
        raise ValueError("FORESTS_RAW_RETENTION must be retain or metadata_only")
    return {"changed": old_hash != sha256_file(destination) or old_coverage_hash != (sha256_file(coverage_path) if coverage_path.exists() else None), "asset_periods_reused": reused, "asset_periods_processed": processed, "records": len(table), "canonical_bytes": destination.stat().st_size, "records_by_level": table.groupby("territory_level").size().to_dict(), "reference_years": sorted(table.reference_year.unique().tolist()), "coverage_path": str(coverage_path) if coverage_path.exists() else None, "raw_retention": retention}
