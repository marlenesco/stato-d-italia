# Runbook operativo

## Setup locale

```sh
uv sync --all-groups --frozen
```

## Test

```sh
uv run pytest -q
git diff --check
```

## Pipeline locale

```sh
uv run stato-data run --workdir data --output artifacts
```

L'esecuzione locale non deve modificare la release R2 attiva.

## Publish R2

```sh
uv run stato-data run --publish r2
```

Prima del publish verificare che le credenziali siano fornite dall'ambiente e non
da file versionati.

## CORS R2/CDN per frontend diretto

MapLibre, PMTiles e JSON vengono letti dal browser direttamente da R2/CDN,
senza proxy Vercel. Configurare quindi CORS sul bucket prima del deploy web:

- `GET`, `HEAD`;
- origine esatta del sito pubblico e origine locale di sviluppo;
- header richiesta `Range` e header esposti `Content-Range`, `Accept-Ranges`,
  `Content-Length`, `ETag`.

`config/r2-cors.example.json` è template: sostituire/aggiungere solo origini
effettivamente autorizzate. Non usare `*` in produzione senza decisione
esplicita. Vercel preview richiede origini preview dichiarate oppure test locale.

## Ordine di publish

```text
download
→ validate
→ normalize
→ generate
→ hash
→ upload immutable objects
→ verify objects
→ publish immutable release.json
→ verify release
→ update manifest.json
```

`manifest.json` non deve essere aggiornato in caso di errore precedente.

## No-op

Se il contenuto della fonte è invariato:

- non duplicare il raw;
- non rigenerare dati senza motivo.

Una modifica di provenance significativa può comunque produrre una metadata-only
release secondo ADR 0005.

## Rollback

Il rollback non modifica oggetti già pubblicati.

Procedura:

1. identificare una release precedente verificata;
2. verificare che tutti gli oggetti referenziati esistano ancora;
3. aggiornare `manifest.json` alla release scelta;
4. verificare il manifest pubblico.

## Failure policy

Se schema, unità, periodi o mapping territoriale non corrispondono al contratto:

- fail;
- non pubblicare;
- non correggere automaticamente la fonte;
- produrre diagnostica sufficiente a capire il cambiamento upstream.

## Controlli dopo ingestione reale

Registrare almeno:

```text
raw bytes
canonical bytes
delivery bytes
record count
accepted/rejected count
territory coverage by level
available periods and gaps
unresolved territory mappings
pipeline duration
source checksum
active release id
```

Queste misure servono anche a stimare la crescita dello storage R2.
