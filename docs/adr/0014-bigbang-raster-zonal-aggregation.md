# ADR 0014: proof of concept di aggregazione zonale raster BIGBANG

**Stato:** accepted

## Contesto

BIGBANG 10.0 pubblica osservazioni modellistiche ufficiali aggregate per Italia e
Regioni e raster annuali su griglia regolare. Il progetto deve verificare se il
raster ufficiale possa sostenere valori sub-regionali senza presentare come dato
ISPRA un'aggregazione prodotta da Stato d'Italia.

Il proof of concept è limitato a precipitazione totale (`TP`), anno 2025,
Regioni e Province. Non modifica il canonical BIGBANG ufficiale, non produce
delivery e non entra nei workflow schedulati.

## Contratto verificato

Fonte ufficiale ISPRA/SINAnet:

- pagina prodotto: `https://groupware.sinanet.isprambiente.it/bigbang-data/library/bigbang100/ascii_grid/total_precipitation/tp_annual_1951-2025`;
- download risolto: `https://groupware.sinanet.isprambiente.it/bigbang-data/library/bigbang100/ascii_grid/total_precipitation/tp_annual_1951-2025/download/en/1/TP_ANNUAL_1951-2025.zip`;
- archivio: `TP_ANNUAL_1951-2025.zip`, 91.421.884 byte, SHA-256
  `af80b158d29190cb57dfae2204bded5dd6c3365e8579dc0c902863418242dbc9`;
- struttura: 75 coppie `.asc`/`.prj`, una per ogni anno 1951-2025;
- raster 2025: `tp_2025_yyc.asc`, 11.809.682 byte, SHA-256
  `52f1bffc413427b9694e883d7c18bd560d843b171b684c366a9c6781273e78d4`;
- formato AAIGrid, CRS equal-area EPSG:3035, 1300 x 1400 celle da 1.000 m;
- estensione `(3900000, 1300000, 5200000, 2700000)` in EPSG:3035;
- NoData `-9999`, unità `mm`.

Il validatore richiede struttura, byte, checksum e header esatti. Una differenza
interrompe il PoC: non sono ammessi fallback su nomi simili o formati inattesi.

## Decisione

### Separazione tra ufficiale e derivato

Le osservazioni Italia/Regioni del workbook restano nel canonical ufficiale con
metric ID `water_total_precipitation_mm`.

Le aggregazioni dal raster sono scritte esclusivamente in:

```text
derived/water/algorithm_version=bigbang-tp-zonal-area-weighted-v1/observations.parquet
```

con metric ID `water_total_precipitation_mm_zonal_mean` e stato
`derived_by_stato_italia`. Ogni record conserva SHA dell'archivio e del raster,
locator interno, versione geometrica, SHA della geometria, versione algoritmo,
area valida, conteggio celle, coverage e quality flags.

### Algoritmo zonale

La versione `bigbang-tp-zonal-area-weighted-v1` usa l'intersezione geometrica
esatta nel CRS equal-area EPSG:3035:

```text
sum(value_cell * valid_intersection_area)
/
sum(valid_intersection_area)
```

Le celle parziali contribuiscono in proporzione all'area realmente intersecata.
NoData non contribuisce né al numeratore né al denominatore. Multipolygon, isole,
coste e intersezioni vuote sono gestiti esplicitamente. Il coverage ratio è il
rapporto tra area valida intersecata e area della geometria territoriale nello
stesso CRS.

Il metodo basato soltanto sul centro del pixel non è quello autorevole del
progetto, anche se viene usato come controllo diagnostico per comprendere le
differenze rispetto alle tabelle ISPRA.

### Dipendenza territoriale

Il PoC usa le geometrie canonical ISTAT con riferimento `2025-01-01`. La
provenance identifica il singolo `territory_version_id` e la relativa geometria.
Un cambio dei confini richiede una nuova derivazione: i risultati non vengono
trasferiti implicitamente a un'altra versione territoriale.

## Gate metodologico dei 100 km2

