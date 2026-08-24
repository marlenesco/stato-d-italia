# ADR 0001: R2 content-addressed immutable releases

Status: accepted.

Raw tabular/vector source artifacts, canonical Parquet and delivery artifacts are
objects, not Git content. Object key is SHA-256-derived. A release is immutable
JSON referencing verified objects. Only `manifest.json` is mutable and advances
after every referenced object passes HEAD/checksum verification. Rollback rewrites
only this pointer to an already verified release. Rasters may have selective
retention; metadata, source URL and checksum are always retained.

