# ADR 0023: adapter Water per le famiglie metriche dell'explorer

**Stato:** accepted

## Contesto

BIGBANG 10.0 pubblica le stime regionali come metriche modellistiche ufficiali,
mentre le mappe provinciali sono metriche derivate da Stato d'Italia tramite
media zonale pesata per area sui raster ISPRA. Le due rappresentazioni della
stessa misura concettuale usano quindi identificativi distinti, ad esempio
`water_total_precipitation_mm` e
`water_total_precipitation_mm_zonal_mean`.

## Decisione

L'explorer Acqua usa un adapter puro che risolve una famiglia di navigazione
nel metric ID esatto del livello selezionato, poi delega selezione e capability
effettive al modello generico definito da ADR 0022. La famiglia serve soltanto
a mantenere la navigazione Regioni/Province: non rende equivalenti le metriche,
le metodologie o le geometrie.

La disponibilità di famiglie, livelli, periodi e geometrie resta determinata
dalla release. `mapGeometry` Water è sempre autoritativo: l'assenza del mapping
esatto rende la mappa non pubblicata. Le serie possono essere mostrate se
pubblicate; i confronti restano fail-closed finché la delivery non fornisce
evidenza verificabile di metrica, metodologia e geometria comparabili.

## Conseguenze

- Regioni: `official_model`, con testo ISPRA BIGBANG 10.0.
- Province: `derived_metric`, con testo esplicito Stato d'Italia e metodo.
- Nessun ranking o percentile viene introdotto per Acqua.
- Il cambio livello conserva la famiglia, ma azzera il territorio selezionato:
  non esiste crosswalk implicito tra Regione e Provincia.