Una presentazione metodologica ufficiale ISPRA del 2019, di Braca e Mariani, dichiara, tra i
criteri del modello, la possibilità di ritagliare risultati su qualunque ambito
territoriale `> 100 km2`. La stessa presentazione indica griglia di 1 km e scala
temporale minima mensile.

La soglia è quindi interpretata come limite/raccomandazione di applicabilità
metodologica dichiarata, non come limite tecnico del formato raster: il software
può intersecare poligoni più piccoli, ma ISPRA non rivendica in quel documento la
stessa applicabilità sotto soglia.

Esito sulle geometrie ISTAT 2025:

| Livello | Esito |
| --- | --- |
| Regione | 20 su 20 sopra soglia; supportato dal PoC |
| Provincia | 107 su 107 sopra soglia; supportato dal PoC |
| Comune >= 100 km2 | 599 unità; sola fattibilità, nessun dataset prodotto |
| Comune < 100 km2 | 7.297 unità; fuori dall'applicabilità dichiarata |

La copertura completa comunale non è metodologicamente difendibile sulla sola
base della documentazione ufficiale verificata. L'operatore riportato da ISPRA è
strettamente `>`; il conteggio richiesto usa `>= 100 km2`, senza effetto sul
risultato osservato.

## Validazione regionale

Il confronto usa le 20 osservazioni ufficiali `TP` 2025 già presenti nel
canonical regionale, senza calibrazione o tolleranza prefissata.

Differenze assolute in mm:

- minimo: 0,0110;
- mediana: 0,2583;
- media: 0,8099;
- massimo: 7,6306 (Marche).

Differenze relative:

- minimo: 0,0017%;
- mediana: 0,0238%;
- media: 0,0830%;
- massimo: 0,8910% (Marche).

Il coverage regionale minimo è 0,9996848. Il confronto è completo e non mostra
un errore strutturale; consente quindi il calcolo delle Province.

Il [Rapporto ISPRA 339/2021](https://www.isprambiente.gov.it/files2021/pubblicazioni/rapporti/rapporto_ispra_339-21_bigbang_ld.pdf)
descrive aggregazioni ufficiali tramite `Zonal statistics` di ArcGIS su confini
vettoriali scelti dall'Istituto. Il PoC usa invece geometrie
ISTAT 2025 generalizzate e intersezioni area-weighted esatte. Queste differenze
verificabili di geometria e algoritmo sono cause plausibili degli scostamenti;
senza la geometria/mask esatta e i parametri operativi usati per le tabelle ISPRA
non è possibile attribuire con certezza il residuo, in particolare quello delle
Marche. Nessun valore è corretto per forzare la coincidenza.

## Province e diagnostica di coverage

Sono state prodotte 107 osservazioni provinciali derivate. Nessun valore è
mancante. Il coverage ratio minimo è 0,9946962, la mediana 0,9999999 e il massimo
1,0. Le differenze di coverage costiero restano visibili nei campi diagnostici e
non vengono trasformate in zero o occultate.

## Conseguenze e limiti

- Il PoC dimostra la fattibilità tecnica e metodologica per Regioni e Province.
- Non autorizza una pipeline di produzione né una pubblicazione R2.
- Non autorizza metriche diverse da TP o anni diversi dal 2025.
- Non autorizza delivery frontend o `territory-insights`.
- Non autorizza copertura comunale completa.
- Una futura produzione deve definire esplicitamente politica di coverage,
  lifecycle del raster, dipendenze territoriali e criteri di accettazione.

## Riproduzione locale

Con raster e canonical locali verificati:

```sh
uv run python -m stato_italia.bigbang_raster_poc \
  --archive data/raw/ispra-bigbang-10/raster-poc/TP_ANNUAL_1951-2025.zip \
  --canonical-root data/canonical \
  --derived-root data/derived \
  --report artifacts/reports/bigbang-tp-2025-poc.json
```

Raster, Parquet derivato e report sono artifact runtime ignorati da Git.
