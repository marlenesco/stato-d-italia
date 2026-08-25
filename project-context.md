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
- Aggiornamento dei dati indipendente dal deploy del futuro frontend.
- Il progetto deve fallire esplicitamente quando una fonte cambia contratto.

## Fase corrente

Sono autorizzate le milestone **1–4**:

1. contratti, registry, schemi e ADR;
2. infrastruttura di release R2;
3. territori storici ISTAT e geometrie/PMTiles;
4. ingestione reale ISPRA/SNPA del consumo di suolo.

La vertical slice Next.js non fa ancora parte della fase corrente.

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
futuro Next.js su Vercel
```

Decisioni già accettate:

- R2 è lo storage primario; nessun Neon nell'MVP.
- Gli oggetti dati e `release.json` sono immutabili/content-addressed.
- Solo `manifest.json` attiva una release completa ed è mutabile.
- Il futuro frontend non deve fare da proxy ordinario per i payload dati.
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
territoriale ISTAT 2025-01-01. Questa relazione temporale deve restare esplicita
nella provenance e, in futuro, nella UI.

I buchi temporali della fonte non devono essere interpolati.

## Storage e ambienti

Durante lo sviluppo può essere usato l'endpoint pubblico R2 di sviluppo. Il
frontend futuro deve comunque leggere la base URL dei dati da configurazione, in
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

## Documenti operativi

- `docs/data-model.md`
- `docs/runbook.md`

La metodologia statistica completa di trend, anomalie, percentile e confronti
verrà definita in un ADR dedicato prima della milestone analytics/frontend.
