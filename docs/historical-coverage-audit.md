# Audit della copertura storica

Aggiornamento H1G: inventario territoriale post-H1E e copertura provinciale BIGBANG verificata in produzione nella release `2026-09-09T231326Z-local`. Le altre sezioni conservano le evidenze H1A.

Baseline H1A generata da `af94f22c3813c07aaa876ed8c314817cab2e5428` sul branch `phase-h1-historical-audit`.

Questo documento descrive soltanto ciò che il repository registra, trasforma e pubblica oggi. Non prova l'esistenza di sorgenti esterne non registrate e non autorizza nuove acquisizioni, elaborazioni, comparazioni o funzionalità. La verifica H1A della pubblicazione è stata eseguita in sola lettura sulla release `2026-09-08T143313Z-local`; i path `data/...` indicano i corrispondenti path logici di lavoro, mentre i path `delivery/...` indicano gli asset della release.

## Matrice esecutiva

| Dominio | Famiglia | Storia dichiarata dalla sorgente | Storia pubblicata | Livello | Politica territoriale | Opportunità | Gap principale |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Suolo | Workbook ISPRA 2025 | variazioni 2006–2024; stock 2024 | uguale | Italia, regioni, province, comuni | geografia della sorgente al 2025-01-01 | LOW | storia ulteriore sconosciuta |
| Acqua | BIGBANG ufficiale | 1951–2025 annuale | 1951–2025 annuale | Italia, regioni | osservazioni ufficiali; mappa regionale su geometria 2025 | LOW | nessun gap noto nel contratto registrato |
| Acqua | BIGBANG provinciale derivato | raster 1951–2025 | 2002–2010, 2012–2020, 2022–2025 (22 anni) | province | geometria ISTAT esatta dell'anno | HIGH | geometrie mancanti per gli altri anni |
| Foreste | INFC | 2015 | 2015 | Italia, regioni | snapshot esatto 2015; mappa regionale | UNKNOWN | altre edizioni non note al repository |
| Foreste | Copernicus TCD | 2018–2024 annuale | 2018–2024 annuale | regioni, province, comuni | geometria esatta dello snapshot | MEDIUM | storia ulteriore sconosciuta |
| Foreste | Copernicus FTY | 2018, 2021, 2024 | 2018, 2021, 2024 | regioni, province, comuni | geometria esatta dello snapshot | MEDIUM | storia ulteriore sconosciuta |
| Foreste | Copernicus DLT | 2018, 2021, 2023 | nessuna | raster registrato | non ancora applicata | HIGH | processing disabilitato |
| Foreste | Copernicus TCPC | 2018–2021 | 2018–2021 | regioni, province, comuni | geometria di fine periodo, 2021-12-31 | MEDIUM | altri intervalli non noti |
| Foreste | CORINE classi forestali | 1990, 2000, 2006, 2012, 2018 | nessuna | raster registrato | non ancora applicata | HIGH | non acquisito/elaborato/pubblicato |
| Dissesto | Snapshot IdroGEO | alluvioni 2020; frane 2024 | uguale | Italia, regioni, province, comuni | limiti ISTAT 2024 dichiarati dalla sorgente | UNKNOWN | snapshot precedenti sconosciuti |
| Emissioni | GHG nazionale | 1990–2024 annuale | 1990–2024 annuale | Italia | country-only | LOW | nessun gap noto nel contratto registrato |
| Emissioni | NFR nazionale | 1990–2024 annuale | 1990–2024 annuale | Italia | country-only | LOW | nessun gap noto nel contratto registrato |
| Emissioni | Disaggregazione provinciale SNAP | 1990, 1995, 2000, 2005, 2010, 2015, 2019, 2023 | 2019, 2023 | province | geometria esatta dello snapshot | HIGH | sei periodi dichiarati non trattenuti |

“Pubblicata” significa presente nella catena canonical/derived → delivery → frontend della release verificata. Non significa automaticamente “confrontabile” o “classificabile”.

## Metodo ed evidenze

Le affermazioni sono classificate così:

- `repository_fact`: struttura o file presente nel repository;
- `source_config_claim`: dichiarazione nel registro locale, non riverificata sul sito esterno in H1A;
- `existing_ADR_decision`: decisione architetturale accettata;
- `code_behavior`: comportamento imposto dal codice;
- `test_contract`: comportamento coperto da test;
- `published_release_artifact`: presenza nella release attiva letta senza scritture;
- `unknown_requires_external_research`: quesito da risolvere in H1B.

