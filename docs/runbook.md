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

## Acquisizione automatica locale

Ogni dominio scarica direttamente dalla propria fonte ufficiale e archivia raw,
licenza/metadati, checksum e URL. Nessun `cp` o input manuale.

Per acquisire solo dissesto IdroGEO:

```sh
uv run stato-data fetch dissesto --workdir data
```

Per acquisire solo raw del dominio Emissioni ISPRA:

```sh
uv run stato-data fetch emissions --workdir data
```

Per acquisire, validare e pubblicare nella object store locale tutti i domini
configurati:

```sh
uv run stato-data run --workdir data --output artifacts --report reports/local-ingestion.json
```

`run` invoca anche l'acquisizione IdroGEO. Usa i quattro export JSON ufficiali
senza `outputFormat`, quindi non scarica CSV/Excel né effettua richieste per
singolo territorio. Archivio raw conserva le risposte esatte. Un errore HTTP,
schema o copertura territoriale interrompe flusso.

## Riesecuzione offline

`--offline` non effettua richieste HTTP e riusa solo raw già acquisiti:

```sh
uv run stato-data run --offline --workdir data --output artifacts --report reports/local-ingestion.json
```

Poi controlli obbligatori:

```sh
uv run pytest -q
git diff --check
```

## Publish R2

```sh
uv run stato-data run --publish r2
```

Prima del publish verificare che le credenziali siano fornite dall'ambiente e non
da file versionati.

## Source state e workflow

Ogni release contiene `metadata/source-state.json` content-addressed. È letto
attraverso release attiva e `manifest.json`; non esiste un secondo puntatore
mutabile. Per controllare una scope senza dipendere dalla cache GitHub:

```sh
uv run stato-data check-sources --scope data --publish r2
uv run stato-data check-sources --scope geospatial --publish r2
```

Il controllo usa `GET` condizionale quando possibile, mai solo `HEAD`. I due
workflow sono `ingest-data.yml` (tabellari/delivery) e
`ingest-geospatial.yml` (catalogo Copernicus, raster e zonal statistics).
La cache Actions accelera canonical geospaziale ma non decide se una fonte è
nuova. Se tale canonical manca nel workflow fast, pipeline fallisce prima di
pubblicare release incompleta.

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
- non caricare oggetti già content-addressed;
- non creare release e non aggiornare `manifest.json`.

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
source checks / changed / unchanged
canonical bytes
delivery bytes
objects uploaded / reused
bytes uploaded to R2
release referenced bytes (dimensione logica)
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
