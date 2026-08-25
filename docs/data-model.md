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
```

Deve mantenere provenance verso l'artefatto raw.

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