Gli stati hanno significati distinti: sorgente dichiarata esistente, registrata, acquisita, canonicalizzata o derivata, consegnata e visibile. Analogamente, visualizzare un valore, costruire una serie, calcolare un delta e produrre una classifica sono capacità separate. Il modello frontend applica l'intersezione fra capacità semantica e asset/evidenza effettivamente pubblicati (`apps/web/lib/domain-capabilities.ts`, `apps/web/lib/explorer-model.ts`).

## Inventario delle sorgenti registrate

| Dominio | `source_id` | Editore e dataset | Versione | Asset o pattern | Livelli e tempo | Frequenza / stato | Limiti principali |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Territori condivisi | `istat-administrative-boundaries` | ISTAT; confini amministrativi a fini statistici | `unknown_in_repository` | `generalizzati/{year_path}/Limiti{file_date}_g.zip` | regioni, province, comuni; date amministrative annuali 2002–2026 dichiarate | annuale; confini statistici ufficiali | il codice materializza solo 2006, 2012 e 2015–2025; generalizzati distinti dai confini dettagliati |
| Suolo | `ispra-soil-2025` | ISPRA/SNPA; estratto dati consumo di suolo 2025 | `unknown_in_repository` | `consumo_di_suolo_estratto_dati_2025_anni_2006_2024.xlsx` | Italia, regioni, province, comuni; 2006–2024 irregolare | annuale; stato non etichettato nel workbook | stock solo 2024; geografia 2025 |
| Acqua | `ispra-bigbang-10` | ISPRA; BIGBANG 10.0 | `bigbang-10-1951-2025` | due workbook; cinque archivi `{TP,AE,IF,GR,RF}_ANNUAL_1951-2025.zip`; `GRID_UNITS.txt` | Italia/regioni ufficiali, raster; 1951–2025 annuale | annuale; stima di modello ufficiale | nessun dato provinciale/comunale nelle tabelle; ricalcolo per versione |
| Foreste | `infc-2015-forests` | CUFAA / CREA; nome dataset non esplicito | `unknown_in_repository` | quattro ZIP per volume, incremento, biomassa e carbonio | Italia, regioni; snapshot 2015 | `unknown_in_repository`; statistiche ufficiali pubblicate | niente province/comuni; Trento e Bolzano non aggregati implicitamente |
| Foreste | `copernicus-hrl-forests` | UE / CLMS; nome e versione non espliciti | `unknown_in_repository` | API CDSE e contratti prodotto TCD/FTY/DLT/TCPC | raster e aggregati derivati; 2018–2024 secondo prodotto | `unknown_in_repository`; `unknown_in_repository` | TCD non equivale a foresta FAO; DLT disabilitato |
| Foreste | `copernicus-corine-forests` | UE / CLMS; nome e versione non espliciti | `unknown_in_repository` | ID download per 1990, 2000, 2006, 2012, 2018 | raster e aggregati potenziali; status a sei anni | `unknown_in_repository`; `unknown_in_repository` | serie distinta da HRL; MMU 25 ha |
| Dissesto | `ispra-idrogeo-risk-2024` | ISPRA IdroGEO; pericolosità e rischio | `unknown_in_repository` | API `/api/pir/{italia,regioni,province,comuni}/export` | tutti i livelli; indicatori 2020/2024 | irregolare; snapshot ufficiale | non annuale; `-1` è indisponibile; limiti ISTAT 2024 |
| Emissioni | `ispra-emissions-ghg-2026` | ISPRA; gas serra nazionali | `2026-1990-2024` | `Emissioni-GHG-Sintesi-<anno>.xlsx` | Italia; 1990–2024 annuale | annuale; inventario ufficiale, publication status unknown | categorie ufficiali non sommate implicitamente |
| Emissioni | `ispra-emissions-nfr-2026` | ISPRA; inquinanti nazionali NFR | `2026-1990-2024` | `Emissioni-POL-NFR-<anno>.xlsx` | Italia; 1990–2024 annuale | annuale; inventario ufficiale, publication status unknown | settori NFR preservati come dimensioni |
| Emissioni | `ispra-emissions-provincial-2026` | ISPRA; disaggregazione provinciale | `2026-2023-disaggregation` | `Disaggregazione_provinciale_inventario_<anno>_rev<rev>_<anno>.xlsx` | province/grid; otto snapshot 1990–2023 | irregolare; disaggregazione top-down ufficiale | slice iniziale 2019/2023; province sarde obsolete nel 2010/2015; grid escluso |

