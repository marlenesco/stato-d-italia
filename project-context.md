# Stato d'Italia — contesto del progetto

## Scopo

**Stato d'Italia** è un progetto civico open source per rendere comprensibili,
confrontabili e verificabili nel tempo dati ambientali e territoriali italiani.

Il valore del progetto deriva da normalizzazione, contestualizzazione, confronto e
analisi riproducibile dei dati ufficiali, non dalla semplice ripubblicazione di
grafici o portali esistenti.

## Principi

- Dati ufficiali e pubblici prima di tutto.
- Provenienza visibile e verificabile.
- Nessuna granularità territoriale inventata.
- Nessuna interpolazione silenziosa dei periodi mancanti.
- Dati ufficiali e metriche derivate sempre distinguibili.
- Storico e confronto territoriale sono più importanti del realtime.
- Comuni, Province/equivalenti, Regioni e Italia sono entità di prima classe.
- Aggiornamento dei dati indipendente dal deploy del frontend operativo.
- Il progetto deve fallire esplicitamente quando una fonte cambia contratto.

## Fase corrente

Sono operativi: registry e contratti, release R2, territori storici/PMTiles,
Suolo, Acqua, Emissioni, Dissesto e Foreste, frontend Next.js e profili
territoriali. La UI legge artifact delivery senza database, proxy dati ordinario
o calcoli che inventino granularità.

## Architettura accettata

```text
Fonti ufficiali
      ↓
GitHub Actions
      ↓
raw archive
      ↓
validazione / normalizzazione
      ↓
canonical Parquet
      ↓
derived + delivery artifacts
      ↓
Cloudflare R2 / CDN
      ↓
Next.js su Vercel
```

Decisioni già accettate:

- R2 è lo storage primario; nessun Neon nell'MVP.
- Gli oggetti dati e `release.json` sono immutabili/content-addressed.
- Solo `manifest.json` attiva una release completa ed è mutabile.
- Il frontend non deve fare da proxy ordinario per i payload dati.
- La pubblicazione di nuovi dati non deve richiedere una build Vercel.
- Le geometrie amministrative sono versionate e distribuite come PMTiles.
- MapLibre sarà il renderer previsto per la futura UI.

## Politica territoriale

Un territorio logico può avere più versioni amministrative nel tempo.

Fusioni, scissioni, soppressioni, trasferimenti di confine o cambi di genitore
producono una rottura esplicita della serie, salvo l'esistenza di un mapping
ufficiale e documentato utilizzabile per quel dataset.

Non ricostruire serie storiche sui confini correnti per comodità grafica.

## Fonte reale corrente

`ispra-soil-2025` identifica il workbook ISPRA/SNPA attualmente usato per la
vertical slice dati sul consumo di suolo.

La fonte contiene:

- variazioni 2006–2012;
- variazioni 2012–2015;
- periodi annuali successivi fino al 2024;
- valori di stock 2024;
- righe Italia, Regione, Provincia/equivalente e Comune.

Gli identificativi comunali presenti nella fonte sono coerenti con il riferimento
territoriale ISTAT 2025-01-01. Questa relazione temporale resta esplicita in
provenance e UI.

I buchi temporali della fonte non devono essere interpolati.

## Storage e ambienti

Durante lo sviluppo può essere usato l'endpoint pubblico R2 di sviluppo. Il
frontend deve comunque leggere la base URL dei dati da configurazione, in
modo da poter passare a un custom domain/CDN senza cambiare i contratti dati.

Raw tabellari/vettoriali, canonical e delivery non sono contenuto Git. I raster
pesanti hanno retention selettiva secondo ADR 0001.

## Comandi principali

```sh
uv sync --all-groups --frozen
uv run pytest -q
uv run stato-data run --workdir data --output artifacts
uv run stato-data run --publish r2
```

Il publish predefinito deve essere sicuro per lo sviluppo. Le credenziali R2 non
sono mai contenute nel repository.

## Decision records

- `docs/adr/0001-data-storage-and-releases.md`
- `docs/adr/0002-territory-history.md`
- `docs/adr/0003-canonical-and-derived-data.md`
- `docs/adr/0004-maps.md`
- `docs/adr/0005-source-provenance.md`
- `docs/adr/0006-source-contracts-and-validation.md`
- `docs/adr/0007-analytics-and-comparisons.md`
- `docs/adr/0008-multidimensional-official-observations.md`
- `docs/adr/0009-temporal-ui-comparisons.md`
- `docs/adr/0010-responsive-data-explorer.md`
- `docs/adr/0011-persistent-map-selection.md`
- `docs/adr/0012-territory-profile-insights.md`
- `docs/adr/0013-persistent-source-state-and-scoped-workflows.md`

## Documenti operativi

- `docs/data-model.md`
- `docs/runbook.md`

La metodologia di trend, percentile e confronti è definita da ADR 0007; UI e
delivery applicano solo risultati derivati documentati e verificabili.
