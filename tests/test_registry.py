from stato_italia.registry import load_source


def test_soil_source_registry_is_complete() -> None:
    source = load_source("ispra-soil")
    for key in ("publisher", "download_url", "license", "methodology_url", "known_limitations"):
        assert source[key]
