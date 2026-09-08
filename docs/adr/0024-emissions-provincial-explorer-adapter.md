# ADR 0024: adapter Emissioni per combinazioni provinciali inquinante e SNAP

**Stato:** accepted

## Contesto

Nella disaggregazione provinciale ISPRA lo stesso `metricId` identifica un
inquinante, ma ogni mappa contiene più attività CORINAIR SNAP distinte. Il solo
`metricId` non identifica quindi la combinazione navigata. Le serie nazionali
GHG e NFR sono invece dataset annuali multidimensionali e non mappe
territoriali.

## Decisione

La vista provinciale usa un adapter puro che seleziona una sola combinazione
`pollutant + SNAP`, costruisce esclusivamente le sue `MapOption` e associa ogni
logical path alla geometria provinciale dello stesso periodo. L'adapter delega
poi selezione e capability effettive al resolver generico di ADR 0022.

Il catalogo della release determina combinazioni e periodi disponibili. Una
mappa priva della geometria esatta non è pubblicata e non usa fallback a una
geometria più recente. La disponibilità di almeno due periodi autorizza timeline
e serie di valori, ma non un confronto: per Emissioni provinciali comparison,
ranking e percentile restano semanticamente non supportati.

La vista nazionale conserva `NationalExplorer` e `SeriesChart` specializzati e
non passa dal resolver territoriale.

## Conseguenze

- Nessuna attività SNAP viene aggregata o contaminata con un'altra.
- Serie nazionale e disaggregazione provinciale restano dataset distinti.
- I valori 2019 e 2023 possono essere mostrati come serie senza delta, direzione
  o percentuale.
- I profili richiedono identità provinciali correnti pubblicate nella release.
