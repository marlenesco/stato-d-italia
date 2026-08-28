# ADR 0011: selezione territoriale persistente negli esploratori

**Stato:** accepted

## Contesto

Un cambio di periodo ricarica i valori della mappa. La selezione non deve
sparire soltanto perché il nuovo dataset non pubblica un valore per quel
territorio: assenza del dato e assenza della scelta sono stati diversi.

## Decisione

Gli esploratori cartografici usano il parametro condivisibile
`territory=<territory_id>` insieme ai parametri già presenti di metrica,
livello e periodo. La selezione viene aggiornata con `replace`, senza reload o
scroll, e resta attiva durante cambio di periodo nella stessa scala geografica.

Se il valore non è pubblicato nel periodo selezionato, mappa e pannello
mantengono il territorio e dichiarano indisponibilità. Non usano zero, stime o
conversioni. Un cambio di livello rimuove la selezione: nessuna conversione
automatica fra comune, provincia e regione è ammessa senza gerarchia storica
ufficiale valida per quel periodo.

Il contratto vale per Suolo, Acqua, Foreste, Dissesto ed Emissioni provinciali.
Non si applica alle serie nazionali o alle pagine profilo.

## Conseguenze

- URL di una mappa selezionata è ricaricabile e condivisibile.
- Serie e pannello distinguono "dato non pubblicato" da "nessun territorio
  selezionato".
- La stessa istanza MapLibre aggiorna feature-state e valori quando geometria
  non cambia.