I landing URL, gli URL completi e i contratti di formato sono conservati nei dieci file sotto `config/sources/`. Dove un campo non esiste nel file, l'audit usa esplicitamente `unknown_in_repository`; non ricava versione, frequenza o stato dalla sola denominazione commerciale.

## Suolo

### Grafo di dipendenza

```text
config/sources/ispra-soil.yaml
└─ data/raw/ispra-soil-2025/consumo-di-suolo-2025.xlsx
   └─ src/stato_italia/soil.py
      └─ data/canonical/soil/dataset_version=2025-2024-observations/observations.parquet
         ├─ src/stato_italia/analytics.py
         │  └─ data/derived/soil/algorithm_version=soil-analytics-v1/analytics.parquet
         └─ src/stato_italia/delivery.py
            └─ data/delivery/soil/{index,provenance,maps,profiles,rankings,geometry}
               ├─ src/stato_italia/territories.py + src/stato_italia/tiles.py
               └─ apps/web/app/suolo/page.tsx
                  + apps/web/components/soil-workspace.tsx
                  + apps/web/lib/{domain-capabilities,explorer-model,data}.ts
```

Tutti i periodi registrati sono canonicalizzati, inclusi nelle analytics, consegnati e visibili: variazioni `2006-2012`, `2012-2015` e poi annuali fino a `2023-2024`; lo stock è solo `2024`. Tutte le righe sono intenzionalmente legate a `2025-01-01`, perché il workbook 2025 usa quella geografia. Non è un fallback storico scorretto. `territory_id` e `territory_version_id` restano quindi costanti fra i periodi di questo dataset.

Capacità correnti: display e serie sì; confronto solo a parità di metrica/unità; ranking quando pubblicato. Opportunità `LOW`: il gap non è fra registro e prodotto, ma nell'eventuale storia ufficiale ulteriore, da verificare fuori dal repository.

## Acqua

### BIGBANG ufficiale Italia/regioni

```text
config/sources/ispra-bigbang.yaml
└─ data/raw/ispra-bigbang-10/{BIGBANG100_TABLES_ITALY_01.xlsx,BIGBANG100_TABLES_REGIONS_02.xlsx}
   └─ src/stato_italia/water.py
      └─ data/canonical/water/dataset_version=bigbang-10-1951-2025/observations.parquet
         └─ src/stato_italia/water_delivery.py
            └─ data/delivery/water/{index,provenance,maps,profiles}
               ├─ delivery/soil/geometry/istat-region-2025.pmtiles
               └─ apps/web/app/acqua/page.tsx
                  + apps/web/components/water-workspace.tsx
                  + apps/web/lib/{water-explorer-model,domain-capabilities,explorer-model}.ts
```

La serie ufficiale 1951–2025 è presente per Italia e regioni a tutti i livelli della catena. Le righe del workbook restano osservazioni ufficiali di modello e non vengono sostituite dalle statistiche zonali. Per la mappa regionale il delivery riusa la geometria regionale 2025 del dominio Suolo: questa è la politica effettiva del prodotto ufficiale, separata dal derivato provinciale.

Capacità: display e serie sì; confronto soltanto a parità di metrica, unità, metodo e geometria; ranking no. Opportunità `LOW`.

### BIGBANG provinciale derivato

```text
config/sources/ispra-bigbang.yaml#raster_products
└─ data/raw/ispra-bigbang-10/{TP,AE,IF,GR,RF}_ANNUAL_1951-2025.zip + GRID_UNITS.txt
   └─ src/stato_italia/bigbang_raster_poc.py
      + src/stato_italia/bigbang_historical_processing.py
      + src/stato_italia/bigbang_historical_territory_policy.py
      ├─ data/canonical/water/dataset_version=bigbang-10-1951-2025/observations.parquet
      └─ data/derived/water/historical/dataset_version=bigbang-10-1951-2025/
         algorithm_version=bigbang-tp-zonal-area-weighted-v1/observations.parquet
         └─ src/stato_italia/water_delivery.py
            └─ data/delivery/water/{index,provenance,maps,profiles,geometry}
               ├─ data/canonical/territories/reference_year=<anno>/province.parquet
               └─ frontend Acqua e `water-explorer-model.ts`/capability condivisi
```

