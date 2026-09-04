# ADR 0015: politica territoriale per lo storico BIGBANG 1951–2025

**Stato:** accepted

## Contesto

BIGBANG 10.0 rende disponibili raster annuali dal 1951 al 2025, ma una
derivazione zonale storica è lecita soltanto quando la geometria usata è
esplicitamente coerente con l'anno. ADR 0002 vieta di ricostruire una serie sui
confini correnti per comodità; ADR 0014 ha autorizzato soltanto il PoC 2025.

Questo ADR definisce una policy e una matrice di supporto locale. Non implementa
il processing raster storico, non modifica il canonical ufficiale, non crea
delivery e non pubblica su R2.

## Inventario canonical locale

L'ispezione di `data/canonical/territories/` ha trovato i reference year
`2006`, `2012`, `2015`–`2025`. Per ogni snapshot sono presenti i livelli
`region`, `province` e `municipality`; la geometria è nel rispettivo
`canonical/territories/reference_year=YYYY/{level}.parquet`.

| Reference year | Regioni | Province | Comuni |
| --- | ---: | ---: | ---: |
| 2006 | 20 | 107 | 8.101 |
| 2012 | 20 | 110 | 8.092 |
| 2015 | 20 | 110 | 8.048 |
| 2016 | 20 | 110 | 8.003 |
| 2017 | 20 | 107 | 7.983 |
| 2018 | 20 | 107 | 7.960 |
| 2019 | 20 | 107 | 7.926 |
| 2020 | 20 | 107 | 7.904 |
| 2021 | 20 | 107 | 7.904 |
| 2022 | 20 | 107 | 7.904 |
| 2023 | 20 | 107 | 7.901 |
| 2024 | 20 | 107 | 7.899 |
| 2025 | 20 | 107 | 7.896 |

Ogni feature conserva un `territory_version_id` nel formato
`it:{level}:{istat_code}@{reference_date}`; l'artifact di supporto registra per
ogni snapshot il pattern, un campione di ID e la geometry reference.

Il canonical locale etichetta il file 2021 con `reference_date=2021-01-01`.
La fonte ISTAT dichiara invece il 31 dicembre 2021. La policy lo esclude fino a
un re-ingest che allinei metadata e `territory_version_id`: non è lecito
reinterpretare implicitamente quel file.

## Fonti ufficiali ISTAT verificate

