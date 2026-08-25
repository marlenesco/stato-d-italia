# ADR 0007: analytics e confronti territoriali deterministici

**Stato:** accepted

## Contesto

Le osservazioni canonical ISPRA sul consumo di suolo includono flussi su periodi
di durata diversa (`2006–2012`, `2012–2015`, poi annuali) e soli valori di stock
nel 2024. Confrontare questi valori come se fossero una serie annuale omogenea
produrrebbe variazioni e trend ingannevoli.

## Decisione

Analytics è un artefatto derivato separato dal canonical. Ogni riga dichiara
`algorithm_version = soil-analytics-v1`, metriche/input, finestra, coverage e
motivo dell'eventuale indisponibilità. Non modifica né sostituisce mai una
`official observation`.

### Input eleggibili

- valore numerico finito, stesso `metric_id`, `territory_id` e
  `territory_version_id`;
- per variazioni e trend: soli flussi annuali consecutivi, ossia periodo
  `Y-01-01` → `Y-12-31` (nel dataset corrente: 2016–2024 come anno finale);
- stock/punti nel tempo possono esporre solo latest value finché la fonte non
  fornisce punti temporali comparabili;
- cambio di `territory_version_id` nella finestra = `series_break`: derivazione
  non disponibile. Nessun crosswalk viene stimato.

### Metriche derivate

| Campo | Regola |
| --- | --- |
| `latest_value` | Ultima osservazione ufficiale per periodo finale; non derivata. |
| `change_previous` | Ultimo flusso annuale meno flusso annuale precedente, solo se gli anni finali sono consecutivi. |
| `change_5y` | Ultimo flusso annuale meno flusso con anno finale esattamente cinque anni precedente. Nessun periodo pluriennale viene sostituito. |
| `change_10y` | Stessa regola a dieci anni. Assente nel dataset soil corrente perché manca flusso annuale 2014. |
| `trend` | Regressione lineare OLS `value ~ end_year` sui flussi annuali della finestra finale massima di dieci anni. Richiede almeno 7 osservazioni, copertura almeno 80% dello span osservato e nessun gap superiore a un anno. Espone slope, intercept, R², numero osservazioni e direzione. |
| `percentile` | CDF empirica inclusiva `100 * count(value <= value_territory) / N`, su valori validi dello stesso livello, metrica e periodo. Richiede almeno 10 territori. |
| `ranking` | Rank competition (`method=min`) decrescente per metriche `greater_pressure`; pari merito condividono rango. Richiede almeno 2 territori. |

La direzione del trend è `flat` quando `abs(slope) <= 1%` della mediana dei valori
assoluti della finestra per anno; altrimenti `increasing` o `decreasing`. È una
classificazione derivata, non giudizio ufficiale.

### Confronti

Confronti gerarchici usano osservazioni ufficiali della stessa metrica e dello
stesso periodo: Comune → Provincia → Regione → Italia. Un confronto non viene
prodotto se manca uno dei valori o differisce `territory_version_id` rispetto al
riferimento geografico della fonte.

Ranking/percentili confrontano solo pari livello. Per i Comuni si espongono:

- nazionale: tutti i Comuni;
- regionale: Comuni della stessa Regione;
- provinciale: Comuni della stessa Provincia.

Per Province e Regioni, gruppi inferiori a 10 non espongono percentile. Italia
non ha peer group e quindi non espone ranking/percentile.

## Conseguenze

- Nessuna falsa continuità tra periodi ISPRA pluriennali e annuali.
- `change_10y` può essere esplicitamente `unavailable`; non è zero.
- Delivery/UI deve mostrare separatamente valore ufficiale, risultato derivato,
  periodo, coverage, versione algoritmo e motivazione di indisponibilità.
