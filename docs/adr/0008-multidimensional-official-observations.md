# ADR 0008: dimensioni ufficiali delle osservazioni

**Stato:** accepted

## Contesto

Alcune fonti ufficiali, come la disaggregazione ISPRA delle emissioni,
pubblicano una misura per territorio, periodo, inquinante e attività CORINAIR
SNAP. Trattare due attività come la stessa osservazione distruggerebbe il
significato della fonte. Sommarle senza una regola dichiarata trasformerebbe un
dato ufficiale in una metrica derivata non dichiarata.

## Decisione

La chiave logica di una `Observation` comprende anche le dimensioni ufficiali
quando il dataset le espone:

```text
dataset
metric
territory_version
period
source_dimensions
```

`source_dimensions_json` conserva il sottoinsieme minimo, stabile e
serializzato delle dimensioni pubblicate dalla fonte. Per le emissioni include
codice e descrizione SNAP. Non è un campo per dimensioni inventate dal progetto.

Una somma tra dimensioni, ad esempio totale CO2 su tutte le attività SNAP,
è sempre una `DerivedMetric`: deve dichiarare algoritmo, copertura degli input
e gestione esplicita di celle mancanti.

## Conseguenze

- La UI può presentare dati ufficiali per inquinante e attività senza
  attribuire a ISPRA un totale non pubblicato come tale.
- Un dominio può aggiungere una metrica aggregata solo dopo una regola
  riproducibile e una verifica semantica delle celle vuote.
- Il canonical conserva una provenienza più precisa senza cambiare il
  significato delle osservazioni esistenti prive di dimensioni.
