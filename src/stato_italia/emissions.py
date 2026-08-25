from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from .common import now_iso, stable_id
from .download import download_registered_source
from .registry import load_source
from .territories import load_territory_index

SOURCE = load_source("ispra-emissions-provincial-2026")
SOURCE_ID = SOURCE["source_id"]
SHEET = SOURCE["source_contract"]["workbook_sheet"]
PERIOD_REFERENCE_YEARS = {
    int(period): int(reference_year)
    for period, reference_year in SOURCE["source_contract"]["province_reference_year_by_period"].items()
}
REQUIRED_COLUMNS = set(SOURCE["source_contract"]["required_columns"])


def _code(value: object, width: int) -> str:
    if pd.isna(value):
        raise ValueError("missing numeric territorial code")
    number = float(value)
    if not number.is_integer():
        raise ValueError(f"non-integral territorial code: {value!r}")
    return str(int(number)).zfill(width)


def _text(value: object, field: str) -> str:
    if pd.isna(value) or not str(value).strip():
        raise ValueError(f"missing {field}")
    return str(value).strip()


def _validate_contract(frame: pd.DataFrame) -> None:
    columns = {str(column) for column in frame.columns}
    missing = REQUIRED_COLUMNS - columns
    if missing:
        raise ValueError(f"Unexpected ISPRA emissions contract: missing={sorted(missing)}")
    if frame.empty:
        raise ValueError("Unexpected ISPRA emissions contract: empty workbook sheet")


def _province_index(canonical_root: Path, reference_year: int) -> dict[str, dict]:
    return {
        territory["istat_code"]: territory
        for territory in load_territory_index(canonical_root, reference_year).values()
        if territory["level"] == "province"
    }


def _record(
    *, row: pd.Series, row_number: int, period: int, territory: dict,
    source_hash: str, ingested_at: str,
) -> dict:
    pollutant_code = _text(row["COD_POL"], "COD_POL")
    snap_code = _text(row["SNAP"], "SNAP")
    start = date(period, 1, 1).isoformat()
    end = date(period, 12, 31).isoformat()
    locator = f"{SHEET}:{row_number + 2}:{period}"
    dimensions = {
        "pollutant_code": pollutant_code,
        "pollutant_label": _text(row["NOMPOL"], "NOMPOL"),
        "snap_code": snap_code,
        "snap_label": _text(row["Descrizione"], "Descrizione"),
    }
    return {
        "observation_id": stable_id(SOURCE_ID, source_hash, locator),
        "dataset_id": SOURCE_ID,
        "dataset_version": "2026-2023-disaggregation",
        "source_asset_sha256": source_hash,
        "source_row_locator": locator,
        "source_dimensions_json": json.dumps(dimensions, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "metric_id": f"emissions_pollutant_{pollutant_code.lower()}",
        "territory_id": territory["territory_id"],
        "territory_version_id": territory["territory_version_id"],
        "territory_level": "province",
        "period_start": start,
        "period_end": end,
        "reference_year": period,
        "value_decimal": float(row[str(period)]),
        "unit_ucum": _text(row["UNI_mis"], "UNI_mis"),
        "official_status": "unknown",
        "quality_flags": ["official_top_down_disaggregation"],
        "methodology_version": "ispra-emissions-provincial-2026",
        "ingested_at": ingested_at,
    }


def _records(frame: pd.DataFrame, canonical_root: Path, source_hash: str, ingested_at: str) -> list[dict]:
    output: list[dict] = []
    province_rows = frame.loc[frame["G_EMEP"].isna()].copy()
    for period, reference_year in PERIOD_REFERENCE_YEARS.items():
        index = _province_index(canonical_root, reference_year)
        period_rows = province_rows.loc[province_rows[str(period)].notna()].copy()
        codes = {_code(value, 3) for value in period_rows["COD_PROV"]}
        expected_codes = set(index)
        if codes != expected_codes:
            raise ValueError(
                f"Unexpected ISPRA emissions province coverage for {period}: "
                f"missing={sorted(expected_codes - codes)}, unknown={sorted(codes - expected_codes)}"
            )
        for row_number, row in period_rows.iterrows():
            territory = index[_code(row["COD_PROV"], 3)]
            output.append(_record(
                row=row, row_number=int(row_number), period=period, territory=territory,
                source_hash=source_hash, ingested_at=ingested_at,
            ))
    if not output:
        raise ValueError("ISPRA emissions workbook produced no retained observations")
    return output


def _summarize(source: dict, destination: Path) -> dict:
    table = pd.read_parquet(destination)
    return {
        "source": source,
        "records": len(table),
        "records_by_period": table.groupby("reference_year").size().to_dict(),
        "records_by_metric": table.groupby("metric_id").size().to_dict(),
        "records_by_level": table.groupby("territory_level").size().to_dict(),
        "canonical_path": str(destination),
        "canonical_bytes": destination.stat().st_size,
    }


def fetch_emissions(raw_root: Path, *, offline: bool = False) -> dict:
    workbook = raw_root / "raw" / SOURCE_ID / "disaggregazione-provinciale-2023.xlsx"
    return download_registered_source(SOURCE, workbook, offline=offline)


def ingest_emissions(raw_root: Path, canonical_root: Path, force: bool = False, offline: bool = False) -> dict:
    workbook = raw_root / "raw" / SOURCE_ID / "disaggregazione-provinciale-2023.xlsx"
    source = fetch_emissions(raw_root, offline=offline)
    destination = canonical_root / "emissions" / "dataset_version=2026-2023-disaggregation" / "observations.parquet"
    if source.get("unchanged") and destination.exists() and not force:
        current = pd.read_parquet(destination, columns=["reference_year", "territory_level"])
        if set(current["reference_year"].astype(int)) == set(PERIOD_REFERENCE_YEARS) and set(current["territory_level"]) == {"province"}:
            return _summarize(source, destination) | {"changed": False, "skipped": True}
    frame = pd.read_excel(workbook, sheet_name=SHEET, dtype={"COD_POL": str, "SNAP": str})
    _validate_contract(frame)
    records = _records(frame, canonical_root, source["sha256"], source["acquired_at"])
    table = pd.DataFrame(records)
    if table.duplicated(["observation_id"]).any():
        raise ValueError("Duplicate canonical emissions observation IDs")
    destination.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(destination, index=False, compression="zstd")
    return _summarize(source, destination) | {"changed": True}
