# ADR 0005: source provenance is a release artifact

Status: accepted.

Every raw object has resolved URL, acquisition time, HTTP ETag/Last-Modified,
content type, byte size and SHA-256 sidecar. Canonical observations retain raw
checksum and source row locator. Sources are checked conditionally; an unchanged
checksum produces a no-op run and cannot advance `manifest.json`.

