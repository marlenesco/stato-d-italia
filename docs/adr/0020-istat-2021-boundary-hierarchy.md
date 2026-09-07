# ADR 0020: data e gerarchia dei confini ISTAT 2021

**Stato:** accepted

## Contesto

Il dataset ufficiale `Limiti2021_g.zip` è riferito al 31 dicembre 2021, non al
primo gennaio. Il parser precedente costruiva inoltre il codice provinciale con
precedenza `COD_PROV`, mentre i Comuni 2021 dichiarano il genitore in
`COD_UTS` (il layer Province/UTS espone `COD_UTS`, `COD_PROV` e `COD_CM`, non
`COD_PCM`). Per le 14 Città metropolitane i due codici differiscono: la selezione
Forest eliminava quindi 1.268 Comuni orfani senza segnalarlo.

## Decisione

`territory_reference_date(year)` è l'unica risoluzione della data ISTAT: per il
2021 restituisce `2021-12-31`, per gli altri snapshot il primo gennaio.

Il parser conserva inizialmente i candidati di codice ufficiali. Costruisce poi
la popolazione Province/UTS e risolve ogni genitore comunale soltanto contro i
codici provinciali realmente presenti nello stesso snapshot. Zero candidati o
più candidati distinti sono errori; non sono ammessi crosswalk o correzioni per
singole Città metropolitane. La chiusura Comune → Provincia/UTS → Regione è un
contratto canonical esplicito.

Il canonical 2021 usa il contract version 2 e richiede 7.904 Comuni, 20 Regioni
e zero orfani. Un parquet 2021 prodotto con il contract precedente non è
riusabile: una validation Forest locale lo rigenera dal ZIP ISTAT ufficiale
prima di ricalcolare le statistiche zonali.

## Conseguenze

- `territory_version_id` 2021 termina con `@2021-12-31`; l'anno del logical
  geometry path resta `2021`.
- TCD 2021, FTY 2021 e TCPC 2018–2021 vengono aggregati sulle nuove geometrie
  canonical 2021; i raster CDSE e le rispettive request restano invariati e
  riusabili.
- Nessun valore viene trasferito ai confini 2023 e nessuna serie riceve un
  crosswalk implicito.
