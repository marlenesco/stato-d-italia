# ADR 0006: contratti delle fonti e validazione fail-closed

**Stato:** accepted

## Contesto

Le fonti esterne possono cambiare workbook, colonne, sheet, unità, codici,
granularità o convenzioni senza mantenere un'API versionata. Accettare
silenziosamente un nuovo formato rischia di pubblicare dati formalmente validi ma
semanticamente errati.

## Decisione

Ogni adapter di ingestione ha un **source contract** esplicito e versionato.

Il contratto deve descrivere almeno, quando applicabile:

- file/formati attesi;
- sheet o resource name;
- colonne richieste e opzionali;
- tipi e unità;
- chiavi territoriali;
- granularità geografica;
- granularità temporale;
- anni/periodi attesi o regole per validarli;
- valori null/soppressi/speciali;
- invarianti minimi di contenuto;
- regole di deduplicazione.

## Fail-closed

Una modifica non riconosciuta al contratto deve:

1. interrompere l'ingestione interessata;
2. non aggiornare `manifest.json`;
3. produrre diagnostica leggibile;
4. conservare, quando sicuro e utile, metadata dell'acquisizione fallita;
5. richiedere una modifica esplicita del contract/schema prima della pubblicazione.

Non sono ammessi fallback silenziosi basati su posizione di colonna, fuzzy matching
o conversioni di unità non dichiarate.

## Validazione semantica

Oltre allo schema, gli adapter devono verificare invarianti ragionevoli, ad esempio:

- conteggio territori entro un range atteso;
- unicità delle chiavi;
- unità previste;
- periodi non regressivi;
- codici territoriali risolvibili;
- valori impossibili o fuori dominio;
- copertura minima quando definita dalla fonte.

Le soglie devono essere documentate e testate; non devono essere inventate per
“far passare” una release.

## Evoluzione

Un cambiamento reale della fonte richiede:

- nuova versione del source contract;
- fixture/test aggiornati;
- eventuale migrazione canonical esplicita;
- nota nella release se cambia l'interpretazione dei dati.

## Conseguenze

La pipeline preferisce un aggiornamento mancato a un aggiornamento errato. Questo è
un requisito intenzionale del progetto civico.
