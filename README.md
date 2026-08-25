# Stato d'Italia — data foundation

Pipeline riproducibile per dati ambientali e territoriali ufficiali. Acquisisce
raw, valida contratti, normalizza in Parquet e pubblica release immutabili su
Cloudflare R2. Dati raw e artefatti non entrano in Git.

Consultare prima [contesto progetto](project-context.md), [regole di lavoro](AGENTS.md)
e [ADR](docs/adr/).

## Ambiente locale

Setup una volta:

```sh
uv sync --all-groups --frozen
```

Scaricare solo raw Dissesto dall'API pubblica ufficiale IdroGEO. Nessun file
da copiare manualmente:

```sh
uv run stato-data fetch dissesto --workdir data
```

Scaricare solo raw del dominio Emissioni ISPRA. Risolve il file effettivamente
esposto dalle landing ufficiali, poi conserva URL, checksum e metadata:

```sh
uv run stato-data fetch emissions --workdir data
```

Eseguire pipeline completa locale. Scarica tutti i domini configurati, valida,
genera canonical/delivery e pubblica soltanto in `artifacts/object-store` locale:

```sh
uv run stato-data run \
  --workdir data \
  --output artifacts \
  --report reports/local-ingestion.json
```

Rieseguire senza rete usando esclusivamente raw già acquisiti:

```sh
uv run stato-data run --offline --workdir data --output artifacts
```

Controlli:

```sh
uv run pytest -q
git diff --check
```

`data/`, `artifacts/` e `reports/` sono locali e ignorati. Un errore HTTP,
schema, copertura territoriale o mapping interrompe pipeline: nessun dato viene
inventato o convertito silenziosamente.

## Produzione — Cloudflare R2

Produzione usa stesso comando della pipeline locale, con `--publish r2`.
Configurare esclusivamente come GitHub Actions secrets:

```text
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_ENDPOINT
R2_BUCKET
```

Comando equivalente al job:

```sh
uv run stato-data run --publish r2
```

Workflow [Ingest official data](.github/workflows/ingest.yml) esegue test e
publish ogni lunedì alle 02:17 UTC. Può essere avviato manualmente da GitHub
Actions; input `force=true` rigenera anche fonti con checksum invariato.

Non esiste staging. Oggetti raw, canonical e delivery sono content-addressed e
immutabili; `release.json` è immutabile; solo `manifest.json` attiva release
completa. Se acquisizione, validazione, upload o verifica falliscono,
`manifest.json` non cambia e release R2 attiva resta invariata.

Rollback:

```sh
uv run stato-data rollback <release-id> --publish r2
```

Mai salvare credenziali R2 in file versionati. Dettagli operativi:
[runbook](docs/runbook.md).
