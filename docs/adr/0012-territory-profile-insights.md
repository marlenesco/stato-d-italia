# ADR 0012: profilo territoriale e insight derivati

**Stato:** accepted

## Contesto

Un territorio può avere osservazioni pubblicate per domini e scale diverse. Un profilo dominato dal solo Suolo nasconde questa lettura trasversale; una somma tra domini o un giudizio automatico non dichiarato la renderebbe però fuorviante.

## Decisione

La delivery pubblica `territory-insights` versionata con algoritmo `territory-profile-insights-v1`. Ogni profilo conserva sezioni indipendenti per dominio: ultimo valore, serie realmente pubblicata, fonte, periodo, scala e link all'esploratore già filtrato sul territorio.

Un confronto automatico usa solo gli ultimi due valori della stessa metrica, territorio, unità e serie. Espone input, delta, percentuale e stato. `improving`/`worsening` è ammesso solo per metriche con direzione dichiarata `less_is_better`; per metriche `context_only` espone solo `changed`/`stable`. Uno snapshot o una serie non comparabile espone `unavailable`, mai una freccia, zero o stima.

Le emissioni restano provinciali e conservano inquinante e attività SNAP. La sezione profilo non somma attività: presenta una sola combinazione esplicitamente configurata. Acqua è regionale; Dissesto resta snapshot finché la fonte non pubblica serie omogenea.

## Conseguenze

- Profilo territoriale è una vista globale senza inventare copertura.
- Ogni sezione dichiara assenza, copertura parziale o scala non pubblicata.
- Insight è una metrica derivata rigenerabile, con versione algoritmo e separata dall'osservazione ufficiale.
