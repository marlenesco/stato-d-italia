# Stato d'Italia — working rules

## Scope

This repository currently implements the data foundation (milestones 1–4):
data contracts, R2 release infrastructure, historical ISTAT territories/maps,
and real ISPRA/SNPA soil-consumption ingestion.

Do not add the Next.js frontend, a database, runtime AI/LLM features, or unrelated
domains unless an approved milestone or ADR explicitly requires them.

## Non-negotiable data rules

- Prefer official, public, documented sources. Record exceptions explicitly.
- Never fabricate municipal granularity, missing observations, or historical
  territorial mappings.
- Preserve raw source bytes when retention policy allows it; always retain enough
  metadata and SHA-256 provenance to identify the exact acquired artifact.
- Canonical tabular observations are Parquet.
- Official observations and project-derived metrics are separate artifacts.
- Every derived metric must identify its algorithm version and source observations.
- Missing, suppressed, unavailable, not-applicable and zero are different states.
  Do not collapse them.
- Publish immutable, content-addressed R2 objects first. Activate a release by
  updating `manifest.json` only after full validation.
- A changed upstream contract must fail loudly. Never silently coerce an unknown
  source shape into the current schema.
- Historical map values must join to the territory/geometry version valid for the
  source reference period.

## Repository conventions

- Source registry: `config/sources/`
- Metric dictionary: `config/metrics/`
- JSON schemas: `schemas/`
- Architecture decisions: `docs/adr/`
- Cross-cutting data model: `docs/data-model.md`
- Operational procedures: `docs/runbook.md`
- Runtime raw, canonical and delivery artifacts live in ignored `data/` and
  `artifacts/`; do not commit them.
- Human-facing project documentation is written in Italian. Code, schema fields,
  identifiers and paths remain in English.
- Do not edit an accepted ADR to silently change a decision. Add a superseding ADR
  or explicitly change its status and document why.

## Secrets

- Never log, commit, snapshot or expose R2 credentials or API tokens.
- GitHub Actions reads secrets from repository/environment secrets.
- Tests and fixtures must use fake credentials only.

## Required checks

Before considering a data-contract, ingestion, release, territory, map or
provenance change complete, run:

```sh
uv run pytest -q
uv run stato-data run --workdir data --output artifacts
git diff --check
```

If the change touches R2 publishing, also validate the publish flow against the
configured non-production target before using the production manifest.

Read `project-context.md`, `docs/data-model.md` and the applicable ADRs before
changing data contracts, release behavior, territory handling, maps or provenance.
