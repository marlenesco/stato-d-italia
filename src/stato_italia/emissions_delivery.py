from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .registry import load_source

DELIVERY_SCHEMA_VERSION = 1
DELIVERY_ALGORITHM_VERSION = "emissions-overview-v1"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")


def _dimensions(value: str) -> dict:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Unexpected emissions source dimensions contract")
    return parsed


def _ghg_total_series(table: pd.DataFrame) -> list[list[float | int]]:
    total = table.loc[
        (table["metric_id"] == "emissions_ghg_co2e") & (table["value_state"] == "observed")
    ].copy()
    total = total.loc[total["source_dimensions_json"].map(lambda value: _dimensions(value).get("inventory_category") == "Total (net emissions) (4)")]
    if len(total) != 35 or total["reference_year"].duplicated().any():
        raise ValueError("Unexpected ISPRA GHG official total series contract")
    return [[int(row.reference_year), float(row.value_decimal)] for row in total.sort_values("reference_year").itertuples()]


def generate_emissions_delivery(
    greenhouse_gases_path: Path, air_pollutants_nfr_path: Path, provincial_path: Path,
    destination: Path, release_id: str, force: bool = False,
) -> dict:
    index_path = destination / "emissions" / "index.json"
    if index_path.exists() and not force:
        previous = json.loads(index_path.read_text())
        if previous.get("algorithmVersion") == DELIVERY_ALGORITHM_VERSION:
            files = sorted(path for path in (destination / "emissions").rglob("*.json"))
            return {"changed": False, "skipped": True, "files": files, "bytes": sum(path.stat().st_size for path in files)}

    ghg = pd.read_parquet(greenhouse_gases_path)
    nfr = pd.read_parquet(air_pollutants_nfr_path)
    provincial = pd.read_parquet(provincial_path)
    required = {"metric_id", "reference_year", "source_dimensions_json", "value_decimal", "value_state", "unit_ucum"}
    for name, table in (("GHG", ghg), ("NFR", nfr), ("provincial", provincial)):
        missing = required - set(table.columns)
        if missing:
            raise ValueError(f"{name} emissions canonical contract missing columns: {sorted(missing)}")

    series = _ghg_total_series(ghg)
    root = destination / "emissions"
    _write(root / "provenance.json", {
        "schemaVersion": DELIVERY_SCHEMA_VERSION,
        "releaseId": release_id,
        "theme": "emissions",
        "datasets": {
            "greenhouseGases": load_source("ispra-emissions-ghg-2026"),
            "airPollutantsNfr": load_source("ispra-emissions-nfr-2026"),
            "provincial": load_source("ispra-emissions-provincial-2026"),
        },
        "officialVsDerived": {
            "national_territorial_inventory": "Inventario nazionale ISPRA: non emissione dichiarata da singolo stabilimento e non concentrazione misurata nell'aria.",
            "provincial_disaggregation": "Stima ISPRA top-down per provincia e attività SNAP; non viene trasformata in dato comunale.",
            "derived_metric": "Nessuna somma o ranking è pubblicato in questo delivery.",
        },
    })
    overview_path = root / "overview.json"
    _write(overview_path, {
        "schemaVersion": DELIVERY_SCHEMA_VERSION,
        "releaseId": release_id,
        "theme": "emissions",
        "greenhouseGases": {
            "label": "Gas serra nazionali",
            "coverage": "Italia · 1990–2024",
            "unit": "kt CO2 equivalenti",
            "seriesLabel": "Totale emissioni nette ufficiale",
            "series": series,
            "metrics": ["CO2 equivalente", "CO2", "CH4", "N2O", "gas fluorurati"],
        },
        "airPollutantsNfr": {
            "label": "Inquinanti atmosferici nazionali",
            "coverage": "Italia · 1990–2024",
            "metrics": int(nfr["metric_id"].nunique()),
            "sourceDimensions": ["settore NFR", "inquinante", "unità fonte"],
        },
        "provincialDisaggregation": {
            "label": "Disaggregazione provinciale",
            "coverage": "Province · 2019 e 2023",
            "metrics": int(provincial["metric_id"].nunique()),
            "sourceDimensions": ["provincia", "attività SNAP", "inquinante"],
        },
        "provenanceRef": "delivery/emissions/provenance.json",
    })
    _write(index_path, {
        "schemaVersion": DELIVERY_SCHEMA_VERSION,
        "releaseId": release_id,
        "theme": "emissions",
        "algorithmVersion": DELIVERY_ALGORITHM_VERSION,
        "overview": "delivery/emissions/overview.json",
        "provenance": "delivery/emissions/provenance.json",
    })
    files = sorted(path for path in root.rglob("*.json"))
    return {"changed": True, "files": files, "bytes": sum(path.stat().st_size for path in files)}
