# ADR 0017: copertura nazionale e snapshot temporali delle elaborazioni Foreste

**Stato:** accepted

## Contesto

La prima slice di sviluppo Copernicus riguardava quattro Regioni. Non è una
copertura pubblicabile come nazionale. Inoltre, i prodotti HRL sono snapshot
discreti: associare un raster al solo nome della metrica o riutilizzare un
payload identico per periodi diversi renderebbe non verificabile la serie.

## Decisione

La policy predefinita per Foreste è `national`. La slice di sviluppo esiste
solo quando `FOREST_COVERAGE_MODE=development_slice` è dichiarata
esplicitamente e non può generare il delivery.

Ogni asset/periodo viene prima risolto nel catalogo CDSE per tag del prodotto e
timestamp `ContentDate/Start` della data di riferimento configurata. Il
manifest delle slice e le osservazioni derivate conservano la signature dello
snapshot. Assenza, ambiguità o timestamp inatteso sono errori bloccanti.

La verifica pubblica del catalogo identifica Tree Cover Density come `TCDCL` a
10 m e Forest Type a 100 m; la griglia Process a 100 m è una scelta di
elaborazione separata e non viene presentata come risoluzione nativa TCD.

La canonical raster produce un sidecar di copertura: popolazione ISTAT attesa,
territori con valore numerico e territori con NoData raster valido. I tre
insiemi devono essere disgiunti e ricomporre esattamente la popolazione attesa.
Il delivery richiede quel sidecar in modalità `national`; la copertura e il
riferimento geometrico sono esposti nelle mappe.

Per ogni metrica, livello e periodo vengono registrati conteggio, min/max,
media, quantili, hash stabile del payload e confronto con lo snapshot
precedente. Due payload territoriali consecutivi esattamente identici sono
rifiutati. Le serie UI confrontano solo geometrie territoriali compatibili e
usano una scala colore comune ai periodi della medesima metrica/livello.

INFC resta una serie ufficiale distinta per Italia/Regioni: non si derivano
Province o Comuni e non si effettua alcun crosswalk con HRL.

## Conseguenze

- La ripresa da cache richiede manifest di slice e sidecar coerenti con lo
  snapshot catalogato; cambiare snapshot invalida la cache.
- I dati DLT e CORINE restano contratti separati: questa decisione non ne
  estende l'acquisizione o la semantica.
- L'attivazione continua a essere globale e seriale come definito da ADR 0016;
  gli artifact Foreste dichiarati possono però essere preparati nel processor
  di dominio senza ricalcolare gli altri domini.
