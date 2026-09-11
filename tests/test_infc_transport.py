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


@pytest.mark.parametrize("proxy_outcome", [403, 407, 429, "ConnectTimeout", "ReadTimeout", "ConnectionError", "ChunkedEncodingError"])
def test_exhausted_routes_have_only_sanitized_diagnostics(monkeypatch, proxy_outcome):
    import json
    import traceback
    import requests
    from types import SimpleNamespace

    secret = "http://secret-user:secret-password@private-proxy.example:3128"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("INFC_HTTPS_PROXIES", secret)
    calls = []
    closed = []

    def get(url, **kwargs):
        calls.append(kwargs)
        assert kwargs["verify"] is True
        if "proxies" in kwargs and isinstance(proxy_outcome, str):
            raise getattr(requests.exceptions, proxy_outcome)(secret)
        status = proxy_outcome if "proxies" in kwargs else 403
        return SimpleNamespace(status_code=status, close=lambda: closed.append(status))

    with pytest.raises(transport.InfcTransportError) as caught:
        transport.get_with_infc_fallback(get, "https://www.inventarioforestale.org/a.zip", direct_attempts=2, retry_sleep=lambda _: None, verify=False)
    expected = {"route": "proxy_1", "error": proxy_outcome} if isinstance(proxy_outcome, str) else {"route": "proxy_1", "http_status": proxy_outcome}
    assert caught.value.diagnostics == {"direct_attempts": 2, "direct": [{"route": "direct", "http_status": 403}] * 2, "proxy_candidates": 1, "proxies": [expected]}
    serialized = json.dumps(caught.value.diagnostics) + str(caught.value) + "".join(traceback.format_exception(caught.value))
    for forbidden in (secret, "secret-user", "secret-password", "private-proxy.example"):
        assert forbidden not in serialized
    assert caught.value.__cause__ is None
    assert len(calls) == 3
    assert closed == ([403, 403] if isinstance(proxy_outcome, str) else [403, 403, proxy_outcome])


def test_direct_exception_and_multiple_proxy_ordinals(monkeypatch):
    import requests
    from types import SimpleNamespace
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("INFC_HTTPS_PROXIES", "private-one.example:3128,private-two.example:3128")
    events = iter([requests.ConnectTimeout("sensitive direct URL"), 403, requests.ConnectionError("private-two.example")])
    def get(*args, **kwargs):
        event = next(events)
        if isinstance(event, Exception):
            raise event
        return SimpleNamespace(status_code=event, close=lambda: None)
    with pytest.raises(transport.InfcTransportError) as caught:
        transport.get_with_infc_fallback(get, "https://www.inventarioforestale.org/a.zip")
    assert caught.value.diagnostics == {"direct_attempts": 1, "direct": [{"route": "direct", "error": "ConnectTimeout"}], "proxy_candidates": 2, "proxies": [{"route": "proxy_1", "http_status": 403}, {"route": "proxy_2", "error": "ConnectionError"}]}
    assert "sensitive" not in str(caught.value)


@pytest.mark.parametrize("proxy_success", [False, True])
def test_success_keeps_response_and_transport(monkeypatch, proxy_success):
    from types import SimpleNamespace
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("INFC_HTTPS_PROXIES", "private.example:3128")
    response = SimpleNamespace(status_code=200)
    calls = []
    def get(*args, **kwargs):
        calls.append(kwargs)
        assert kwargs["verify"] is True
        return SimpleNamespace(status_code=403, close=lambda: None) if proxy_success and "proxies" not in kwargs else response
    actual, route = transport.get_with_infc_fallback(get, "https://www.inventarioforestale.org/a.zip")
    assert actual is response
    assert route == ("proxy" if proxy_success else "direct")
    assert len(calls) == (2 if proxy_success else 1)


def test_diagnostic_workflow_is_read_only_and_uploads_only_sanitized_infc(tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path
    import yaml

    workflow = yaml.load((Path(__file__).parents[1] / ".github/workflows/check-infc.yml").read_text(), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    steps = workflow["jobs"]["check-infc"]["steps"]
    command = next(step for step in steps if "check-sources" in step.get("run", ""))
    assert "uv run stato-data check-sources" in command["run"]
    assert "--domain forests" in command["run"]
    assert "--publish r2" in command["run"]
    assert "--report reports/forests-source-check.json" in command["run"]
    assert "> /dev/null 2>&1" in command["run"]
    assert set(command["env"]) == {"R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT", "R2_BUCKET", "INFC_HTTPS_PROXIES"}
    runs = "\n".join(step.get("run", "") for step in steps)
    assert "stato-data run" not in runs and "pytest" not in runs
    assert "uv sync --all-groups --frozen" in runs
    assert not any("cache" in step.get("uses", "") for step in steps)
    upload = next(step for step in steps if "upload-artifact" in step.get("uses", ""))
    assert upload["if"] == "always() && steps.sanitize.outcome == 'success'"
    assert upload["with"]["path"] == "reports/infc-transport-diagnostics.json"
    script = next(step["run"] for step in steps if step.get("id") == "sanitize").split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    raw = tmp_path / "reports/forests-source-check.json"
    raw.parent.mkdir()
    secret = "http://secret-user:secret-password@private-proxy.example:3128"
    report = {"sources": [
        {"source_id": "copernicus-hrl-forests", "status": "changed", "secret": secret},
        {"source_id": "infc-2015-forests", "status": "unverifiable", "reason": "InfcTransportError", "resolved_url": secret,
         "transport_diagnostics": {"direct_attempts": 1, "direct": [{"route": "direct", "http_status": 403}], "proxy_candidates": 1, "proxies": [{"route": "proxy_1", "error": "ConnectTimeout"}]}}
    ]}
    raw.write_text(json.dumps(report))
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0
    artifact = tmp_path / upload["with"]["path"]
    assert len(json.loads(artifact.read_text())["sources"]) == 1
    for forbidden in (secret, "private-proxy.example", "secret-user", "secret-password", "copernicus"):
        assert forbidden not in result.stdout + result.stderr + artifact.read_text()
    report["sources"][1]["transport_diagnostics"]["proxies"][0]["error"] = secret
    raw.write_text(json.dumps(report))
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode != 0
    assert not artifact.exists()
    assert secret not in result.stdout + result.stderr
