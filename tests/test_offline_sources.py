from pathlib import Path

import pytest

from stato_italia.download import download


def test_offline_source_registers_local_raw_bytes(tmp_path: Path) -> None:
    asset = tmp_path / "raw" / "source" / "asset.xlsx"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"official bytes")

    first = download("https://example.test/asset.xlsx", asset, "source", offline=True)
    second = download("https://example.test/asset.xlsx", asset, "source", offline=True)

    assert first["acquisition_mode"] == "local_supplied"
    assert first["unchanged"] is False
    assert second["unchanged"] is True
    assert (asset.with_suffix(".xlsx.metadata.json")).exists()


def test_offline_source_fails_when_asset_is_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Offline source asset missing"):
        download("https://example.test/missing.xlsx", tmp_path / "missing.xlsx", "source", offline=True)