La sorgente raster dichiara 1951–2025; il derivato provinciale pubblica esattamente `2002–2010`, `2012–2020`, `2022–2025`: 22 anni. L'artefatto storico contiene 11.780 record provinciali, senza valori mancanti, per tutte le cinque metriche BIGBANG (TP, AE, IF, GR, RF). Verifica di produzione H1F: release `2026-09-09T231326Z-local`, con 12 anni esistenti riusati e 10 nuovi anni elaborati.

Restano non supportati:

- `1951–2001`: nessuna geometria provinciale canonica annuale esatta nell'inventario corrente del progetto;
- `2011`: snapshot censuario `2011-10-09`, non ordinario e non accettato come geometria esatta per l'intero anno BIGBANG;
- `2021`: snapshot `2021-12-31`, valido per usi coerenti con quella data ma non per l'aggregazione provinciale BIGBANG dell'intero anno 2021.

ADR 0015 vieta nearest-year, current-boundary backfill e intervalli non documentati. Il comune resta fuori per il vincolo metodologico `> 100 km²`. `territory_version_id` cambia con l'anno; una serie può mostrare punti su geometrie diverse, ma il delta viene bloccato se l'evidenza geometrica o metodologica cambia. Ranking non autorizzato. Opportunità `HIGH`: molta storia raster è registrata, ma non è pubblicabile senza geometrie esatte o intervalli ufficiali documentati.

## Foreste

Le statistiche Copernicus sono dati derivati (`official_status=derived_by_stato_italia`) anche se oggi risiedono nel path canonical forestale `algorithm_version=forests-zonal-statistics-v3`. Questa collocazione non trasforma il dato in osservazione ufficiale e va letta insieme ad ADR 0003 e ai campi di provenienza.

### INFC 2015

```text
config/sources/infc-2015-forests.yaml
└─ data/raw/infc-2015-forests/{volume,volume_increment,biomass,carbon}.zip
   └─ src/stato_italia/forests.py
      └─ data/canonical/forests/dataset_version=infc2015-published-tables/observations.parquet
         └─ src/stato_italia/forests_delivery.py
            └─ data/delivery/foreste/{index,provenance,maps,rankings,geometry}
               ├─ data/canonical/territories/reference_year=2015/region.parquet
               └─ apps/web/app/foreste/page.tsx
                  + apps/web/components/{soil-workspace,soil-map}.tsx
                  + capability/explorer condivisi
```

Snapshot ufficiale 2015: Italia e regioni nel canonical; mappe regionali su geometria esatta 2015. Nessuna estensione silenziosa a province o comuni. Display sì, serie temporale/delta no per singolo snapshot, ranking regionale se pubblicato. Opportunità `UNKNOWN` finché H1B non verifica altre edizioni ufficiali e comparabilità.

### Copernicus TCD, FTY e TCPC

H1H ha completato con successo la materializzazione in produzione del ciclo moderno HR-VLCC: TCD annuale `2018–2024`, FTY `2018`, `2021`, `2024`, TCPC esclusivamente `2018–2021`. DLT resta non operativo (`statistical_api_enabled: false`). HRL legacy `2012`/`2015` resta rinviato a H1I per la discontinuità metodologica e di risoluzione; CORINE e INFC storico restano rinviati. TCPC `2021–2024` non è verificato né pubblicato nel contratto corrente.

Closeout H1H: `releaseId: 2026-09-10T224924Z-local`, `status: success`. Le annualità pubblicate riportate sotto includono l’espansione completata. I run successivi possono riusare soltanto asset-periodi del canonical attivo idratato con metriche, copertura numerica/NoData, versioni territoriali, firme snapshot e richieste raster ancora compatibili. Periodi mancanti o incompatibili vengono ricalcolati singolarmente; il canonical ordinato e il sidecar finale descrivono l'intero inventario abilitato. Il sidecar H1H aggiunge una firma per asset-periodo che include contratto e geometrie, senza includere la lista degli anni.

