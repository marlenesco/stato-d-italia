from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from .common import stable_id
from .download import download
from .registry import load_source
from .territories import load_territory_index

SOURCE = load_source("ispra-bigbang")
METRICS = {"TP": ("water_total_precipitation_mm", "mm"), "AE": ("water_actual_evapotranspiration_mm", "mm"), "IF": ("water_internal_flow_mm", "mm"), "GR": ("water_aquifer_recharge_mm", "mm"), "RF": ("water_surface_runoff_mm", "mm")}


def _frame(path: Path, region: bool) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name="Annuale (Annual)", header=None)
    header = raw.iloc[0].tolist()
    frame = raw.iloc[2:].copy()
    frame.columns = header
    # Workbook repeats hydrological symbols for mm and km3 columns. MVP keeps
    # first occurrence: area-normalised mm, comparable across territories.
    frame = frame.loc[:, ~frame.columns.duplicated()].copy()
    required = {"ANNO (YEAR)", "TP", "AE", "IF", "GR", "RF"}
    if region:
        required |= {"CODE (Istat)", "TERRITORIO (TERRITORY)"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Unexpected BIGBANG annual contract: missing={sorted(required-set(frame.columns))}")
    return frame


def ingest_water(raw_root: Path, canonical_root: Path, force: bool = False, offline: bool = False) -> dict:
    raw_dir = raw_root / "raw" / SOURCE["source_id"]
    italy = download(SOURCE["download_urls"]["italy"], raw_dir / "bigbang100-italy.xlsx", SOURCE["source_id"], offline=offline)
    regions = download(SOURCE["download_urls"]["regions"], raw_dir / "bigbang100-regions.xlsx", SOURCE["source_id"], offline=offline)
    destination = canonical_root / "water" / "dataset_version=bigbang-10-1951-2025" / "observations.parquet"
    if italy.get("unchanged") and regions.get("unchanged") and destination.exists() and not force:
        table = pd.read_parquet(destination)
        return {"changed": False, "records": len(table), "canonical_bytes": destination.stat().st_size, "years": sorted(table.reference_year.unique().tolist()), "source": {"italy": italy, "regions": regions}}
    index = load_territory_index(canonical_root, 2025)
    records = []
    for path, is_region, source in ((raw_dir / "bigbang100-italy.xlsx", False, italy), (raw_dir / "bigbang100-regions.xlsx", True, regions)):
        for row_number, row in _frame(path, is_region).iterrows():
            year = int(row["ANNO (YEAR)"])
            territory = index[f"it:region:{int(row['CODE (Istat)']):02d}"] if is_region else index["it:country:IT"]
            for symbol, (metric, unit) in METRICS.items():
                value = row[symbol]
                if pd.isna(value):
                    raise ValueError(f"Missing BIGBANG value {symbol} row {row_number + 3}")
                start, end = date(year, 1, 1).isoformat(), date(year, 12, 31).isoformat()
                records.append({"observation_id": stable_id(SOURCE["source_id"], source["sha256"], row_number, symbol), "dataset_id": SOURCE["source_id"], "dataset_version": "bigbang-10-1951-2025", "source_asset_sha256": source["sha256"], "source_row_locator": f"annual:{row_number + 3}:{symbol}", "metric_id": metric, "territory_id": territory["territory_id"], "territory_version_id": territory["territory_version_id"], "territory_level": territory["level"], "period_start": start, "period_end": end, "reference_year": year, "value_decimal": float(value), "unit_ucum": unit, "official_status": "model_estimate", "quality_flags": [], "methodology_version": "bigbang-10", "ingested_at": source["acquired_at"]})
    table = pd.DataFrame(records)
    if table.duplicated(["territory_id", "metric_id", "reference_year"]).any(): raise ValueError("Duplicate BIGBANG observations")
    destination.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(destination, index=False, compression="zstd")
    return {"changed": True, "records": len(table), "canonical_bytes": destination.stat().st_size, "years": sorted(table.reference_year.unique().tolist()), "source": {"italy": italy, "regions": regions}}
