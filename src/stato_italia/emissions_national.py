from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pandas as pd

from .common import stable_id
from .download import download_registered_source
from .registry import load_source
from .territories import load_territory_index

GHG_SOURCE = load_source("ispra-emissions-ghg-2026")
NFR_SOURCE = load_source("ispra-emissions-nfr-2026")
GHG_YEARS = tuple(GHG_SOURCE["source_contract"]["expected_years"])
NFR_YEARS = tuple(NFR_SOURCE["source_contract"]["expected_years"])

NFR_POLLUTANTS = {
    "NOx (as NO2)": ("emissions_air_nox_as_no2", "kt"),
    "NMVOC": ("emissions_air_nmvoc", "kt"),
    "SOx (as SO2)": ("emissions_air_sox_as_so2", "kt"),
    "NH3": ("emissions_air_nh3", "kt"),
    "PM2.5": ("emissions_air_pm25", "kt"),
    "PM10": ("emissions_air_pm10", "kt"),
    "TSP": ("emissions_air_tsp", "kt"),
    "BC": ("emissions_air_black_carbon", "kt"),
    "CO": ("emissions_air_co", "kt"),
    "Pb": ("emissions_air_lead", "t"),
    "Cd": ("emissions_air_cadmium", "t"),
    "Hg": ("emissions_air_mercury", "t"),
    "As": ("emissions_air_arsenic", "t"),
    "Cr": ("emissions_air_chromium", "t"),
    "Cu": ("emissions_air_copper", "t"),
    "Ni": ("emissions_air_nickel", "t"),
    "Se": ("emissions_air_selenium", "t"),
    "Zn": ("emissions_air_zinc", "t"),
    "PCDD/ PCDF (dioxins/ furans)": ("emissions_air_pcd_dioxins_furans", "g I-TEQ"),
    "benzo(a) pyrene": ("emissions_air_benzo_a_pyrene", "t"),
    "benzo(b) fluoranthene": ("emissions_air_benzo_b_fluoranthene", "t"),
    "benzo(k) fluoranthene": ("emissions_air_benzo_k_fluoranthene", "t"),
    "Indeno (1,2,3-cd) pyrene": ("emissions_air_indeno_123cd_pyrene", "t"),
    "Total 1-4": ("emissions_air_pah_total_1_4", "t"),
    "HCB": ("emissions_air_hexachlorobenzene", "kg"),
    "PCBs": ("emissions_air_pcbs", "kg"),
}
SPECIAL_VALUE_STATES = {
    "C": "suppressed",
    "IE": "unavailable",
    "NA": "not_applicable",
    "NA,NO": "not_applicable",
    "NE": "unavailable",
    "NE,NO": "unavailable",
    "NO": "not_applicable",
}


def _text(value: object, field: str) -> str:
    if pd.isna(value) or not str(value).strip():
        raise ValueError(f"Missing {field}")
    return re.sub(r"\s+", " ", str(value)).strip()


def _source_value(value: object) -> tuple[float | None, str, str | None]:
    if pd.isna(value):
        return None, "unavailable", None
    if isinstance(value, str):
        text = value.strip()
        if text in SPECIAL_VALUE_STATES:
            return None, SPECIAL_VALUE_STATES[text], text
        try:
            return float(text), "observed", None
        except ValueError as exc:
            raise ValueError(f"Unknown ISPRA emissions value notation: {value!r}") from exc
    return float(value), "observed", None


def _year_columns(row: pd.Series, expected_years: tuple[int, ...], context: str) -> dict[int, int]:
    years: dict[int, int] = {}
    for column, value in row.items():
        if pd.isna(value):
            continue
        try:
            year = int(value)
        except (TypeError, ValueError):
            continue
        if float(value) == year and year in expected_years:
            years[year] = int(column)
    if tuple(sorted(years)) != expected_years:
        raise ValueError(f"Unexpected {context} years: found={sorted(years)}, expected={list(expected_years)}")
    return years


def _country(canonical_root: Path) -> dict:
    return load_territory_index(canonical_root, 2025)["it:country:IT"]


