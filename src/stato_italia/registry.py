from __future__ import annotations

from pathlib import Path

import yaml


def load_source(registry_key: str) -> dict:
    path = Path(__file__).resolve().parents[2] / "config" / "sources" / f"{registry_key}.yaml"
    if not path.exists():
        raise ValueError(f"Unknown source registry entry: {registry_key}")
    payload = yaml.safe_load(path.read_text())
    if not payload.get("source_id"):
        raise ValueError(f"Source registry entry lacks source_id: {path}")
    return payload
