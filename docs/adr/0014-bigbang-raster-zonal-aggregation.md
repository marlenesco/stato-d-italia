# ADR 0014: aggregazione zonale raster BIGBANG 2025

**Stato:** accepted

## Contesto

BIGBANG 10.0 pubblica osservazioni modellistiche ufficiali aggregate per Italia e
Regioni e raster annuali su griglia regolare. Il progetto deve verificare se i
raster ufficiali possano sostenere valori sub-regionali senza presentare come
dato ISPRA un'aggregazione prodotta da Stato d'Italia.

Il Task 1 ha validato il proof of concept per precipitazione totale (`TP`), anno
2025, Regioni e Province. Il Task 2 applica lo stesso motore, senza modificarne la
semantica, alle cinque metriche già presenti nel canonical BIGBANG ufficiale:

| Simbolo | Metrica ufficiale | Metrica derivata |
| --- | --- | --- |
| `TP` | `water_total_precipitation_mm` | `water_total_precipitation_mm_zonal_mean` |
| `AE` | `water_actual_evapotranspiration_mm` | `water_actual_evapotranspiration_mm_zonal_mean` |
| `IF` | `water_internal_flow_mm` | `water_internal_flow_mm_zonal_mean` |
| `GR` | `water_aquifer_recharge_mm` | `water_aquifer_recharge_mm_zonal_mean` |
| `RF` | `water_surface_runoff_mm` | `water_surface_runoff_mm_zonal_mean` |

Il Task 2 resta limitato al 2025. Non modifica il canonical ufficiale, non produce
delivery, non pubblica su R2 e non entra nei workflow schedulati.

## Contratti raster verificati

