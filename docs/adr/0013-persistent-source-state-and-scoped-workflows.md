# ADR 0013: source state persistente e workflow scoped

**Stato:** accepted

## Contesto

Un runner GitHub Actions pulito non conserva stato locale fonti. Cache può
sparire e non può decidere publish. Publish che scandisce `data/raw` può inoltre
includere asset non usati dalla release.

## Decisione

Ogni release include `metadata/source-state.json` come oggetto immutabile
content-addressed, referenziato da `release.json`. Contiene per asset source id,
URL risolto, ETag/Last-Modified quando disponibili, SHA-256, bytes,
dataset/versione/periodo e timestamp controllo. Run seguente legge state solo
passando dalla release attiva indicata da `manifest.json`: quest'ultimo resta
unico puntatore mutabile.

Preflight usa `GET` condizionale, non `HEAD` come controllo esclusivo. Cataloghi
Copernicus sono confrontati per signature autenticata. Risposta non verificabile
è cambiamento: pipeline fail-closed.

`ingest-data.yml` possiede fonti tabellari e delivery;
`ingest-geospatial.yml` possiede cataloghi, raster e zonal statistics. Entrambi
pubblicano con stessa sequenza atomica. Cache Actions è solo acceleratore;
workflow data senza canonical geospaziale riutilizzabile fallisce invece di
degradare release.

Release è costruita da output dichiarati: raw con sidecar provenance,
canonical/derived/delivery e PMTiles della pipeline. Nessuna scansione globale
di `data/raw` è ammessa.

## Conseguenze

- No-op non crea release, non ricarica oggetti e non aggiorna manifest.
- Report distingue dimensione logica referenziata da byte nuovi caricati.
- State avanza solo insieme a release verificata; errore non altera release.