```text
config/sources/copernicus-forests.yaml#<asset>
└─ data/raw/copernicus-hrl-forests/<asset>/<periodo>/<regione>/...
   └─ src/stato_italia/forests.py
      └─ data/canonical/forests/algorithm_version=forests-zonal-statistics-v3/
         {zonal_statistics.parquet,zonal_statistics.coverage.json}
         └─ src/stato_italia/forests_delivery.py
            └─ data/delivery/foreste/{index,provenance,maps,rankings,geometry}
               ├─ geometria ISTAT esatta per asset/periodo/livello
               └─ frontend Foreste e capability/explorer condivisi
```

- TCD: snapshot annuali `2018–2024`; geometrie omologhe (`2021-12-31` per il 2021); regioni, province e comuni. Display, serie e ranking sì; confronto solo con evidenza identica di metodo e geometria. Opportunità `MEDIUM`.
- FTY: snapshot `2018`, `2021`, `2024`; stessa politica exact-year. Display, serie e ranking sì; confronto vincolato. Opportunità `MEDIUM`.
- TCPC: intervallo `2018-2021`, legato alla geometria di fine periodo `2021-12-31`. È un indicatore di gain/loss di copertura arborea, non una prova automatica di deforestazione. Display e ranking sì; non costituisce da solo una serie di snapshot. Opportunità `MEDIUM`.

### Copernicus DLT e CORINE

```text
DLT: config/sources/copernicus-forests.yaml#hrl_dominant_leaf_type
     └─ statistical_api_enabled: false
        └─ raw/canonical/derived/delivery/frontend: assenti

CORINE: config/sources/copernicus-corine-forests.yaml
        └─ percorso raster condizionale in src/stato_italia/forests.py
           └─ raw/canonical/derived/delivery/frontend attivi: assenti
```

DLT registra `2018`, `2021`, `2023`, ma il codice esclude l'asset dai job statistici. CORINE registra `1990`, `2000`, `2006`, `2012`, `2018`; esiste un percorso di ingest condizionale per raster locali, ma la release attiva non contiene raw CORINE né osservazioni o delivery CORINE. Etichette isolate nel frontend non equivalgono a esposizione: nessun gruppo metrico o asset pubblicato le abilita.

Entrambe hanno opportunità `HIGH`, ma per ragioni diverse: DLT ha un blocco tecnico esplicito; CORINE richiede anche verifica degli asset registrati, metodologia e politica geometrica. Non è lecito fondere CORINE e HRL in un'unica serie.

## Dissesto

```text
config/sources/ispra-idrogeo-risk-2024.yaml
└─ data/raw/ispra-idrogeo-risk-2024/{idrogeo-risk-api-responses.zip,metadata,license}
   └─ src/stato_italia/dissesto.py
      └─ data/canonical/dissesto/dataset_version=idrogeo-risk-2024/observations.parquet
         └─ src/stato_italia/dissesto_delivery.py
            └─ data/delivery/dissesto/{index,provenance,maps,geometry}
               ├─ data/canonical/territories/reference_year=2024
               └─ apps/web/app/dissesto/page.tsx
                  + apps/web/components/dissesto-workspace.tsx
                  + capability/explorer condivisi
```

Il repository contiene un solo contratto IdroGEO: indicatori di alluvione con anno di riferimento 2020 e indicatori di frana 2024, entrambi consegnati nel contesto dello snapshot sorgente che dichiara limiti ISTAT 2024. Non è una serie annuale e le due famiglie non formano un delta. Display sì; confronto e ranking no. Opportunità `UNKNOWN`: l'esistenza e la semantica di snapshot precedenti richiedono ricerca ufficiale.

## Emissioni

### Serie nazionali GHG e NFR

```text
config/sources/ispra-emissions-{ghg,nfr}-2026.yaml
└─ data/raw/<source_id>/{greenhouse-gases,air-pollutants-nfr}.xlsx
   └─ src/stato_italia/emissions_national.py
      └─ data/canonical/emissions/national/<famiglia>/
         dataset_version=2026-1990-2024/observations.parquet
         └─ src/stato_italia/emissions_delivery.py
            └─ data/delivery/emissions/national/<famiglia>.json
               + {overview,index,provenance}.json
               └─ apps/web/app/emissioni/page.tsx
                  + apps/web/components/emissions-workspace.tsx
                  + apps/web/lib/{emissions-explorer-model,domain-capabilities,explorer-model}.ts
```