1. [Confini delle unità amministrative a fini statistici](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/), dataset ISTAT con regioni, province e comuni a copertura nazionale. Sono disponibili annualmente dal 2002, con riferimento al 1 gennaio, e ai censimenti 1991, 2001 e 2011; il 2021 è riferito al 31 dicembre. I dati 2022 e 2023 sono stati riprodotti/sostituiti dopo la revisione delle basi territoriali. La licenza generale del sito è [CC BY 4.0](https://www.istat.it/note-legali/) salvo diversa indicazione da verificare alla singola acquisizione. I confini sono per fini statistici e la scala non è uniformemente certificata.
2. [Confini statistico-amministrativi: analisi storica](https://www.istat.it/notizia/confini-statistico-amministrativi-analisi-storica/), ricostruzione ISTAT per censimenti 1861–1981. Per 1951, 1961, 1971 e 1981 sono disponibili shape solo provinciali; i limiti comunali elettronici antecedenti al censimento 1991 non sono disponibili e la ricostruzione è trasposta dalla geografia comunale 2011, con possibili approssimazioni. Questa risorsa non è stata acquisita né contrattualizzata in questo task, quindi non dimostra supporto operativo.

SITUAS può documentare variazioni amministrative e territoriali, ma un intervallo
di validità entra nella policy solo se viene acquisito come metadata territoriale
con fonte ufficiale, inizio, fine e regola espliciti. Non è un crosswalk
automatico.

## Decisione

Il componente puro `bigbang_historical_territory_policy` restituisce una
decisione deterministica per anno, livello e versioni territoriali disponibili.
Non scarica raster, non calcola zonal statistics e non pubblica.

| Livello | Politica 1951–2025 |
| --- | --- |
| Italia | `official`: restano le osservazioni dei workbook BIGBANG; nessuna sostituzione raster. |
| Regioni | `official`: restano prioritarie le osservazioni dei workbook; il raster è solo diagnostico/validazione. |
| Province | `derived_supported` soltanto con snapshot canonical dello stesso anno o intervallo ufficiale documentato; altrimenti `unsupported_missing_exact_geometry`. |
| Comuni | `unsupported_methodology`: fuori scope per il gate BIGBANG `> 100 km2` già accettato in ADR 0014. |

Una versione exact-year è valida solo se `territory_reference_date` coincide con
la data ISTAT ufficialmente attesa: per il 2021 è `2021-12-31`, negli snapshot
annuali ordinari è `YYYY-01-01`. Una data diversa è un errore fail-closed, anche
quando il `reference_year` coincide.

Non esistono fallback nearest-year, current-boundary backfill o crosswalk
inventati. Exact-year e intervallo documentato non hanno priorità reciproca:
più versioni esatte, più intervalli sovrapposti oppure una versione exact-year
insieme a un intervallo valido per lo stesso anno sono ambiguità e fanno fallire
la policy, non una scelta arbitraria.

Con l'inventario corrente risultano supportate per le Province 12 annualità:
`2006`, `2012`, `2015`–`2020`, `2022`–`2025`. Restano non supportate 63
annualità, incluso il 2021 per l'incoerenza metadata descritta sopra. Non sono
stati registrati intervalli ufficiali documentati nel progetto.

## Support matrix locale

Il comando seguente produce un artifact ignorato da Git:

```sh
uv run python -m stato_italia.bigbang_historical_territory_policy \
  --canonical-root data/canonical \
  --report artifacts/reports/bigbang-historical-territory-support.json
```

La matrice contiene 300 righe (75 anni × Italia, Regioni, Province e Comuni) con
`reference_year`, `territory_level`, `support_status`, `data_kind`,
`territory_reference_date`, `territory_source`, `geometry_reference` e `reason`.
`derived_supported` è ammesso soltanto con una territory reference esplicita.

## Conseguenze

- Il prossimo task potrà implementare soltanto le annualità provinciali che la
  matrice dichiara `derived_supported` al momento della sua esecuzione.
- L'eventuale acquisizione di altri confini ISTAT deve aggiungere contratti,
  provenance, date di riferimento esatte e test prima di cambiare la matrice.
- Il riallineamento del metadata 2021 richiede un re-ingest esplicito e non una
  correzione retroattiva silenziosa dei risultati.
- Non viene prodotto alcun dato BIGBANG comunale.

## Implementazione locale Task 4

Il Task 4 consuma questa policy senza modificarla: costruisce il piano
deterministico per tutte le 75 annualità e processa le Province soltanto per le
righe `derived_supported` che hanno data e geometry reference esplicite. Il
risultato è un artifact locale separato dal PoC 2025, in
`derived/water/historical/dataset_version=bigbang-10-1951-2025/`, e non scrive
né Regioni derivate né Province nel canonical ufficiale.

Per ogni coppia anno/metrica il processing verifica l'intero contratto ZIP,
risolve il member annuale esatto e registra il suo SHA-256 runtime. Le Regioni
sono calcolate solo temporaneamente come diagnostica contro il workbook
ufficiale: una mancata geometry exact-year resta non eseguibile e non autorizza
fallback. Un mismatch strutturale di scala/unità, un join incompleto o una
copertura regionale vuota interrompono la relativa derivazione provinciale.

L'implementazione non modifica il significato del zonale area-weighted già
accettato in ADR 0014, non re-ingesta il 2021 e non introduce geometrie,
crosswalk o delivery.

L'identità di ogni osservazione raster-derived storica include algorithm
version, derived metric ID, BIGBANG reference year, SHA-256 del raster e
territory version ID. L'anno è esplicito per evitare collisioni quando una
stessa geometry version è validamente riusata da più annualità mediante un
intervallo ufficiale documentato.

## Integrazione production Task 5

Il derived storico è un artifact della scope `data`, con logical path stabile
`derived/water/historical/dataset_version=bigbang-10-1951-2025/algorithm_version=bigbang-tp-zonal-area-weighted-v1/observations.parquet`
e processing family esplicita `water_historical`. Le geometrie territoriali
ISTAT restano shared. Il canonical ufficiale `canonical/water/...` conserva
esclusivamente Italia e Regioni: le sole righe provinciali raster-derived sono
nel parquet separato con `official_status=derived_by_stato_italia`.

La stessa family `water` persiste nel source state i due workbook, i cinque ZIP
annuali e `GRID_UNITS.txt`, con raw deterministico e sidecar metadata. Il primo
preflight dopo l'introduzione di questi asset rileva le entry assenti nello
source state attivo e richiede il bootstrap senza `--force`; dopo una release
completa, i controlli invariati sono un vero no-op e non avanzano il manifest.

Il derived dipende semanticamente da `water` e `boundaries`: una variazione di
una delle due family lo ricostruisce; una variazione data non correlata lo porta
avanti come oggetto immutabile identico. Per una ricostruzione da soli confini,
o con un solo ZIP aggiornato, gli ZIP BIGBANG invariati e i loro sidecar sono
idratati dalla release attiva verificando SHA-256, non dalla cache del runner.
Prima del publish la coerenza di release verifica tutti i campi di provenance,
i cinque SHA degli ZIP presenti nel source state, metriche/dataset/algoritmo e
le geometry reference dichiarate. La vera acceptance R2 resta da eseguire dopo
review; questa integrazione non l'ha avviata né ha pubblicato alcun oggetto.
