from __future__ import annotations

import json
import math
import os
import re
import zipfile
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from hashlib import sha256
from datetime import date
from pathlib import Path
from time import sleep
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import rasterio
import requests
from pyproj import Transformer
from rasterio.mask import mask
from shapely import wkb
from shapely.geometry import box, mapping
from shapely.ops import transform

from .common import json_dump, now_iso, sha256_file, stable_id
from .download import download
from .registry import load_source

HRL = load_source("copernicus-forests")
CORINE = load_source("copernicus-corine-forests")
INFC = load_source("infc-2015-forests")
ZONAL_ALGORITHM_VERSION = "forests-zonal-statistics-v2"
MAPPABLE_LEVELS = ("municipality", "province", "region")


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


def _catalog_products(source: dict, token: str) -> list[dict]:
    """Discover supported HRL products through CDSE OData; unknown shapes fail closed."""
    tags = [asset["catalog_tag"] for asset in source["assets"]]
    filters = [f"contains(Name,'{tag}')" for tag in tags]
    params = {
        "$filter": "Collection/Name eq 'CLMS' and (" + " or ".join(filters) + ")",
        "$select": "Id,Name,ContentDate,Checksum,S3Path,OriginDate",
        "$orderby": "ContentDate/Start desc",
        "$top": "1000",
    }
    response = requests.get(source["catalog_api_url"], params=params, timeout=(15, 90), headers={"Accept": "application/json", "Authorization": f"Bearer {token}"})
    response.raise_for_status()
    payload = response.json()
    values = payload.get("value")
    if not isinstance(values, list):
        raise ValueError("Unexpected CDSE OData contract: value[] missing")
    products: list[dict] = []
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get("Id"), str) or not isinstance(item.get("Name"), str):
            raise ValueError("Unexpected CDSE OData product shape")
        products.append({key: item.get(key) for key in ("Id", "Name", "ContentDate", "Checksum", "S3Path", "OriginDate")})
    if not products:
        raise ValueError("CDSE OData returned no supported Tree Cover & Forest products")
    return sorted(products, key=lambda item: (item["Name"], item["Id"]))


def _catalog_state(root: Path) -> Path:
    return root / "raw" / HRL["source_id"] / "catalog.json"