Entrambe le serie coprono tutti gli anni `1990–2024` a livello Italia nel source contract, canonical, delivery e frontend. Le dimensioni ufficiali GHG/NFR restano distinte secondo ADR 0008. Display e serie sì; confronto e ranking non sono autorizzati dal capability model corrente. Opportunità `LOW` per entrambe.

### Disaggregazione provinciale SNAP

```text
config/sources/ispra-emissions-provincial-2026.yaml
└─ data/raw/ispra-emissions-provincial-2026/disaggregazione-provinciale-2023.xlsx
   └─ src/stato_italia/emissions.py
      └─ data/canonical/emissions/dataset_version=2026-2023-disaggregation/observations.parquet
         └─ src/stato_italia/emissions_delivery.py
            └─ data/delivery/emissions/{provincial/catalog.json,maps,geometry,index,overview,provenance}
               ├─ data/canonical/territories/reference_year={2019,2023}/province.parquet
               └─ frontend Emissioni e adapter/capability condivisi
```

La sorgente dichiara otto snapshot: `1990`, `1995`, `2000`, `2005`, `2010`, `2015`, `2019`, `2023`. Il contratto di ingest e la pubblicazione trattengono soltanto `2019` e `2023`, gli unici anni con mapping esplicito alla versione ISTAT nel config. Il 2010 e il 2015 includono inoltre quattro province sarde obsolete; 1990, 1995 e 2000 precedono l'inventario territoriale materializzato dal repository; il 2005 è ora presente nell’inventario H1E, senza modificare il mapping del contratto emissioni. La griglia è fuori dalla slice amministrativa.

Le mappe richiedono selezione esatta di inquinante e attività SNAP e geometria provinciale esatta dell'anno. Display e serie a due punti sì; confronto e ranking no. Opportunità `HIGH`, ma subordinata a strutture territoriali ufficiali e a eventuali crosswalk documentati: non è autorizzato rimappare alle province correnti.

## Inventario territoriale canonico

Il source config ISTAT dichiara disponibilità 2002–2026; gli snapshot storici materializzati coprono `2002–2010` e `2012–2026`, per 24 source year totali. Il 2011 è lo snapshot censuario `2011-10-09`, non un confine annuale ordinario al 1° gennaio e non fa parte dell’inventario annuale H1E. Per ogni anno materializzato esistono Parquet di regioni, province e comuni. L'identità Italia è sintetizzata nell'indice territoriale e non ha un file geometrico separato. `territory_id` è l'identità stabile quando l'entità resta la stessa; `territory_version_id` include la data e cambia fra versioni.

| Anno | Italia | Regioni | Province | Comuni | Data riferimento | Nota metadata | Uso pubblicato |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2002–2005 | sì | sì | sì | sì | 1° gennaio del rispettivo anno | — | Acqua derivata |
| 2006 | sì | sì | sì | sì | 2006-01-01 | — | Acqua derivata |
| 2007–2010 | sì | sì | sì | sì | 1° gennaio del rispettivo anno | — | Acqua derivata |
| 2012 | sì | sì | sì | sì | 2012-01-01 | — | Acqua derivata |
| 2013–2014 | sì | sì | sì | sì | 1° gennaio del rispettivo anno | — | Acqua derivata |
| 2015 | sì | sì | sì | sì | 2015-01-01 | — | Acqua derivata, INFC |
| 2016 | sì | sì | sì | sì | 2016-01-01 | — | Acqua derivata |
| 2017 | sì | sì | sì | sì | 2017-01-01 | — | Acqua derivata |
| 2018 | sì | sì | sì | sì | 2018-01-01 | — | Acqua derivata, TCD, FTY |
| 2019 | sì | sì | sì | sì | 2019-01-01 | — | Acqua derivata, emissioni provinciali |
| 2020 | sì | sì | sì | sì | 2020-01-01 | — | Acqua derivata |
| 2021 | sì | sì | sì | sì | 2021-12-31 | v3 e semantica `COD_UTS`; artefatti `2021-01-01`/v2 respinti | TCD, FTY, fine TCPC; escluso BIGBANG provinciale annuale |
| 2022 | sì | sì | sì | sì | 2022-01-01 | — | Acqua derivata |
| 2023 | sì | sì | sì | sì | 2023-01-01 | — | Acqua derivata, TCD, emissioni provinciali |
| 2024 | sì | sì | sì | sì | 2024-01-01 | — | Acqua derivata, Dissesto |
| 2025 | sì | sì | sì | sì | 2025-01-01 | — | Acqua derivata, Suolo, mappa regionale Acqua ufficiale |
| 2026 | sì | sì | sì | sì | 2026-01-01 | inventario H1E | fuori dalla copertura BIGBANG 1951–2025 |