La libreria ufficiale [ISPRA/SINAnet BIGBANG 10.0](https://groupware.sinanet.isprambiente.it/bigbang-data/library/bigbang100/ascii_grid/)
espone i cinque prodotti annuali. Il file ufficiale
[`GRID_UNITS.txt`](https://groupware.sinanet.isprambiente.it/bigbang-data/library/bigbang100/ascii_grid/grid_units/download/en/1/GRID_UNITS.txt),
596 byte, SHA-256 `d56a9671b9cc508e85837a838f31a812b2fac4f2ff4300ba2aa9e6cc786855a4`,
dichiara che tutti gli altri grid delle componenti di bilancio, escluse le
eccezioni nominate nel file, sono espressi in `mm`. Le cinque metriche qui usate
ricadono in tale dichiarazione.

| Simbolo | Pagina prodotto e download | Archivio verificato | Raster 2025 verificato |
| --- | --- | --- | --- |
| `TP` | [prodotto](https://groupware.sinanet.isprambiente.it/bigbang-data/library/bigbang100/ascii_grid/total_precipitation/tp_annual_1951-2025) · [download](https://groupware.sinanet.isprambiente.it/bigbang-data/library/bigbang100/ascii_grid/total_precipitation/tp_annual_1951-2025/download/en/1/TP_ANNUAL_1951-2025.zip) | `TP_ANNUAL_1951-2025.zip`; 91.421.884 byte; SHA-256 `af80b158d29190cb57dfae2204bded5dd6c3365e8579dc0c902863418242dbc9` | `tp_2025_yyc.asc` + `tp_2025_yyc.prj`; 11.809.682 byte; SHA-256 `52f1bffc413427b9694e883d7c18bd560d843b171b684c366a9c6781273e78d4` |
| `AE` | [prodotto](https://groupware.sinanet.isprambiente.it/bigbang-data/library/bigbang100/ascii_grid/actual_evapotranspiration/ae_annual_1951-2025) · [download](https://groupware.sinanet.isprambiente.it/bigbang-data/library/bigbang100/ascii_grid/actual_evapotranspiration/ae_annual_1951-2025/download/en/1/AE_ANNUAL_1951-2025.zip) | `AE_ANNUAL_1951-2025.zip`; 91.808.775 byte; SHA-256 `860c3b7882aa78e9942b70590710aba116baea8ac4a6d0d5b6fc4095877f77a4` | `ae_2025_yyc.asc` + `ae_2025_yyc.prj`; 11.808.129 byte; SHA-256 `24a973a44b449c38602269948befeec3b85906adbc7bbf143bb6f871d0a72fa8` |
| `IF` | [prodotto](https://groupware.sinanet.isprambiente.it/bigbang-data/library/bigbang100/ascii_grid/internal_flow/if_annual_1951-2025) · [download](https://groupware.sinanet.isprambiente.it/bigbang-data/library/bigbang100/ascii_grid/internal_flow/if_annual_1951-2025/download/en/1/IF_ANNUAL_1951-2025.zip) | `IF_ANNUAL_1951-2025.zip`; 96.183.083 byte; SHA-256 `8d685396d554971402cc28e9af38bf66362fe6d863e19e0c06b04cba9a15962a` | `if_2025_yyc.asc` + `if_2025_yyc.prj`; 11.809.372 byte; SHA-256 `72663d78a197b7376606d56092051d35b8b69cfab358836aa65de8d232064d62` |
| `GR` | [prodotto](https://groupware.sinanet.isprambiente.it/bigbang-data/library/bigbang100/ascii_grid/groundwater-_recharge/gr_annual_1951-2025) · [download](https://groupware.sinanet.isprambiente.it/bigbang-data/library/bigbang100/ascii_grid/groundwater-_recharge/gr_annual_1951-2025/download/en/1/GR_ANNUAL_1951-2025.zip) | `GR_ANNUAL_1951-2025.zip`; 94.421.130 byte; SHA-256 `eafc0a8e4206718b07cef7c1ab62028dfa963c2c3d7b81e1aaa31ed84b876219` | `gr_2025_yyc.asc` + `gr_2025_yyc.prj`; 11.768.891 byte; SHA-256 `8d2e1c8079c5fd0dd026320db69031abe1acf4d05e9e8b813fb4ca476029f6bb` |
| `RF` | [prodotto](https://groupware.sinanet.isprambiente.it/bigbang-data/library/bigbang100/ascii_grid/surface_runoff/rf_annual_1951-2025) · [download](https://groupware.sinanet.isprambiente.it/bigbang-data/library/bigbang100/ascii_grid/surface_runoff/rf_annual_1951-2025/download/en/1/RF_ANNUAL_1951-2025.zip) | `RF_ANNUAL_1951-2025.zip`; 96.267.880 byte; SHA-256 `5adebbfe9c30fc4cb79d1b1aa19b339de09f636343d02e6853f31e962121a597` | `rf_2025_yyc.asc` + `rf_2025_yyc.prj`; 11.803.495 byte; SHA-256 `29e604293730fbbec4dff4dcb04801215583c2df6d8d678b02e2dcff6a5364ba` |

Ogni archivio contiene esattamente 150 member: una coppia `.asc`/`.prj` per
ciascuno dei 75 anni dal 1951 al 2025. Tutti i raster 2025 hanno questo contratto:

- formato/driver `AAIGrid`, singola banda `float32`;
- CRS equal-area `EPSG:3035`;
- 1.300 × 1.400 celle da 1.000 × 1.000 m;
- bounds `(3900000, 1300000, 5200000, 2700000)`;
- NoData `-9999`;
- unità `mm`.

Il validatore richiede nome, byte, checksum e struttura completa dell'archivio,
unicità dei member 2025, checksum/byte del raster e header esatti. Una differenza
interrompe il PoC: non sono ammessi fallback su nomi simili o formati inattesi.
Gli anni 1951–2024 sono stati verificati come disponibilità dell'archivio, ma non
sono stati elaborati in questo task.

## Decisione

### Separazione tra ufficiale e derivato

Le osservazioni Italia/Regioni dei workbook restano nel canonical ufficiale con
gli ID esistenti. Le aggregazioni raster sono scritte esclusivamente in:

```text
derived/water/algorithm_version=bigbang-tp-zonal-area-weighted-v1/observations.parquet
```

L'artifact locale contiene 635 record: cinque metriche per 20 Regioni e 107
Province. Ogni record ha stato `derived_by_stato_italia` e conserva raster,
geometria, algoritmo, area valida, conteggi cella, coverage e quality flags. Il
canonical ufficiale non viene scritto; il run ne verifica l'hash prima e dopo la
derivazione.

### Algoritmo zonale e versione

La versione resta `bigbang-tp-zonal-area-weighted-v1`. Il nome nato nel Task 1 è
mantenuto intenzionalmente: lo stesso algoritmo, senza cambi semantici, è ora
applicato alle altre quattro metriche. Per TP restano quindi invariati versione,
formula e identità delle osservazioni derivate già validate.

L'unico algoritmo zonale usa l'intersezione geometrica esatta nel CRS equal-area
EPSG:3035:

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

### Dipendenza territoriale

Il PoC usa le geometrie canonical ISTAT con riferimento `2025-01-01`. La
provenance identifica il singolo `territory_version_id` e la relativa geometria.
Un cambio dei confini richiede una nuova derivazione: i risultati non vengono
trasferiti implicitamente a un'altra versione territoriale.

## Gate metodologico dei 100 km2

La [pagina ufficiale corrente del modello BIGBANG](https://www.isprambiente.gov.it/pre_meteo/idro/BIGBANG_ISPRA.html),
aggiornata per BIGBANG 10.0, dichiara tra i criteri del modello la possibilità di
ritagliare risultati su qualunque ambito territoriale `> 100 km2`. Lo stesso
criterio è riportato nella presentazione metodologica ufficiale ISPRA del 2019 di
Braca e Mariani, che indica inoltre griglia di 1 km e scala temporale minima
mensile.

La soglia è interpretata come limite/raccomandazione di applicabilità
metodologica dichiarata, non come limite tecnico del formato raster: il software
può intersecare poligoni più piccoli, ma ISPRA non rivendica la stessa
applicabilità sotto soglia.

Esito sulle geometrie ISTAT 2025:

| Livello | Esito |
| --- | --- |
| Regione | 20 su 20 sopra soglia; supportato dal PoC |
| Provincia | 107 su 107 sopra soglia; supportato dal PoC |
| Comune >= 100 km2 | 599 unità; sola fattibilità, nessun dataset prodotto |
| Comune < 100 km2 | 7.297 unità; fuori dall'applicabilità dichiarata |

La copertura completa comunale non è supportata e i Comuni restano fuori scope.
L'operatore riportato da ISPRA è strettamente `>`; il conteggio descrittivo usa
`>= 100 km2`, senza effetto sul risultato osservato.

## Validazione regionale 2025

Il confronto usa le 20 osservazioni ufficiali 2025 di ogni metrica già presenti
nel canonical regionale, senza calibrazione o tolleranza prefissata. Per tutte le
metriche il join è completo 20:20, uno a uno per `territory_id`, senza valori
mancanti.

Differenze assolute in mm:

| Metrica | Minimo | Mediana | Media | Massimo |
| --- | ---: | ---: | ---: | ---: |
| `TP` | 0,0110 | 0,2583 | 0,8099 | 7,6306 |
| `AE` | 0,0069 | 0,0918 | 0,4437 | 3,7825 |
| `IF` | 0,0034 | 0,2242 | 0,5421 | 3,9077 |
| `GR` | 0,0038 | 0,1518 | 0,2245 | 1,0171 |
| `RF` | 0,0301 | 0,1356 | 0,3752 | 3,2345 |

Differenze relative percentuali:

| Metrica | Minimo | Mediana | Media | Massimo |
| --- | ---: | ---: | ---: | ---: |
| `TP` | 0,0017% | 0,0238% | 0,0830% | 0,8910% |
| `AE` | 0,0015% | 0,0169% | 0,0757% | 0,6345% |
| `IF` | 0,0012% | 0,0560% | 0,1489% | 1,5001% |
| `GR` | 0,0023% | 0,0743% | 0,1130% | 0,6152% |
| `RF` | 0,0179% | 0,0640% | 0,1706% | 1,9771% |

Coverage regionale:

| Metrica | Minimo | Mediana | Media | Massimo |
| --- | ---: | ---: | ---: | ---: |
| `TP` | 0,9996848 | 0,9999902 | 0,9999622 | 1,0000000 |
| `AE` | 0,9996754 | 0,9999718 | 0,9999506 | 1,0000000 |
| `IF` | 0,9996754 | 0,9999718 | 0,9999506 | 1,0000000 |
| `GR` | 0,9996754 | 0,9999718 | 0,9999506 | 1,0000000 |
| `RF` | 0,9996754 | 0,9999718 | 0,9999506 | 1,0000000 |

Nessuna metrica presenta uno scostamento strutturale rispetto alle altre. I
massimi di TP, AE, IF e RF ricadono nelle Marche, mentre i valori centrali restano
molto più bassi; non emerge un bias di scala o unità. Tutte e cinque le metriche
sono state quindi ammesse esplicitamente al calcolo provinciale.

Il [Rapporto ISPRA 339/2021](https://www.isprambiente.gov.it/files2021/pubblicazioni/rapporti/rapporto_ispra_339-21_bigbang_ld.pdf)
descrive aggregazioni ufficiali tramite `Zonal statistics` di ArcGIS su confini
vettoriali scelti dall'Istituto. Il PoC usa invece geometrie ISTAT 2025
generalizzate e intersezioni area-weighted esatte. Queste differenze verificabili
di geometria e algoritmo sono cause plausibili degli scostamenti; senza la
geometria/mask esatta e i parametri operativi delle tabelle ISPRA non è possibile
attribuire con certezza il residuo. Nessun valore è corretto per forzare la
coincidenza.

## Province e diagnostica di coverage

| Metrica | Record | Missing | Coverage min | Mediana | Media | Massimo |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `TP` | 107 | 0 | 0,9946962 | 0,9999999 | 0,9999221 | 1,0000000 |
| `AE` | 107 | 0 | 0,9946215 | 0,9999981 | 0,9999089 | 1,0000000 |
| `IF` | 107 | 0 | 0,9946215 | 0,9999981 | 0,9999089 | 1,0000000 |
| `GR` | 107 | 0 | 0,9946215 | 0,9999981 | 0,9999089 | 1,0000000 |
| `RF` | 107 | 0 | 0,9946215 | 0,9999981 | 0,9999089 | 1,0000000 |

Le differenze di coverage costiero restano visibili nei campi diagnostici e non
vengono trasformate in zero o occultate. Tutti i valori provinciali sono metriche
derivate da Stato d'Italia.

## Conseguenze e limiti

- Il PoC dimostra la fattibilità tecnica e metodologica per cinque metriche,
  Regioni e Province, esclusivamente per il 2025.
- Non autorizza ancora la pipeline storica 1951–2025 né crosswalk territoriali.
- Non autorizza una pipeline di produzione, workflow schedulati o pubblicazione
  R2.
- Non autorizza delivery frontend o modifiche a `territory-insights`.
- Non autorizza copertura comunale completa; nessun dato comunale è prodotto.
- Una futura produzione deve definire esplicitamente politica di coverage,
  lifecycle del raster, dipendenze territoriali e criteri di accettazione.

## Riproduzione locale

Il primo passaggio calcola soltanto le Regioni e genera il report necessario alla
valutazione manuale degli scostamenti:

```sh
uv run python -m stato_italia.bigbang_raster_poc \
  --archive-dir data/raw/ispra-bigbang-10/raster-poc \
  --canonical-root data/canonical \
  --derived-root data/derived \
  --report artifacts/reports/bigbang-2025-regional-validation.json
```

Dopo la verifica documentata che nessuna metrica presenta problemi strutturali,
le Province vengono abilitate esplicitamente:

```sh
uv run python -m stato_italia.bigbang_raster_poc \
  --archive-dir data/raw/ispra-bigbang-10/raster-poc \
  --canonical-root data/canonical \
  --derived-root data/derived \
  --report artifacts/reports/bigbang-2025-poc.json \
  --approve-provinces TP AE IF GR RF
```

Raster, Parquet derivato e report sono artifact runtime ignorati da Git.
