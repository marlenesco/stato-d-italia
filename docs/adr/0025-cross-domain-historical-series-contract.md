# ADR 0025: contratto cross-domain per le serie storiche

**Stato:** accepted

## Contesto

L'[audit H1A](../historical-coverage-audit.md) mostra che presenza di dati,
pubblicazione e capacità di confronto sono già concetti distinti. La
[ricerca H1B](../historical-source-research.md) aggiunge periodi ufficiali ma
documenta anche geometrie mancanti, geografie armonizzate, cambi di metodo,
revisioni complete e snapshot irregolari.

Una regola unica come `historical = true` non può rappresentare questi casi.
Produrrebbe mappe su confini sbagliati, linee che suggeriscono interpolazioni o
delta tra ricostruzioni metodologiche diverse.

## Decisione

Stato d'Italia espone la massima profondità storica difendibile, ma ogni
periodo conserva separatamente:

- periodo di osservazione, release e versione della fonte e release del
  progetto;
- modalità, data, fonte e versione della geografia territoriale;
- versione di metrica, unità, metodologia, classificazione, durata e
  risoluzione spaziale;
- eventuali rotture di serie, con dimensioni e motivazione;
- eleggibilità indipendente per display, mappa, serie, delta, trend, ranking e
  confronto territoriale.

Il contratto dettagliato e la matrice per famiglia sono definiti in
[`docs/historical-series-policy.md`](../historical-series-policy.md).

### Modalità territoriali

Le modalità minime sono:

- `contemporaneous_exact`: osservazione amministrativa collegata alla versione
  ufficiale valida alla data di riferimento della fonte;
- `source_harmonized`: valori storici pubblicati esplicitamente dall'editore su
  una geografia comune successiva;
- `project_aggregated_exact`: valore derivato da Stato d'Italia aggregando una
  fonte ufficiale non amministrativa su geometria ufficiale dello stesso
  periodo;
- `non_administrative_grid`: valore nativo su griglia ufficiale;
- `official_crosswalk`: valore collegato o armonizzato tramite una regola
  ufficiale esplicita e versionata;
- `project_harmonized`: risultato derivato mediante crosswalk del progetto,
  ammesso solo da un ADR specifico e mai presentato come osservazione ufficiale;
- `unknown`: geografia non provata; blocca attribuzione e mappa amministrativa.

Una geometria censuaria vicina, la geometria corrente o la coincidenza di nome
o codice non sono fallback. Un valore storico non eredita mai implicitamente
il confine corrente.

### Exact-year e date censuarie

Una geometria amministrativa è eleggibile quando la data ufficiale coincide
con il riferimento richiesto dal dataset, oppure quando una fonte ufficiale
documenta un intervallo di validità che comprende l'intero uso previsto.

Gli snapshot censuari 1991 e 2001 non rappresentano le emissioni 1990, 1995 o
2000. Queste mappe restano bloccate. I confini 2005, 2010 e 2015 sono candidati
exact-year, ma le righe provinciali ISPRA devono superare un audit identitario
uno-a-uno prima dell'uso.

Lo snapshot censuario del 9 ottobre 2011 è esatto soltanto per osservazioni che
dichiarano quella data. Non autorizza l'aggregazione provinciale dell'intero
anno BIGBANG 2011 senza un intervallo ufficiale o una regola della fonte. Il 31
dicembre 2021 resta l'eccezione annuale ISTAT già disciplinata dagli ADR 0020 e
0021.

### Rotture e capacità

Le rotture sono multidimensionali: definizione metrica, unità,
metodo/versione, classificazione, geografia, revisione/reprocessing, durata del
periodo e risoluzione spaziale sono valutate indipendentemente.

Una rottura non impedisce il display isolato di un periodo valido. Impedisce
invece delta e trend attraverso la rottura; una vista storica può mantenere i
punti in segmenti distinti, con annotazione e senza linea di continuità.
Ranking e confronto territoriale sono valutati sul singolo periodo e sulla sua
popolazione omogenea, non ereditati dalla presenza di una serie.