Non sono presenti geometrie materializzate per `1990`, `1995` e `2000`; gli anni disponibili non autorizzano alcun backfill. Il 2021 canonico esiste con riferimento `2021-12-31` e contratto v3 documentati da ADR 0020 e 0021: valido per usi coerenti con quello snapshot, non per BIGBANG provinciale full-year 2021.

## Capacità storiche correnti

| Famiglia | Display | Serie | Confronto/delta | Ranking |
| --- | --- | --- | --- | --- |
| Suolo | sì | sì | stessa metrica e unità | sì, se pubblicato |
| Acqua ufficiale | sì | sì | stessa metrica, unità, metodo e geometria | no |
| Acqua provinciale derivata | sì | sì | bloccato se metodo/geometria cambiano | no |
| INFC | sì | singolo snapshot | no: singolo snapshot | sì, se pubblicato |
| TCD | sì | sì | stessa metrica, unità, metodo e geometria | sì, se pubblicato |
| FTY | sì | sì | stessa metrica, unità, metodo e geometria | sì, se pubblicato |
| TCPC | sì | singolo intervallo | no: singolo intervallo | sì, se pubblicato |
| DLT | no | no | no | no |
| CORINE | no | no | no | no |
| Dissesto | sì | snapshot distinti per famiglia | no | no |
| GHG nazionale | sì | sì | no | no |
| NFR nazionale | sì | sì | no | no |
| Emissioni provinciali SNAP | sì | 2019/2023 | no | no |

## Gap prioritari

I codici usati sono specifici: `source_period_not_ingested`, `territory_geometry_missing`, `derived_processing_missing`, `delivery_not_generated`, `frontend_not_exposed`, `source_history_unknown` e `comparison_evidence_missing`. Non vengono riassunti come generico “non implementato”.

1. **Emissioni provinciali, 1990–2015** — `source_period_not_ingested`, `territory_geometry_missing`. Sei snapshot ufficiali dichiarati non sono trattenuti; occorre stabilire la struttura provinciale originale, soprattutto le province sarde obsolete.
2. **CORINE, 1990–2018** — `source_period_not_ingested`, `derived_processing_missing`, `delivery_not_generated`, `frontend_not_exposed`. Cinque layer sono registrati ma fuori dalla catena attiva.
3. **BIGBANG provinciale, anni non coperti** — `territory_geometry_missing`. Il raster esiste nel contratto, ma mancano versioni esatte o intervalli ufficiali documentati.
4. **DLT, 2018/2021/2023** — `source_period_not_ingested`, `derived_processing_missing`, `delivery_not_generated`, `frontend_not_exposed`. Processing statistico esplicitamente disabilitato.
5. **Dissesto storico** — `source_history_unknown`. Nessun'altra edizione è registrata.
6. **INFC/HRL aggiuntivi** — `source_history_unknown`. La disponibilità esterna e la comparabilità non sono fatti di repository.
7. **Suolo ulteriore** — `source_history_unknown`. Il contratto registrato è già interamente pubblicato.
8. **Governance del delta** — `comparison_evidence_missing`. ADR 0009 e ADR 0022 necessitano una frase architetturale esplicita in H1D.

## Revisione ADR

