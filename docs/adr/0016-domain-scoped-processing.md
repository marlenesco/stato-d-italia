# ADR 0016: processing scoped per dominio e attivazione globale seriale

**Stato:** accepted

## Contesto

Gli scope `data` e `geospatial` definiscono ownership di release, ma sono più
ampi di un dominio. Rigenerare Foreste non deve acquisire o ricalcolare Suolo,
Acqua, Emissioni o Dissesto. Al tempo stesso `territory-insights` è un output
shared: non appartiene esclusivamente al dominio che ne aggiorna un input.

## Decisione

La pipeline dichiara un registry di domini con scope di ownership, famiglie
sorgente, downstream shared e processor. D1.2 abilita `forests`:

```text
INFC + Copernicus
  -> canonical Foreste
  -> delivery Foreste
  -> territory-insights (shared)
```

I comandi `check-sources --domain forests` e `run --domain forests` limitano
preflight, hydration, acquisizione e ricalcolo alle famiglie `infc` e
`copernicus`. Le canonical degli altri domini richieste da
`territory-insights` sono idratate dalla release attiva e verificate per SHA-256;
non ne avviene una nuova ingestione. `--force` rivalida solo le famiglie del
dominio richiesto.

Il registry include già i contratti di estensione per `soil`, `water`,
`emissions` e `dissesto`, ma non abilita un processor finché non esiste il loro
grafo completo e testato. Non vengono introdotti manifest per dominio:
`manifest.json` resta l'unico puntatore globale.

Elaborazione di dominio e attivazione sono concetti separati: il processor
produce artifact dichiarati e `_publish_scoped` unisce source state, carry-forward
e controllo di coerenza prima dell'unica attivazione globale. L'attivazione R2
è rifiutata fuori da `main`; future esecuzioni parallele potranno preparare
artifact indipendenti, ma dovranno serializzare l'ultima composizione e update
atomico del manifest globale.

## Conseguenze

- Foreste può essere rigenerato senza lavorare gli altri quattro domini.
- Un cambiamento Foreste rigenera `territory-insights` dai nuovi input Foreste
  e dalle canonical attive degli altri domini.
- Una run senza piano continua a essere fail-closed rispetto alle dipendenze
  mancanti nella release attiva; un piano di un altro dominio è rifiutato.
- Il registry evita cinque copie dell'orchestrazione, ma non implementa ancora
  scheduling, locking dei risultati intermedi o merge parallelo multi-dominio.
