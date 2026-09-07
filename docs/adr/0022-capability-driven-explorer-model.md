# ADR 0022: modello capability-driven per gli explorer

**Stato:** accepted

## Contesto

Il registry dei domini dichiara ciò che è semanticamente lecito per livello
territoriale, temporalità, confronti, ranking e percentile. Una release può però
pubblicare soltanto una parte di tali possibilità. Trattare la presenza di un
asset come autorizzazione semantica produce timeline, ranking o confronti
fuorvianti; trattare il registry come disponibilità inventa invece asset assenti.

## Decisione

Gli explorer condivisi risolvono una capability effettiva come:

```text
capability semantica del dominio
        ∩
asset effettivamente pubblicati nella release
        =
capability effettiva dell'explorer
```

Il resolver puro usa soltanto metadata già caricata dal server: mappe, periodi,
geometrie compatibili, ranking e identità territoriali correnti. Restituisce
selezione valida e stati espliciti `available`, `not_published` e
`not_supported`, con reason code stabile. Una geometria `mapGeometry` dichiarata
è autoritativa: una mappa storica senza mapping non può ricadere sulla geometria
generica del livello.

`not_supported` significa che il dominio vieta semanticamente la feature;
`not_published` significa che sarebbe consentita ma non è dichiarata nella
release. I renderer decidono il testo e il layout, ma ricevono la capability
risolta: non deducono più timeline, ranking o confronto dalla sola presenza di
una URL.

Un confronto con policy `same_metric_unit_method_geometry` resta fail-closed se
l'indice non fornisce evidenza sufficiente per metodologia e geometria. I check
runtime su unità, durata del periodo e geometria restano necessari e non sono
sostituiti dal model.

## Conseguenze

- Snapshot singoli e singoli change period non mostrano timeline o serie fittizie.
- Ranking e percentile richiedono sia policy del dominio sia asset esatto della
  combinazione metrica/periodo/livello.
- Il cambio di livello azzera il territorio selezionato; non esiste crosswalk
  implicito tra Comune, Provincia e Regione.
- `ThemeWorkspace`, `DissestoWorkspace`, `SoilMap` e `TerritoryMapSeries`
  condividono il model senza diventare un unico componente universale.
- Gli explorer Acqua ed Emissioni mantengono in questa fase i loro controller
  specializzati; il modello non modifica canonical, pipeline o release R2.
