# ADR 0021: semantica dei campi Province/UTS ISTAT 2021

**Stato:** accepted

**Sostituisce parzialmente:** ADR 0020, limitatamente alla versione del
contract canonical e alla risoluzione del codice Provincia/UTS.

## Contesto

Il contract v2 introdotto dall'ADR 0020 chiudeva correttamente la gerarchia,
ma trattava `COD_UTS`, `COD_PROV`, `COD_CM` e `COD_PCM` come candidati
intercambiabili. Nel layer ufficiale `Limiti2021_g.zip` questa equivalenza non
esiste: per Milano, per esempio, `COD_PROV=015`, `COD_CM=215` e
`COD_UTS=215`. La stessa distinzione vale per le altre Città metropolitane.

## Decisione

Per lo schema 2021, `COD_UTS` è obbligatorio e costituisce l'unico codice
canonical del layer Province/UTS e l'unico parent canonical dei Comuni. Se il
codice è assente o non identifica una Province/UTS canonical, l'ingest fallisce;
non è permesso il fallback a `COD_PROV`.

I quattro campi sorgente sono mantenuti separati come provenance canonical.
Per gli snapshot diversi dal 2021 resta la priorità legacy già verificata:
`COD_PROV`, poi `COD_UTS`, poi `COD_PCM`. Non si applica retroattivamente la
regola 2021 a schemi diversi.

Il contract canonical 2021 diventa versione 3. I Parquet v2, pur con data
`2021-12-31` e popolazione completa, non sono riusabili perché possono avere
una semantica di identità provinciale diversa.

## Conseguenze

- Il 2021 mantiene `territory_version_id` con suffisso `@2021-12-31`.
- La chiusura Comune → Provincia/UTS → Regione, i 7.904 Comuni e il rebuild
  validation-only dall'archivio ISTAT ufficiale restano obbligatori.
- Le geometrie canonical e le statistiche zonali Forest 2021 vengono
  rigenerate nella candidate validation; raster CDSE, cache e request rimangono
  semanticamente riusabili.
- Non sono introdotti crosswalk né correzioni specifiche per città.
