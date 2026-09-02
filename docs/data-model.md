# Modello dati

Questo documento descrive il modello logico corrente. Gli ADR definiscono le
decisioni architetturali; questo file può evolvere insieme agli schemi senza
richiedere un nuovo ADR per ogni campo.

## Entità principali

### Territory

Identità logica durevole di Italia, Regione, Provincia/equivalente o Comune.

Campi concettuali:

```text
territory_id
level
```

### TerritoryVersion

Versione amministrativa valida o riferita a una data.

```text
territory_version_id
territory_id
reference_date
valid_from
valid_to
official_code
name
parent_territory_version_id
geometry_version_id
```

### Source

Editore e origine istituzionale.

```text
source_id
publisher
landing_url
license_default
methodology_url
```

### Dataset

Contratto/versione di uno specifico dataset.

```text
dataset_id
source_id
dataset_version
geographical_granularity
temporal_granularity
contract_version
```

### Metric

Definizione semantica di una misura.

```text
metric_id
label
data_type
canonical_unit
semantic_direction
ranking_allowed
trend_allowed
```

### Observation

Valore ufficiale normalizzato.

Chiave logica:

```text
dataset
metric
territory_version
period
source_dimensions (quando presenti nella fonte)
```

Deve mantenere provenance verso l'artefatto raw.

`source_dimensions_json` conserva dimensioni ufficiali necessarie a
distinguere osservazioni altrimenti omonime, ad esempio attività CORINAIR SNAP
nelle emissioni. Non contiene dimensioni inventate dal progetto.

`value_state`, se presente, distingue `observed`, `unavailable`, `suppressed`
e `not_applicable`. Per un valore indisponibile `value_decimal` resta `null`:
non viene convertito in zero.

### DerivedMetric

Risultato calcolato da Stato d'Italia.

```text
derived_metric_id
derived_type
algorithm_version
input_observations
period/window
value
unit
coverage
quality_status
```

### TerritoryProfileInsight

Delivery derivata, rigenerabile, per rendere leggibile il profilo di un singolo
territorio senza confondere fonti o scale.

```text
territory_id
domain
latest observation (period, value, unit)
published series[]
comparison (algorithm_version, status, delta, percent)
source and scale
```

Un insight non è un'osservazione ufficiale: richiama una sola metrica e le sue
dimensioni di fonte. `unavailable` dichiara esplicitamente una scala non
pubblicata oppure l'assenza dalla copertura consegnata; non equivale a zero.

### Release

Insieme immutabile e coerente di oggetti pubblicati.

```text
release_id
created_at
objects[]
datasets[]
schema_versions
```

### IngestionRun

Audit di un'esecuzione.

```text
run_id
source/dataset
started_at
completed_at
source_metadata
records_read
records_accepted
records_rejected
status
error
```

### SourceState

Snapshot immutable, incluso nella release come `metadata/source-state.json`.

```text
schemaVersion
sources[]: source_id, asset_path, resolved_url, etag, last_modified,
           sha256, bytes, dataset_version, period, checked_at
```

Il prossimo run legge questo snapshot dalla release attiva; `manifest.json`
resta l'unico puntatore mutabile. Metriche operative distinguono byte logici
referenziati dalla release e nuovo storage caricato nell'object store.

Ogni run scoped sostituisce esattamente le entry delle sole famiglie sorgente
interessate. Famiglie invariate dello stesso scope e famiglie dello scope opposto
restano nello snapshot trusted della release attiva.

Per gli artifact, ownership è esplicita e distinta in `data`, `geospatial` e
`shared`; la famiglia di elaborazione descrive inoltre quali output devono essere
sostituiti insieme. Un run scoped conserva per riferimento content-addressed
ogni famiglia non interessata, anche nello stesso scope o shared. Una famiglia
interessata viene ridefinita soltanto dagli output dichiarati, quindi artifact
rimossi non sopravvivono. Gli shared derivati, come `territory-insights`, seguono
gli input semantici reali. `scope=all` ricostruisce source state e membership
soltanto dagli output correnti, senza carry-forward implicito.

Il dominio Foreste è interamente `geospatial`: source state e raw INFC,
cataloghi/raw Copernicus, canonical INFC e zonali, PMTiles e delivery Foreste
avanzano nello stesso scope. L'ownership è policy della pipeline e non entra
nell'identità content-addressed della sorgente.

Le geometrie delivery sono dipendenze versionate per dominio e reference year.
La release risolve ogni logical path verso un object SHA immutabile; indici e
mappe dichiarano livello e data territoriale compatibili. INFC usa la geometria
regionale 2015, Copernicus le geometrie 2023, Suolo e Acqua il 2025, Dissesto il
2024 ed Emissioni il 2019/2023. Un aggiornamento ISTAT non invalida geometrie di
anni non interessati.

## Relazioni essenziali

```text
Source
  └─ Dataset
       └─ Observation ── TerritoryVersion ── Territory
               │
               └─ raw provenance

Observation(s)
  └─ DerivedMetric

Release
  └─ raw/canonical/delivery/provenance objects
```

## Regole trasversali

- `official observation != derived metric`.
- `territory_id != territory_version_id`.
- Un valore storico non eredita automaticamente la geometria corrente.
- Missing, suppressed, unavailable, not-applicable e zero sono stati distinti.
- Delivery è derivato e rigenerabile; canonical è la base analitica.
- Ogni schema pubblico/di delivery espone `schemaVersion`.
