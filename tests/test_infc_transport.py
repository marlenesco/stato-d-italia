import pytest

import stato_italia.infc_transport as transport


def test_configured_proxies_preserve_multiline_and_comma_priority() -> None:
    assert transport.configured_infc_proxies(
        "proxy-one.example:3128\nhttp://proxy-two.example:443,https://proxy-three.example:9443\n"
    ) == (
        "http://proxy-one.example:3128",
        "http://proxy-two.example:443",
        "https://proxy-three.example:9443",
    )


@pytest.mark.parametrize("value", ["ftp://proxy.example:21", "proxy.example", "http://proxy.example:8080/path"])
def test_invalid_configured_proxy_fails_closed(value: str) -> None:
    with pytest.raises(ValueError, match="Invalid INFC proxy"):
        transport.configured_infc_proxies(value)


def test_proxy_candidates_require_github_actions_and_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://www.inventarioforestale.org/asset.zip"
    monkeypatch.setenv("INFC_HTTPS_PROXIES", "http://proxy.example:3128")

    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert transport.infc_proxy_candidates(url) == ()

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert transport.infc_proxy_candidates(url) == ("http://proxy.example:3128",)

    monkeypatch.delenv("INFC_HTTPS_PROXIES")
    assert transport.infc_proxy_candidates(url) == ()