L'ordine dei gate è:

```text
policy semantica storica (ADR 0025)
        ∩
capability e asset pubblicati (ADR 0022)
        ∩
controlli runtime/algoritmici (ADR 0009 o ADR specifico)
        =
capability effettiva
```

ADR 0009 disciplina quindi il calcolo effimero solo dopo l'autorizzazione
semantica e l'evidenza richiesta da ADR 0025 e ADR 0022. ADR 0007 resta la
metodologia specifica del Suolo e non diventa una regola universale di trend.

### Revisioni e reprocessing

`reference_period`, `source_release`, `source_version` e `project_release` sono
identità diverse. Quando una fonte ripubblica l'intera storia, una release del
progetto usa una sola ricostruzione coerente; non mescola anni provenienti da
submission diverse.

Le differenze fra due submission per lo stesso periodo sono revisioni della
stima, non cambiamenti ambientali. Restano confrontabili come revisioni solo in
una vista esplicitamente dedicata. Sostituzioni di byte o geometrie generano
nuova provenance, nuova versione e ricostruzione dei derivati dipendenti; non
riscrivono oggetti immutabili già pubblicati.

Una migrazione di accesso senza evidenza ufficiale di reprocessing, come la
migrazione CLMS a CDSE, non viene classificata come nuova versione
metodologica.

### Serie sparse e prodotti change

I periodi mancanti non sono interpolati. Le serie sparse mostrano punti o
intervalli reali e la durata dichiarata. Una linea è ammessa soltanto fra
periodi adiacenti nella cadenza ufficiale, senza rotture e con semantica
continua documentata; altrimenti resta assente.

Uno status e un change product sono famiglie semantiche distinte. Per CORINE si
usano i change layer ufficiali; non si sottraggono ingenuamente due status. Per
Copernicus non si presume un change 2021–2024 dalla sola presenza degli status
2024.

### Raster e griglie

Una derivazione amministrativa da raster richiede fonte ufficiale, periodo,
CRS e risoluzione noti, geometria ufficiale compatibile, algoritmo versionato,
provenance riproducibile e diagnostica di copertura. L'output è sempre una
metrica derivata.

La griglia EMEP delle emissioni costituisce una famiglia futura separata e
complementare alle province. Il relativo ADR di implementazione è differito:
CRS, convenzione delle coordinate, geometria delle celle e contratto delivery
non sono ancora sufficientemente definiti. H1C non autorizza ingest o mappa.

## Relazione con gli ADR esistenti

- ADR 0002 e ADR 0020 restano invariati: exact-year e identità versionate sono
  confermati.
- ADR 0007 resta specifico alle analytics del Suolo.
- ADR 0009 è chiarito dall'ordine dei gate sopra definito.
- ADR 0015 resta fail-closed; nuovi confini possono ampliare la matrice BIGBANG
  solo dopo acquisizione e validazione, senza fallback censuari.
- ADR 0022 resta il resolver delle capability effettivamente pubblicate.
- ADR 0023 mantiene separate osservazioni BIGBANG ufficiali e derivati
  provinciali.
- ADR 0024 mantiene separati inquinante e SNAP e non abilita confronti o ranking
  provinciali.

Nessuno degli ADR elencati è sostituito.

## Conseguenze

- Esistenza storica e confrontabilità non sono più sinonimi.
- La stessa famiglia può consentire display e serie ma bloccare delta, trend o
  ranking.
- Geografie armonizzate dalla fonte restano visibili ma distinguibili dalla
  geografia contemporanea.
- Le future modifiche agli schemi dovranno rappresentare questi metadati prima
  di ampliare ingest, delivery o UI.
- H1C non modifica source contract, pipeline, dati, frontend o pubblicazione.