def _check_catalog(root: Path, source: dict, token: str) -> dict:
    products = _catalog_products(source, token)
    signature = sha256(json.dumps(products, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    destination = _catalog_state(root)
    previous = json.loads(destination.read_text()) if destination.exists() else None
    changed = previous is None or previous.get("signature") != signature
    if changed:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps({"source_id": source["source_id"], "signature": signature, "products": products, "checked_at": now_iso()}, ensure_ascii=False, separators=(",", ":")) + "\n")
    return {"changed": changed, "signature": signature, "products": len(products), "path": str(destination)}


def _asset_periods(asset: dict) -> list[tuple[int, int]]:
    return [(int(year), int(year)) for year in asset.get("years", [])] + [tuple(map(int, period)) for period in asset.get("periods", [])]


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


def _process_payload(asset: dict, bbox: tuple[float, float, float, float], width: int, height: int, start_year: int, end_year: int) -> dict:
    timestamp = f"{end_year}-01-01T00:00:00Z"
    return {
        "input": {
            "bounds": {"bbox": list(bbox), "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/3035"}},
            "data": [{"type": f"byoc-{asset['byoc_collection_id']}", "dataFilter": {"timeRange": {"from": timestamp, "to": f"{end_year}-01-02T00:00:00Z"}}}],
        },
        "output": {"width": width, "height": height, "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}]},
        "evalscript": _process_evalscript(asset),
    }


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


def _fetch_process_raster_slices(root: Path, canonical_root: Path, token: str) -> dict:
    """Acquire a bounded local raster slice through CDSE Process API, never R2."""
    reference_year = int(HRL["development_slice"]["territory_reference_year"])
    territories = _slice_territories(canonical_root, reference_year)
    regions = territories[territories["level"] == "region"]
    selected = set(HRL["development_slice"]["region_istat_codes"])
    if set(regions["istat_code"]) != selected:
        raise ValueError("Forest process slice lacks configured ISTAT regions")
    changed = False
    requests_made = 0
    files: list[dict] = []
    assets = [asset for asset in HRL["assets"] if asset.get("statistical_api_enabled", True)]
    for asset in assets:
        for start_year, end_year in _asset_periods(asset):
            for region in regions.sort_values("istat_code").to_dict("records"):
                manifest_path = _process_slice_path(root, asset, start_year, end_year, region["istat_code"], 0, 0).parent / "slice-manifest.json"
                entries: list[dict] = []
                for bbox, width, height, row, column in _process_tile_grid(region["geometry_wkb"], int(asset["process_resolution_m"]), int(asset["process_max_pixels"])):
                    target = _process_slice_path(root, asset, start_year, end_year, region["istat_code"], row, column)
                    sidecar = target.with_suffix(target.suffix + ".metadata.json")
                    expected = {"asset_id": asset["id"], "period": [start_year, end_year], "region_istat_code": region["istat_code"], "bbox_epsg3035": list(bbox), "width": width, "height": height}
                    prior = json.loads(sidecar.read_text()) if target.exists() and sidecar.exists() else None
                    if prior and prior.get("request") == expected and prior.get("sha256") == sha256_file(target):
                        metadata = prior
                    else:
                        with _post_process_raster(_process_payload(asset, bbox, width, height, start_year, end_year), token) as response:
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
                                "request": expected, "asset_id": asset["id"], "band": asset["band"], "byoc_collection_id": asset["byoc_collection_id"],
                                "source_resolution_m": asset["resolution_m"], "slice_resolution_m": asset["process_resolution_m"],
                                "license": HRL["license"], "methodology_url": HRL["methodology_url"],
                            }
                            json_dump(sidecar, metadata)
                            changed = True
                            requests_made += 1
                    entries.append({"path": target.name, "sha256": metadata["sha256"], "bytes": metadata["bytes"], "request": expected})
                signature = sha256(json.dumps({"asset_id": asset["id"], "period": [start_year, end_year], "region_istat_code": region["istat_code"], "entries": entries}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                manifest = {"schemaVersion": 1, "source_id": HRL["source_id"], "asset_id": asset["id"], "period": [start_year, end_year], "region_istat_code": region["istat_code"], "slice_resolution_m": asset["process_resolution_m"], "source_signature": signature, "entries": entries}
                prior_manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
                if prior_manifest != manifest:
                    json_dump(manifest_path, manifest)
                    changed = True
                files.append({"path": str(manifest_path), "bytes": sum(item["bytes"] for item in entries), "tiles": len(entries), "asset": asset["id"], "period": f"{start_year}-{end_year}", "region": region["istat_code"]})
    return {"changed": changed, "requests": requests_made, "files": files, "raw_bytes": sum(item["bytes"] for item in files)}


def fetch_forests(root: Path, offline: bool = False) -> dict:
    """Acquire INFC, check CDSE, and optionally retain bounded local raster slices."""
    infc = []
    for asset in INFC["assets"]:
        target = root / "raw" / INFC["source_id"] / f"{asset['id']}.zip"
        infc.append(download(asset["url"], target, INFC["source_id"], offline=offline, user_agent=INFC["download_user_agent"], source_context={"asset_id": asset["id"], "metric_id": asset["metric_id"]}))
    if offline:
        return {"infc": infc, "catalog": {"status": "offline"}, "raw_retention": os.getenv("FORESTS_RAW_RETENTION", HRL["raw_retention_default"])}
    if not os.getenv(HRL["client_id_environment"]) or not os.getenv(HRL["client_secret_environment"]):
        return {"infc": infc, "catalog": {"status": "blocked", "reason": "CDSE OAuth credentials unavailable"}, "raw_retention": os.getenv("FORESTS_RAW_RETENTION", HRL["raw_retention_default"])}
    token = _cdse_token(HRL)
    catalog = _check_catalog(root, HRL, token)
    raster = None
    if os.getenv(HRL["processing_mode_environment"], "raster") == "raster":
        raster = _fetch_process_raster_slices(root, root / "canonical", token)
    return {"infc": infc, "catalog": catalog, "raster": raster, "raw_retention": os.getenv("FORESTS_RAW_RETENTION", HRL["raw_retention_default"])}


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
        "derived_metric_id": stable_id(ZONAL_ALGORITHM_VERSION, source_hash, territory["territory_id"], metric_id, start_year, end_year),
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
            values = values[np.isfinite(values)]
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
            manifest.get("schemaVersion") != 1
            or manifest.get("source_id") != HRL["source_id"]
            or manifest.get("asset_id") != asset["id"]
            or not isinstance(manifest.get("period"), list)
            or len(manifest["period"]) != 2
            or not isinstance(manifest.get("region_istat_code"), str)
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
        groups.append({"manifest_path": manifest_path, "source_hash": manifest["source_signature"], "region_istat_code": manifest["region_istat_code"], "start_year": int(manifest["period"][0]), "end_year": int(manifest["period"][1]), "paths": paths})
    return groups


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


def _process_raster_records(asset: dict, group: dict, territories: pd.DataFrame) -> list[dict]:
    """Aggregate all regional Process API chunks before writing one observation per territory."""
    subset = territories[territories["region_istat_code"] == group["region_istat_code"]]
    if subset.empty:
        raise ValueError(f"Process slice has no configured territory: {group['region_istat_code']}")
    rows: list[dict] = []
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
                values = values[np.isfinite(values) & (values != asset["process_no_data"])]
                if len(values):
                    values_by_chunk.append(values)
            if not values_by_chunk:
                raise ValueError(f"No raster values for {asset['id']} / {territory['territory_version_id']}")
            values = np.concatenate(values_by_chunk)

            def add(metric: str, value: float) -> None:
                rows.append(_record(asset | {"source_id": HRL["source_id"]}, group["manifest_path"].relative_to(group["manifest_path"].parents[4]), group["source_hash"], territory, metric, float(value), group["start_year"], group["end_year"]))

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
    return rows


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
    """Keep complete municipality/province/region coverage for the configured regions."""
    frames = {level: pd.read_parquet(canonical_root / "territories" / f"reference_year={year}" / f"{level}.parquet") for level in MAPPABLE_LEVELS}
    selected_regions = set(HRL["development_slice"]["region_istat_codes"])
    regions = frames["region"][frames["region"]["istat_code"].isin(selected_regions)]
    provinces = frames["province"][frames["province"]["parent_istat_code"].isin(selected_regions)]
    municipalities = frames["municipality"][frames["municipality"]["parent_istat_code"].isin(set(provinces["istat_code"]))]
    result = pd.concat([municipalities, provinces, regions], ignore_index=True)
    if result.empty or result.duplicated(["territory_id", "territory_version_id"]).any():
        raise ValueError("Invalid configured forest development-slice territory coverage")
    return result


def _stats_evalscript(asset: dict) -> str:
    band = asset["band"]
    if asset["kind"] == "tree_cover_density":
        return f"//VERSION=3\nfunction setup() {{ return {{ input: [\"{band}\", \"dataMask\"], output: [{{ id: \"default\", bands: 1, sampleType: \"FLOAT32\" }}, {{ id: \"dataMask\", bands: 1 }}] }}; }}\nfunction evaluatePixel(s) {{ return {{ default: [s.{band}], dataMask: [s.dataMask] }}; }}"
    codes = asset["class_codes"]
    classes = [(name, code) for name, code in codes.items() if name not in {"non_forest", "non_tree"}]
    outputs = ", ".join(f"s.{band} === {code} ? 1 : 0" for _, code in classes)
    return f"//VERSION=3\nfunction setup() {{ return {{ input: [\"{band}\", \"dataMask\"], output: [{{ id: \"default\", bands: {len(classes)}, sampleType: \"UINT8\" }}, {{ id: \"dataMask\", bands: 1 }}] }}; }}\nfunction evaluatePixel(s) {{ return {{ default: [{outputs}], dataMask: [s.dataMask] }}; }}"


def _stats_payload(asset: dict, territory: dict, start_year: int, end_year: int) -> dict:
    geometry = wkb.loads(territory["geometry_wkb"])
    project = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True).transform
    # HRL BYOC items are timestamped at the source reference date (1 January),
    # not over a continuous annual observation interval. Query that one snapshot
    # while retaining the documented source period in canonical observations.
    start = f"{end_year}-01-01T00:00:00Z"
    end = f"{end_year}-01-02T00:00:00Z"
    calculation: dict = {"statistics": {"default": {}}}
    if asset["kind"] == "tree_cover_density":
        calculation["statistics"]["default"] = {"percentiles": {"k": [25, 50, 75]}}
    return {
        "input": {"bounds": {"geometry": mapping(transform(project, geometry)), "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/3035"}}, "data": [{"type": f"byoc-{asset['byoc_collection_id']}", "dataFilter": {"timeRange": {"from": start, "to": end}}}]},
        "aggregation": {"timeRange": {"from": start, "to": end}, "aggregationInterval": {"of": "P1D"}, "evalscript": _stats_evalscript(asset), "resx": asset.get("statistical_resolution_m", asset["resolution_m"]), "resy": asset.get("statistical_resolution_m", asset["resolution_m"])},
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


def _post_statistics(payload: dict, token: str) -> requests.Response:
    """Retry only transient CDSE failures; a persistent contract/API error stops release activation."""
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            response = requests.post(HRL["statistical_api_url"], json=payload, headers={"Accept": "application/json", "Authorization": f"Bearer {token}"}, timeout=(15, 180))
            if response.status_code not in {429, 500, 502, 503, 504}:
                return response
            last_error = requests.HTTPError(f"CDSE Statistical API transient status {response.status_code}")
            response.close()
            retry_after = response.headers.get("Retry-After")
            delay = min(float(retry_after), 120) if retry_after and retry_after.replace(".", "", 1).isdigit() else min(2 ** attempt, 60)
        except requests.RequestException as exc:
            last_error = exc
            delay = min(2 ** attempt, 8)
        if attempt < 5:
            sleep(delay)
    raise RuntimeError("CDSE Statistical API failed after transient retries") from last_error


def _statistical_records(asset: dict, territory: dict, token: str, source_hash: str) -> list[dict]:
    periods = [(year, year) for year in asset.get("years", [])] + [tuple(period) for period in asset.get("periods", [])]
    records: list[dict] = []
    for start, end in periods:
        with _post_statistics(_stats_payload(asset, territory, start, end), token) as response:
            stats = _statistical_response(response, asset)
        locator = f"statistical-api:{asset['id']}:{start}-{end}"
        def add(metric: str, value: float) -> None:
            records.append(_record(asset | {"source_id": HRL["source_id"]}, locator, source_hash, territory, metric, value, start, end))
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


def _checkpoint_path(destination: Path, asset: dict, territory: dict) -> Path:
    """Stable local-only checkpoint; source signature is validated in its payload."""
    key = sha256(f"{asset['id']}:{territory['territory_version_id']}".encode()).hexdigest()
    return destination.parent / "statistical-api-checkpoints" / asset["id"] / f"{key}.json"


def _expected_statistical_records(asset: dict) -> int:
    periods = len(asset.get("years", [])) + len(asset.get("periods", []))
    per_period = {"tree_cover_density": 4, "forest_type": 6, "tree_cover_change": 2, "dominant_leaf_type": 2}.get(asset["kind"])
    if per_period is None:
        raise ValueError(f"Unknown statistical forest asset kind: {asset['kind']}")
    return periods * per_period


def _read_statistical_checkpoint(destination: Path, asset: dict, territory: dict, source_hash: str, force: bool) -> list[dict] | None:
    if force:
        return None
    path = _checkpoint_path(destination, asset, territory)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid local CDSE checkpoint: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid local CDSE checkpoint shape: {path}")
    if payload.get("sourceHash") != source_hash or payload.get("assetId") != asset["id"] or payload.get("territoryVersionId") != territory["territory_version_id"]:
        return None
    records = payload.get("records")
    if not isinstance(records, list) or len(records) != _expected_statistical_records(asset) or not all(isinstance(record, dict) for record in records):
        raise ValueError(f"Invalid local CDSE checkpoint records: {path}")
    if any(record.get("territory_version_id") != territory["territory_version_id"] or record.get("source_asset_sha256") != source_hash for record in records):
        raise ValueError(f"Invalid local CDSE checkpoint provenance: {path}")
    return records


def _write_statistical_checkpoint(destination: Path, asset: dict, territory: dict, source_hash: str, records: list[dict]) -> None:
    path = _checkpoint_path(destination, asset, territory)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({
        "schemaVersion": 1,
        "sourceHash": source_hash,
        "assetId": asset["id"],
        "territoryVersionId": territory["territory_version_id"],
        "records": records,
    }, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def _ingest_statistical_api(root: Path, canonical_root: Path, destination: Path, force: bool) -> dict:
    if destination.exists() and not force:
        table = pd.read_parquet(destination)
        return {"changed": False, "records": len(table), "canonical_bytes": destination.stat().st_size, "records_by_level": table.groupby("territory_level").size().to_dict(), "mode": "statistical-api", "requests": 0}
    state = _catalog_state(root)
    if not state.exists():
        raise FileNotFoundError("CDSE catalog state missing. Run `stato-data fetch foreste` first.")
    token = _cdse_token(HRL)
    metadata = json.loads(state.read_text())
    source_hash = metadata.get("signature")
    if not isinstance(source_hash, str) or len(source_hash) != 64:
        raise ValueError("Invalid CDSE catalog state signature")
    reference_year = int(HRL["development_slice"]["territory_reference_year"])
    territories = _slice_territories(canonical_root, reference_year)
    records: list[dict] = []
    checkpoint_records = 0
    assets = [asset for asset in HRL["assets"] if asset.get("statistical_api_enabled", True)]
    territory_records = territories.to_dict("records")
    request_count = sum(len(asset.get("years", [])) + len(asset.get("periods", [])) for asset in assets) * len(territory_records)
    workers = int(os.getenv("FOREST_STATISTICAL_API_WORKERS", "4"))
    if not 1 <= workers <= 6:
        raise ValueError("FOREST_STATISTICAL_API_WORKERS must be between 1 and 6")
    pending: list[tuple[dict, dict]] = []
    for territory in territory_records:
        for asset in assets:
            checkpoint = _read_statistical_checkpoint(destination, asset, territory, source_hash, force)
            if checkpoint is None:
                pending.append((territory, asset))
            else:
                records.extend(checkpoint)
                checkpoint_records += len(checkpoint)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cdse-forest") as pool:
        jobs = iter(pending)
        futures: dict[Future[list[dict]], tuple[dict, dict]] = {}

        def submit_next() -> bool:
            try:
                territory, asset = next(jobs)
            except StopIteration:
                return False
            futures[pool.submit(_statistical_records, asset, territory, token, source_hash)] = (territory, asset)
            return True

        for _ in range(min(workers * 2, len(pending))):
            submit_next()
        while futures:
            completed, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in completed:
                territory, asset = futures.pop(future)
                result = future.result()
                _write_statistical_checkpoint(destination, asset, territory, source_hash, result)
                records.extend(result)
                submit_next()
    table = pd.DataFrame(records)
    if table.empty or table.duplicated(["derived_metric_id"]).any():
        raise ValueError("Invalid or duplicate CDSE statistical forest metrics")
    destination.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(destination, index=False, compression="zstd")
    return {"changed": True, "records": len(table), "checkpoint_records_reused": checkpoint_records, "canonical_bytes": destination.stat().st_size, "records_by_level": table.groupby("territory_level").size().to_dict(), "reference_years": sorted(table.reference_year.unique().tolist()), "mode": "statistical-api", "requests": request_count, "raw_retention": os.getenv("FORESTS_RAW_RETENTION", HRL["raw_retention_default"])}


def ingest_forests(root: Path, canonical_root: Path, force: bool = False, mode: str | None = None) -> dict:
    destination = canonical_root / "forests" / f"algorithm_version={ZONAL_ALGORITHM_VERSION}" / "zonal_statistics.parquet"
    selected_mode = mode or os.getenv(HRL["processing_mode_environment"], "raster")
    if selected_mode not in HRL["processing_modes"]:
        raise ValueError(f"Unsupported {HRL['processing_mode_environment']}: {selected_mode}")
    if selected_mode == "statistical-api":
        return _ingest_statistical_api(root, canonical_root, destination, force)
    if destination.exists() and not force:
        table = pd.read_parquet(destination)
        return {"changed": False, "records": len(table), "canonical_bytes": destination.stat().st_size, "records_by_level": table.groupby("territory_level").size().to_dict()}
    records: list[dict] = []
    raster_paths: list[Path] = []
    reference_year = int(HRL["development_slice"]["territory_reference_year"])
    territories = _slice_territories_with_region_code(canonical_root, reference_year)
    expected_records = 0
    process_groups_found = False
    for original in HRL["assets"]:
        if not original.get("statistical_api_enabled", True):
            continue
        groups = _process_raster_groups(root, original)
        if not groups:
            continue
        expected_groups = len(_asset_periods(original)) * len(HRL["development_slice"]["region_istat_codes"])
        if len(groups) != expected_groups:
            raise ValueError(f"Incomplete CDSE Process API slice manifests for {original['id']}: groups={len(groups)}, expected={expected_groups}")
        process_groups_found = True
        metrics_per_territory = {"tree_cover_density": 4, "forest_type": 6, "tree_cover_change": 2}[original["kind"]]
        for group in groups:
            count = int((territories["region_istat_code"] == group["region_istat_code"]).sum())
            expected_records += count * metrics_per_territory
            raster_paths.extend(group["paths"])
            records.extend(_process_raster_records(original, group, territories))
    if process_groups_found:
        if len(records) != expected_records:
            raise ValueError(f"Incomplete CDSE Process API raster coverage: records={len(records)}, expected={expected_records}")
    else:
        # Retain support for a future national COG download adapter. It may only
        # ingest one complete raster per metric/period; tiled COG input must use
        # the manifest-based Process API path above to avoid duplicate borders.
        for source in (HRL, CORINE):
            for original in source["assets"]:
                asset = original | {"source_id": source["source_id"]}
                for path in _raster_files(root, source, asset):
                    raster_paths.append(path)
                    meta = json.loads(path.with_suffix(path.suffix + ".metadata.json").read_text())
                    start, end = _reference_years_for_asset(asset, path)
                    if not (canonical_root / "territories" / f"reference_year={end}").exists():
                        raise ValueError(f"Missing ISTAT territory version for forest raster reference {end}")
                    frames = [pd.read_parquet(canonical_root / "territories" / f"reference_year={end}" / f"{level}.parquet") for level in (*MAPPABLE_LEVELS,)]
                    records.extend(_raster_records(asset, path, meta["sha256"], pd.concat(frames, ignore_index=True)))
    if not records:
        raise FileNotFoundError("No Copernicus/CLC GeoTIFF raw assets. Raster mode requires retained, validated raster assets.")
    table = pd.DataFrame(records)
    if table.duplicated(["derived_metric_id"]).any(): raise ValueError("Duplicate forest zonal metrics")
    destination.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(destination, index=False, compression="zstd")
    retention = os.getenv("FORESTS_RAW_RETENTION", HRL["raw_retention_default"])
    if retention == "metadata_only":
        # Canonical and sidecar checksum/provenance now exist; only exact raster
        # payloads are removed, never their metadata or any unrelated raw asset.
        for path in raster_paths: path.unlink()
    elif retention != "retain":
        raise ValueError("FORESTS_RAW_RETENTION must be retain or metadata_only")
    return {"changed": True, "records": len(table), "canonical_bytes": destination.stat().st_size, "records_by_level": table.groupby("territory_level").size().to_dict(), "reference_years": sorted(table.reference_year.unique().tolist()), "raw_retention": retention}