| ADR | Stato H1A | Motivo | Candidato azione futura |
| --- | --- | --- | --- |
| 0002 | pienamente applicabile | identità stabile, versioni datate, nessun join implicito alla geografia corrente | — |
| 0003 | pienamente applicabile | osservazioni ufficiali e derivati restano separati | — |
| 0007 | domain-specific | analytics e confronti del Suolo; non è un'autorizzazione cross-domain | H1D può citarlo senza generalizzarlo |
| 0008 | pienamente applicabile | dimensioni ufficiali preservate, essenziali per NFR/SNAP | — |
| 0009 | da chiarire in seguito | regola il calcolo effimero del delta, ma si sovrappone al gate di capacità/evidenza di 0022 | H1D: esplicitare precedenza e requisiti metodo/geometria |
| 0014 | domain-specific | autorizza derivazione BIGBANG limitata e separa ufficiale/derivato | — |
| 0015 | applicabile con dettaglio successivo | exact-year/intervallo ufficiale; niente fallback. Il canonical 2021 è valido al 2021-12-31, ma resta escluso dal BIGBANG provinciale full-year | mantenere matrice derivata dall'inventario corrente |
| 0017 | parzialmente superato | l'identificazione TCDCL è corretta da 0018; copertura nazionale e integrità snapshot restano | leggere insieme a 0018 |
| 0018 | domain-specific | contratto TCD 100 m e NoData valido | — |
| 0019 | domain-specific | TCPC è intervallo 2018–2021 su geometria di fine periodo | — |
| 0020 | parzialmente superato | fissa gerarchia/data 2021; 0021 sostituisce soltanto versione contratto e semantica campi | applicare insieme a 0021 |
| 0021 | pienamente applicabile | contratto territoriale v3 e `COD_UTS` per il 2021 | — |
| 0022 | pienamente applicabile | capacità effettiva = semantica autorizzata ∩ asset/evidenza pubblicati | chiarimento H1D con 0009 |
| 0023 | domain-specific | separa Acqua ufficiale regionale e derivata provinciale; `mapGeometry` autorevole | — |
| 0024 | domain-specific | selezione esatta inquinante+SNAP e geometria provinciale del periodo | — |

### ADR 0009 rispetto ad ADR 0022

La relazione è **compatibile ma parzialmente sovrapposta e richiede chiarimento futuro**. ADR 0009 definisce quando e come il client può calcolare un delta effimero fra due osservazioni; ADR 0022 stabilisce prima se il dominio e gli asset pubblicati autorizzano quella capacità, con evidenza più rigorosa per metodo e geometria. La lettura conservativa corrente è: 0022 autorizza la capacità e richiede l'evidenza; solo dopo, 0009 disciplina il calcolo runtime. Questa è un'interpretazione H1A, non una nuova decisione: H1D deve formalizzarla o correggerla con un ADR.

## Coda di ricerca H1B

Sono domande, non risposte presunte:

1. Per ciascuno degli anni provinciali ISPRA 1990, 1995, 2000, 2005, 2010 e 2015, quale struttura territoriale ufficiale usa il workbook e sono pubblicati crosswalk o note di armonizzazione?
2. Quali prodotti ufficiali ISTAT di confini provinciali sono disponibili per 1990, 1995, 2000 e 2005, con quale data di validità e licenza?
3. Gli ID dataset/download CORINE registrati per 1990, 2000, 2006, 2012 e 2018 sono ancora risolvibili e i prodotti hanno definizioni metodologiche comparabili?
4. Quali snapshot IdroGEO precedenti sono ufficialmente scaricabili e quali anni di indicatore e geometrie amministrative dichiarano?
5. Esistono edizioni INFC aggiuntive con tabelle ufficiali confrontabili a livello Italia/regione e quali cambi metodologici richiedono separazione?
6. Per DLT 2018, 2021 e 2023, quale modalità ufficiale di acquisizione/elaborazione è sostenibile e perché il percorso statistico corrente è disabilitato?
7. Esistono snapshot TCD/FTY o intervalli TCPC ulteriori, con contratti prodotto e date contenuto verificabili?
8. Esistono confini ISTAT o intervalli ufficiali documentati che estendano BIGBANG provinciale agli anni oggi non supportati senza fallback?
9. ISPRA pubblica osservazioni di consumo di suolo pre-2006 o stock pre-2024 con geografia esplicitamente documentata?

## Output machine-readable

Il report strutturato locale è `artifacts/reports/historical-coverage-audit.json`. Fotografa H1A e non è stato rigenerato in H1G: i tredici anni territoriali di quel report non rappresentano l’inventario post-H1E di 24 source year. Contiene dieci sorgenti, tredici famiglie dataset, la revisione ADR, i gap tipizzati e la coda H1B. È intenzionalmente ignorato da Git secondo la convenzione `/artifacts/` e non è un file da pubblicare in R2.

## Limiti e sicurezza H1A

- cambi pipeline: 0;
- cambi frontend: 0;
- cambi source contract: 0;
- scritture R2: 0;
- nuovi download di sorgenti ufficiali: 0;
- cambi ADR: 0.

L'unica modifica persistente versionabile è questo documento. L'audit non avvia H1B e non modifica la matrice di supporto territoriale corrente.
