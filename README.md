# Stato d'Italia — data foundation

Milestone 1–4 only. No Next.js UI.

Start with [project context](project-context.md), [working rules](AGENTS.md),
and the accepted [architecture decisions](docs/adr/).

```sh
uv sync --all-groups
uv run stato-data run --workdir data --output artifacts
uv run pytest
```

Default run downloads official ISPRA/SNPA soil workbook and ISTAT generalized
administrative boundaries for source-relevant years. `data/` and `artifacts/`
are intentionally untracked.

R2 publish needs all variables below. Without them, pipeline publishes and
tests atomically into local object-store only.

```text
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_ENDPOINT
R2_BUCKET
```
