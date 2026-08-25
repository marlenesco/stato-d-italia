# ADR 0003: canonical Parquet e separazione delle metriche derivate

**Stato:** accepted

## Contesto

Il progetto deve conservare più informazione di quella necessaria alla UI corrente,
ma deve anche distinguere in modo inequivocabile ciò che proviene da una fonte
ufficiale da ciò che viene calcolato da Stato d'Italia.

## Decisione

I dataset canonical tabellari sono Apache Parquet.

Le osservazioni ufficiali normalizzate e le metriche derivate sono dataset
separati. Non condividono la stessa tabella logica.

Ogni osservazione canonical deve poter risalire almeno a:

- dataset/versione;
- raw SHA-256;
- row locator o equivalente;
- metric ID;
- territory/version;
- periodo;
- valore e unità;
- stato ufficiale/qualità;
- metodologia;
- data di ingestione.

Ogni metrica derivata deve registrare almeno:

- `derived_metric_id`;
- tipo di derivazione;
- versione dell'algoritmo;
- osservazioni di input o riferimento riproducibile agli input;
- finestra temporale;
- coverage/quality status;
- valore e unità.

## Metric dictionary

`config/metrics/` è la fonte di verità per la semantica delle metriche e deve
dichiarare, quando applicabile:

- tipo dati;
- unità canonica;
- direzione semantica;
- precisione;
- valori ammessi;
- compatibilità con trend/ranking/percentile;
- regole per missing/suppressed/not-applicable.

`0`, `null`, valore soppresso, dato assente e non applicabile non sono equivalenti.

## Delivery

Gli asset delivery sono una proiezione usa-e-getta del canonical:

- ottimizzati per CDN/browser;
- rigenerabili;
- non sono la fonte di verità;
- possono cambiare schema tramite una `schemaVersion` esplicita.

## Conseguenze

Il canonical può essere rielaborato con nuovi algoritmi senza riscaricare la fonte,
mentre ogni risultato derivato rimane distinguibile e riproducibile.

## Alternative scartate

- **JSON come formato canonical principale:** meno efficiente e meno adatto ad
  analisi colonnari e dataset estesi.
- **Official + derived nella stessa tabella:** aumenta il rischio che un calcolo
  del progetto venga presentato come dato ufficiale.