def _record(
    *, source: dict, source_hash: str, locator: str, metric_id: str, territory: dict,
    year: int, value: float | None, value_state: str, dimensions: dict, ingested_at: str,
) -> dict:
    start, end = date(year, 1, 1).isoformat(), date(year, 12, 31).isoformat()
    return {
        "observation_id": stable_id(source["source_id"], source_hash, locator, metric_id),
        "dataset_id": source["source_id"],
        "dataset_version": source["dataset_version"],
        "source_asset_sha256": source_hash,
        "source_row_locator": locator,
        "source_dimensions_json": json.dumps(dimensions, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "metric_id": metric_id,
        "territory_id": territory["territory_id"],
        "territory_version_id": territory["territory_version_id"],
        "territory_level": "country",
        "period_start": start,
        "period_end": end,
        "reference_year": year,
        "value_decimal": value,
        "value_state": value_state,
        "unit_ucum": dimensions["source_unit"],
        "official_status": "unknown",
        "quality_flags": [],
        "methodology_version": source["dataset_version"],
        "ingested_at": ingested_at,
    }


def _ghg_metric(gas: str, category: str) -> str:
    if gas != "f_gases":
        return f"emissions_ghg_{gas}"
    return "emissions_ghg_f_gases_co2e" if "CO2 equivalents" in category else "emissions_ghg_f_gases"


def _ghg_records(workbook: Path, canonical_root: Path, source_hash: str, ingested_at: str) -> list[dict]:
    output: list[dict] = []
    territory = _country(canonical_root)
    for sheet, contract in GHG_SOURCE["source_contract"]["sheets"].items():
        raw = pd.read_excel(workbook, sheet_name=sheet, header=None)
        header_row, unit_row, data_row = (int(contract[key]) for key in ("header_row", "unit_row", "data_row"))
        years = _year_columns(raw.iloc[header_row], GHG_YEARS, f"ISPRA GHG {sheet}")
        unit = _text(raw.iloc[unit_row, 1], f"ISPRA GHG {sheet} unit")
        if unit != contract["expected_unit"]:
            raise ValueError(f"Unexpected ISPRA GHG unit for {sheet}: {unit!r}")
        for row_number in range(data_row, len(raw)):
            category = raw.iloc[row_number, 0]
            if pd.isna(category):
                continue
            category_text = _text(category, f"ISPRA GHG {sheet} category")
            for year, column in years.items():
                value, value_state, notation = _source_value(raw.iloc[row_number, column])
                dimensions = {"gas": contract["gas"], "inventory_category": category_text, "source_unit": unit}
                if notation:
                    dimensions["source_notation"] = notation
                output.append(_record(
                    source=GHG_SOURCE, source_hash=source_hash, locator=f"{sheet}:{row_number + 1}:{year}",
                    metric_id=_ghg_metric(str(contract["gas"]), category_text), territory=territory, year=year,
                    value=value, value_state=value_state, dimensions=dimensions, ingested_at=ingested_at,
                ))
    if not output:
        raise ValueError("ISPRA GHG workbook produced no canonical observations")
    return output


def _nfr_records(workbook: Path, canonical_root: Path, source_hash: str, ingested_at: str) -> list[dict]:
    output: list[dict] = []
    territory = _country(canonical_root)
    contract = NFR_SOURCE["source_contract"]["header_rows"]
    for year in NFR_YEARS:
        raw = pd.read_excel(workbook, sheet_name=str(year), header=None)
        pollutant_row, detail_row, unit_row, data_row = (
            int(contract[key]) for key in ("pollutant", "pollutant_detail", "unit", "data")
        )
        reported_year = _text(raw.iloc[5, 1], f"ISPRA NFR {year} reported YEAR")
        if reported_year != str(year):
            raise ValueError(f"Unexpected ISPRA NFR sheet/year relation: sheet={year}, reported={reported_year!r}")
        pollutants = {}
        in_pah_block = False
        for column, value in raw.iloc[pollutant_row].items():
            if pd.isna(value):
                if in_pah_block and not pd.isna(raw.iloc[detail_row, column]):
                    pollutants[int(column)] = _text(raw.iloc[detail_row, column], f"ISPRA NFR {year} PAH pollutant")
                continue
            label = _text(value, f"ISPRA NFR {year} pollutant")
            if label in {"PAHs", "Benzoapyrenes"}:
                label = _text(raw.iloc[detail_row, column], f"ISPRA NFR {year} PAH pollutant")
                in_pah_block = True
            else:
                in_pah_block = False
            pollutants[int(column)] = label
        selected = {column: NFR_POLLUTANTS[label] for column, label in pollutants.items() if label in NFR_POLLUTANTS}
        if set(label for label in pollutants.values() if label in NFR_POLLUTANTS) != set(NFR_POLLUTANTS):
            raise ValueError(f"Unexpected ISPRA NFR pollutants for {year}")
        current_group: str | None = None
        for row_number in range(data_row, len(raw)):
            nfr_code = raw.iloc[row_number, 1]
            if pd.isna(nfr_code):
                continue
            if not pd.isna(raw.iloc[row_number, 0]):
                current_group = _text(raw.iloc[row_number, 0], f"ISPRA NFR {year} group")
            nfr_code_text = _text(nfr_code, f"ISPRA NFR {year} code")
            if not re.match(r"^\d", nfr_code_text):
                continue
            if current_group is None:
                raise ValueError(f"Missing ISPRA NFR group for code {nfr_code_text!r} in {year}")
            nfr_label = _text(raw.iloc[row_number, 2], f"ISPRA NFR {year} label")
            for column, (metric_id, expected_unit) in selected.items():
                source_unit = _text(raw.iloc[unit_row, column], f"ISPRA NFR {year} {metric_id} unit")
                if source_unit != expected_unit:
                    raise ValueError(f"Unexpected ISPRA NFR unit for {metric_id}: {source_unit!r}")
                value, value_state, notation = _source_value(raw.iloc[row_number, column])
                dimensions = {
                    "nfr_code": nfr_code_text,
                    "nfr_group": current_group,
                    "nfr_label": nfr_label,
                    "pollutant_label": pollutants[column],
                    "source_unit": source_unit,
                }
                if notation:
                    dimensions["source_notation"] = notation
                output.append(_record(
                    source=NFR_SOURCE, source_hash=source_hash, locator=f"{year}:{row_number + 1}:{column}",
                    metric_id=metric_id, territory=territory, year=year, value=value,
                    value_state=value_state, dimensions=dimensions, ingested_at=ingested_at,
                ))
    if not output:
        raise ValueError("ISPRA NFR workbook produced no canonical observations")
    return output


def _write(records: list[dict], destination: Path) -> dict:
    table = pd.DataFrame(records)
    if table.duplicated(["observation_id"]).any():
        raise ValueError(f"Duplicate emissions observation IDs: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(destination, index=False, compression="zstd")
    return _summarize(table, destination)


def _summarize(table: pd.DataFrame, destination: Path) -> dict:
    return {
        "records": len(table),
        "records_by_metric": table.groupby("metric_id").size().to_dict(),
        "records_by_value_state": table.groupby("value_state").size().to_dict(),
        "canonical_path": str(destination),
        "canonical_bytes": destination.stat().st_size,
    }


def fetch_national_emissions(raw_root: Path, *, offline: bool = False) -> dict:
    raw_dir = raw_root / "raw"
    return {
        "greenhouse_gases": download_registered_source(
            GHG_SOURCE, raw_dir / GHG_SOURCE["source_id"] / "greenhouse-gases.xlsx", offline=offline,
        ),
        "air_pollutants_nfr": download_registered_source(
            NFR_SOURCE, raw_dir / NFR_SOURCE["source_id"] / "air-pollutants-nfr.xlsx", offline=offline,
        ),
    }


def ingest_national_emissions(raw_root: Path, canonical_root: Path, force: bool = False, offline: bool = False) -> dict:
    acquired = fetch_national_emissions(raw_root, offline=offline)
    ghg_destination = canonical_root / "emissions" / "national" / "greenhouse-gases" / f"dataset_version={GHG_SOURCE['dataset_version']}" / "observations.parquet"
    nfr_destination = canonical_root / "emissions" / "national" / "air-pollutants-nfr" / f"dataset_version={NFR_SOURCE['dataset_version']}" / "observations.parquet"
    reports: dict[str, dict] = {}
    for key, source, destination, records_fn in (
        ("greenhouse_gases", GHG_SOURCE, ghg_destination, _ghg_records),
        ("air_pollutants_nfr", NFR_SOURCE, nfr_destination, _nfr_records),
    ):
        source_metadata = acquired[key]
        if source_metadata.get("unchanged") and destination.exists() and not force:
            table = pd.read_parquet(destination)
            reports[key] = _summarize(table, destination) | {"source": source_metadata, "changed": False, "skipped": True}
            continue
        reports[key] = _write(
            records_fn(
                raw_root / "raw" / source["source_id"] / ("greenhouse-gases.xlsx" if key == "greenhouse_gases" else "air-pollutants-nfr.xlsx"),
                canonical_root, source_metadata["sha256"], source_metadata["acquired_at"],
            ),
            destination,
        ) | {"source": source_metadata, "changed": True}
    return {"changed": any(report["changed"] for report in reports.values()), "datasets": reports}
