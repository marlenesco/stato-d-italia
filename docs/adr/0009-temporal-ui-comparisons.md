# ADR 0009: confronti temporali nella UI

**Stato:** accepted

## Contesto

La timeline rende leggibili osservazioni ufficiali successive. Un indicatore
visivo di aumento o diminuzione rispetto al periodo precedente richiede però
un calcolo del progetto: non può essere presentato come un valore della fonte.

## Decisione

La UI può mostrare un gauge di confronto esclusivamente quando sono disponibili
due osservazioni numeriche della stessa metrica, territorio, unità e durata del
periodo. Il confronto usa:

```text
delta = valore selezionato - valore precedente
percentuale = delta / abs(valore precedente) * 100
```

La UI dichiara la versione `temporal-comparison-ui-v1`, i due periodi input e
la formula. Non interpola periodi mancanti e non produce il gauge se:

- manca uno dei due valori;
- unità o durata dei periodi differiscono;
- il valore precedente è zero.

Il gauge è un confronto visuale effimero, non una `DerivedMetric` pubblicata:
non viene scritto nel canonical né nei delivery artifact. Una metrica derivata
pubblicabile, una classificazione di trend o un confronto fra confini storici
richiede un artefatto analytics separato e un nuovo ADR.

## Conseguenze

- Il lettore vede aumento/diminuzione senza scambiare il risultato per dato
  ufficiale.
- Le serie con snapshot singoli o periodi non omogenei restano senza gauge.
- Le frecce della timeline navigano solo gli asset di periodo realmente
  pubblicati.
