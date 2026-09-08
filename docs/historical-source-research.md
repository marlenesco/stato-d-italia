# Historical source research

Ricerca H1B eseguita il 9 settembre 2026 sul branch `phase-h1-historical-audit`, a partire da `c48138210534692c7c91d873b883c40c655f2c9e`.

## Scope and evidence rules

Questo documento integra, senza sostituirlo, l'[audit H1A dello stato del repository](historical-coverage-audit.md). H1A descrive ciò che Stato d'Italia registra, trasforma e pubblica; H1B verifica invece ciò che gli editori ufficiali rendono disponibile fuori dal repository. Una sorgente scoperta qui non è automaticamente autorizzata all'ingest, alla pubblicazione, al confronto o alla rimappatura territoriale.

Sono state usate soltanto pagine, download e documentazione degli editori ufficiali. Le conclusioni hanno una delle seguenti forze:

- `VERIFIED_DOWNLOAD`: artefatto ufficiale scaricabile o interrogabile verificato;
- `VERIFIED_OFFICIAL_PAGE`: una pagina ufficiale conferma esistenza o copertura, senza verifica diretta dell'artefatto;
- `VERIFIED_DOCUMENTATION_ONLY`: la documentazione ufficiale descrive il dato, ma l'accesso operativo non è stabilito;
- `OFFICIAL_MENTION_NO_DATASET`: esiste una pubblicazione ufficiale, ma non è stato trovato un dataset storico riusabile;
- `UNRESOLVED`: evidenza insufficiente.

Le classi di formato usate sono `API`, `XLS/XLSX`, `CSV`, `Parquet`, `GeoPackage`, `Shapefile`, `GeoJSON`, `GeoTIFF`, `ZIP archive`, `PDF/table only`, `interactive portal only` e `unavailable`. Le classi di accesso sono `direct stable URL`, `discoverable dynamic URL`, `API-generated`, `manual download`, `requires session` e `currently broken`.

I gap sono classificati esclusivamente come `no_gap`, `source_available_not_registered`, `registered_not_ingested`, `ingested_not_delivered`, `territory_geometry_missing`, `methodology_evidence_missing`, `machine_readable_source_not_found`, `official_history_not_found` o `requires_H1C_policy`. “Anno vicino” non significa geometria valida: H1B non autorizza nearest-year fallback, geografia corrente retroattiva o crosswalk impliciti.

## Executive findings

1. ISTAT pubblica confini amministrativi annuali dal 2002 al 2026, con date censuarie specifiche per 1991, 2001 e 2011 e con il 2021 riferito al 31 dicembre. Questo sblocca come candidati esatti i periodi provinciali emissioni 2005, 2010 e 2015, ma non 1990, 1995 e 2000; gli snapshot censuari vicini non sono sostituti autorizzati. I prodotti contengono regioni, province e comuni in Shapefile WGS84, sia generalizzati sia dettagliati. ([ISTAT, confini 2018 e serie storica](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/))
2. SITUAS documenta le variazioni amministrative, i comuni soppressi, i cambi di denominazione e codice e le dipendenze territoriali, con storia dal 1861 e variazioni dal 1991; è evidenza per spiegare i cambi, non un crosswalk automatico delle osservazioni. ([ISTAT, codici territoriali e SITUAS](https://www.istat.it/classificazione/codici-dei-comuni-delle-province-e-delle-regioni/), [SITUAS](https://situas.istat.it/web/))
3. L'archivio ISPRA del consumo di suolo espone cartografie e indicatori storici dal 2006. L'artefatto regionale 2006 verificato dichiara nel metadata un join di indicatori 2006 a `Reg_2024_r_LAEA.shp`: almeno quella distribuzione storica usa quindi una geografia successiva armonizzata, non il confine amministrativo contemporaneo. ([ISPRA, archivio cartografie](https://groupware.sinanet.isprambiente.it/uso-copertura-e-consumo-di-suolo/library/consumo-di-suolo), [ISPRA, indicatori 2006](https://groupware.sinanet.isprambiente.it/uso-copertura-e-consumo-di-suolo/library/consumo-di-suolo/indicatori/consumo_2006/poligoni/consumo_reg06/download/en/1/Consumo_REG06.zip))
4. BIGBANG 10.0 copre già il massimo arco ufficiale dichiarato, 1951–2025. Il gap provinciale residuo non è nel raster sorgente: è soprattutto disponibilità/registrazione della geometria esatta e politica H1C sul significato territoriale delle statistiche zonali. Le tabelle ufficiali pubblicano Italia, regioni e distretti idrografici, non una serie ordinaria per provincia. ([ISPRA, BIGBANG 10.0](https://www.isprambiente.gov.it/pre_meteo/idro/BIGBANG_ISPRA.html), [archivio grid](https://groupware.sinanet.isprambiente.it/bigbang-data/library/bigbang100/ascii_grid/), [archivio tabelle](https://groupware.sinanet.isprambiente.it/bigbang-data/library/bigbang100/excel_tables/))
5. Gli inventari forestali nazionali ufficiali hanno riferimenti 1985, 2005 e 2015. Il 2005 ha tabelle statistiche ufficiali ma il collegamento operativo osservato richiede una sessione SIAN; per il 1985 sono state trovate pubblicazioni PDF, non tabelle machine-readable verificate. Una tabella INFC confronta esplicitamente 2005 e 2015 per alcune grandezze, ma ciò non rende automaticamente comparabili tutti gli indicatori omonimi. ([INFC, prodotti e servizi](https://www.inventarioforestale.org/it/prodotti-e-servizi/), [statistiche 2005](https://www.inventarioforestale.org/it/statistiche-infc/), [statistiche 2015](https://www.inventarioforestale.org/it/statistiche_infc/), [superficie e variazioni](https://www.inventarioforestale.org/it/superficie-e-composizione-area-and-composition/))
6. La storia ufficiale CLMS è più ampia della configurazione corrente: TCD, DLT e FTY hanno prodotti 2012 e 2015; TCD e DLT hanno inoltre annualità 2018–2023, mentre FTY ha 2018 e 2021. Il passaggio da 20 m a 10 m e il nuovo ciclo produttivo impediscono di presumere stabilità metodologica. ([CLMS, Forests and Tree Cover](https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover?tab=technical_summary))
7. CORINE conferma gli status 1990, 2000, 2006, 2012 e 2018 e i quattro change layer intermedi; non risulta uno status successivo. I confronti devono usare i change layer, non la sottrazione ingenua degli status, perché revisioni e MMU differiscono. ([CLMS, CORINE technical summary](https://land.copernicus.eu/en/products/corine-land-cover?tab=technical_summary), [CLMS FAQ](https://land.copernicus.eu/en/faq/products/corine-land-cover))
8. IdroGEO rende scaricabili mosaici di pericolosità 2017, 2020/2021 e 2024, mentre i rapporti nazionali 2015, 2018, 2021 e 2024 non equivalgono tutti a dataset aggregati storici riusabili. Le edizioni sono snapshot di piani e mosaici aggiornati, non una serie annuale di eventi. ([IdroGEO, open data](https://beta.idrogeo.isprambiente.it/app/page/open-data), [ISPRA, rapporto 2015](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/dissesto-idrogeologico-in-italia-pericolosita-e-indicatori-di-rischio-rapporto-2015), [rapporto 2024](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/dissesto-idrogeologico-in-italia-pericolosita-e-indicatori-di-rischio-edizione-2024))
9. Gli inventari nazionali GHG e NFR 2026 contengono serie annuali complete 1990–2024 e ricalcolano la storia quando cambiano metodologie, dati o allocazioni. Concettualmente la sorgente corrente è l'ultima ricostruzione ufficiale della serie completa, pur restando immutabile ogni release pubblicata da Stato d'Italia. ([ISPRA, NID 2026](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/national-inventory-document-2026-italian-greenhouse-gas-inventory-1990-2024), [ISPRA, IIR 2026](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/italian-emission-inventory-1990-2024-informative-inventory-report-2026))
10. Il workbook provinciale ufficiale contiene righe provinciali e di griglia, dimensione SNAP, inquinanti, unità e valori per 1990, 1995, 2000, 2005, 2010, 2015, 2019 e 2023. I conteggi di codici provinciali non nulli cambiano 95, 95, 103, 103, 110, 110, 107, 107: la struttura amministrativa è storica e variabile. Il report ISPRA esplicita il problema dei mutamenti provinciali e la disaggregazione top-down. ([ISPRA, disaggregazione provinciale](https://emissioni.sina.isprambiente.it/disaggregazione-provinciale/), [workbook 2023 rev. 06/2026](https://emissioni.sina.isprambiente.it/wp-content/uploads/2026/06/Disaggregazione_provinciale_inventario_2023_rev06_2026.xlsx), [rapporto 2026](https://www.isprambiente.gov.it/files2026/pubblicazioni/rapporti/rapporto_prov_432_2026.pdf))
11. Le stesse otto annualità hanno dati ufficiali sulla griglia EMEP 0,1° × 0,1° con coordinate longitudine/latitudine. Il report non assegna un codice EPSG e segnala una futura modifica della convenzione delle coordinate: la griglia è un'opportunità `HIGH`, complementare e non sostitutiva delle province, ma richiede un nuovo ADR. ([ISPRA, metodologia provinciale](https://emissioni.sina.isprambiente.it/disaggregazione-provinciale-emissioni/), [rapporto 2026](https://www.isprambiente.gov.it/files2026/pubblicazioni/rapporti/rapporto_prov_432_2026.pdf))

### Source-config claim verification

| Famiglia | Claim H1A/config | Esito ufficiale H1B | Discrepanza |
| --- | --- | --- | --- |
| Confini ISTAT | disponibilità annuale 2002–2026 | confermata; aggiunti snapshot censuari e date speciali ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) | nessuna sul range; metadata locale incompleto sulle revisioni |
| Suolo | variazioni 2006–2024, stock 2024 nel compact extract | confermato per l'estratto; l'archivio espone ulteriori artefatti stock storici armonizzati ([ISPRA](https://groupware.sinanet.isprambiente.it/uso-copertura-e-consumo-di-suolo/library/consumo-di-suolo/indicatori)) | copertura esterna più ampia del singolo asset registrato |
| BIGBANG | 1951–2025, Italia/regione ufficiali e raster | confermato ([ISPRA](https://www.isprambiente.gov.it/pre_meteo/idro/BIGBANG_ISPRA.html)) | nessuna; province ordinarie restano derivate dal progetto |
| INFC | solo 2015 operativo | edizioni ufficiali 1985/2005/2015 ([CREA](https://www.crea.gov.it/-/giornata-internazionale-delle-foreste-verso-l-inventario-nazionale-2025)) | storia ufficiale esterna più ampia |
| HRL forests | TCD 2018/21/23; FTY 2018/21; DLT 2018/21/23; TCPC 2018–21 | storia ufficiale include 2012/15 e più annualità 2018+ ([CLMS](https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover?tab=technical_summary)) | configurazione incompleta, non falsa per i periodi presenti |
| CORINE | status 1990/2000/06/12/18 | confermato; aggiunti quattro change layer ([CLMS](https://land.copernicus.eu/en/products/corine-land-cover?tab=technical_summary)) | nessuna sugli status; change non registrati |
| IdroGEO | alluvioni 2020, frane 2024 | confermato per gli indicatori correnti; esistono hazard geodata più vecchi ([IdroGEO](https://beta.idrogeo.isprambiente.it/app/page/open-data)) | contratto corrente corretto ma non esaurisce la storia geospaziale |
| Emissioni nazionali | 1990–2024 annuale | confermato per GHG e NFR ([NID](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/national-inventory-document-2026-italian-greenhouse-gas-inventory-1990-2024), [IIR](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/italian-emission-inventory-1990-2024-informative-inventory-report-2026)) | nessuna sul range; va registrata la revisione dell'intera serie |
| Emissioni provinciali | otto snapshot 1990–2023 | confermato direttamente nel workbook ([ISPRA](https://emissioni.sina.isprambiente.it/wp-content/uploads/2026/06/Disaggregazione_provinciale_inventario_2023_rev06_2026.xlsx)) | nessuna sui periodi; grid e revision log non sono coperti dalla slice corrente |

### Historical opportunity matrix

| Domain | Dataset/source | Official history | Current history | New periods | Level | Machine-readable | Territory issue | Methodology issue | Evidence | Opportunity |
| ------ | -------------- | ---------------- | --------------- | ----------- | ----- | ---------------- | --------------- | ----------------- | -------- | ----------- |
| Territori | Confini ISTAT annuali | 2002–2026; snapshot censuari 1991/2001/2011 | 2006, 2012, 2015–2025 | 1991, 2001, 2002–2005, 2007–2011, 2013–2014, 2026 | regione, provincia, comune | Shapefile; ZIP archive; `direct stable URL` | date censuarie speciali; nessun exact-year 1990/1995/2000 | revisioni 2022/2023 | `VERIFIED_DOWNLOAD` ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) | HIGH |
| Territori | SITUAS | storia dal 1861; variazioni dal 1991 | non registrato | metadati di variazione | tutti i livelli amministrativi | interactive portal only; `discoverable dynamic URL` | descrive cambi, non rimappa osservazioni | semantica del cambiamento per caso | `VERIFIED_OFFICIAL_PAGE` ([ISTAT](https://www.istat.it/classificazione/codici-dei-comuni-delle-province-e-delle-regioni/)) | HIGH |
| Suolo | Cartografie/indicatori ISPRA | 2006, 2012, 2015–2024 | variazioni 2006–2024; stock 2024 | stock storici da qualificare | Italia, regione, provincia, comune | Shapefile; XLS/XLSX; ZIP archive; `direct stable URL` | almeno il 2006 verificato è armonizzato a geografia 2024 | serie ricalcolate; classificazione evoluta | `VERIFIED_DOWNLOAD` ([ISPRA](https://groupware.sinanet.isprambiente.it/uso-copertura-e-consumo-di-suolo/library/consumo-di-suolo/indicatori)) | MEDIUM |
| Suolo | Stime anteriori al 2006 | stime/report precedenti | nessuna | potenzialmente pre-2006 | variabile | PDF/table only; `direct stable URL` | geografia non stabilita | metodi/coperture eterogenei | `OFFICIAL_MENTION_NO_DATASET` ([ISPRA 2015](https://www.isprambiente.gov.it/files/pubblicazioni/rapporti/Rapporto_218_15.pdf)) | LOW |
| Acqua | BIGBANG 10.0 raster | 1951–2025 annuale | 2006, 2012, 2015–2025 provinciale derivato | 1951–2005, 2007–2011, 2013–2014 | griglia 1 km; aggregazione derivabile | GeoTIFF; ZIP archive; `direct stable URL` | richiede geometria esatta; soglia territoriale >100 km² | intera serie ricalcolata per versione | `VERIFIED_DOWNLOAD` ([ISPRA](https://www.isprambiente.gov.it/pre_meteo/idro/BIGBANG_ISPRA.html)) | HIGH |
| Foreste | INFC/IFNI | 1985, 2005, 2015 | 2015 | 1985, 2005 | Italia, regione | XLS/XLSX per 2005 non accessibile; PDF/table only; `requires session` | unità inventariali, non province | disegni inventariali e definizioni da qualificare | `VERIFIED_OFFICIAL_PAGE` ([INFC](https://www.inventarioforestale.org/it/prodotti-e-servizi/)) | HIGH per 2005; LOW per 1985 |
| Foreste | Copernicus HRL TCD | 2012, 2015, 2018–2023 | 2018, 2021, 2023 | 2012, 2015, 2019, 2020, 2022 | raster; aggregati derivabili | GeoTIFF; API; `API-generated` | richiede geometria periodo per aggregati | 20 m → 10 m; nuovo ciclo | `VERIFIED_DOWNLOAD` ([CLMS](https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover?tab=technical_summary)) | HIGH |
| Foreste | Copernicus HRL DLT | 2012, 2015, 2018–2023 | registrati 2018/2021/2023, non processati | 2012, 2015, 2019, 2020, 2022, oltre ai registrati non consegnati | raster; aggregati derivabili | GeoTIFF; API; `API-generated` | richiede geometria periodo | 20 m → 10 m; classi/versioni | `VERIFIED_DOWNLOAD` ([CLMS](https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover?tab=technical_summary)) | HIGH |
| Foreste | Copernicus HRL FTY | 2012, 2015, 2018, 2021 | 2018, 2021 | raster; aggregati derivabili | GeoTIFF; API; `API-generated` | richiede geometria periodo | 20 m → 10 m | `VERIFIED_DOWNLOAD` ([CLMS](https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover?tab=technical_summary)) | MEDIUM |
| Foreste | Copernicus TCPC/change | 2012–2015, 2015–2018, 2018–2021 | 2018–2021 | 2012–2015, 2015–2018 | raster; aggregati derivabili | GeoTIFF; API; `API-generated` | geometria di fine periodo da decidere | 2015–2018 non aggiornato con status 2018 rivisto | `VERIFIED_DOWNLOAD` ([CLMS](https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover?tab=technical_summary)) | MEDIUM |
| Foreste | CORINE status/change | status 1990/2000/2006/2012/2018; quattro change layer | status registrati, nulla pubblicato | tutti i periodi sono nuovi in delivery | raster/vettore; aggregati derivabili | GeoTIFF; GeoPackage; `direct stable URL` | timestamp 1990 eterogeneo; aggregati richiedono policy | revisioni e MMU; usare change layer | `VERIFIED_DOWNLOAD` ([CLMS](https://land.copernicus.eu/en/products/corine-land-cover/?tab=datasets)) | HIGH |
| Dissesto | IdroGEO hazard mosaics | 2017, 2020/2021, 2024 | indicatori alluvioni 2020; frane 2024 | 2017 hazard; frane 2020/2021 | geometria hazard nazionale | Shapefile; ZIP archive; `manual download` | riferimento territoriale diverso per aggregati | mosaici PAI/versioni non omogenei | `VERIFIED_DOWNLOAD` ([IdroGEO](https://beta.idrogeo.isprambiente.it/app/page/open-data)) | MEDIUM |
| Dissesto | Rapporti/indicatori storici | edizioni 2015/2018/2021/2024 | snapshot API corrente | aggregati storici non trovati come dataset | Italia, regione, provincia, comune nei rapporti | PDF/table only; `direct stable URL` | confini dell'edizione | indicatori e basi esposte cambiano | `OFFICIAL_MENTION_NO_DATASET` ([ISPRA](https://www.isprambiente.gov.it/it/attivita/suolo-e-territorio/dissesto-idrogeologico)) | LOW |
| Emissioni | GHG/NFR nazionali | 1990–2024 annuale | 1990–2024 annuale | nessuno | Italia | XLS/XLSX; PDF/table only; `direct stable URL` | non applicabile | storia ricalcolata a ogni submission | `VERIFIED_DOWNLOAD` ([NID](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/national-inventory-document-2026-italian-greenhouse-gas-inventory-1990-2024), [IIR](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/italian-emission-inventory-1990-2024-informative-inventory-report-2026)) | LOW |
| Emissioni | Disaggregazione provinciale SNAP | 1990/1995/2000/2005/2010/2015/2019/2023 | 2019/2023 | 1990–2015 sparse | provincia | XLS/XLSX; `direct stable URL` | strutture storiche 95/103/110/107 province; exact geometry assente per tre periodi | top-down, revisioni interne | `VERIFIED_DOWNLOAD` ([ISPRA](https://emissioni.sina.isprambiente.it/disaggregazione-provinciale/)) | HIGH |
| Emissioni | Griglia EMEP | otto snapshot 1990–2023 | presente nel raw registrato; non ingested/delivered | tutti gli otto | celle 0,1° × 0,1° | XLS/XLSX; `direct stable URL` | indipendente dai confini; CRS non esplicitato | convenzione coordinate destinata a cambiare | `VERIFIED_DOWNLOAD` ([ISPRA](https://www.isprambiente.gov.it/files2026/pubblicazioni/rapporti/rapporto_prov_432_2026.pdf)) | HIGH |

## Cross-domain historical territory sources

Il prodotto ISTAT “Confini delle unità amministrative a fini statistici” pubblica download annuali 2002–2026 e basi censuarie 1991, 2001 e 2011. I livelli sono regioni, province/città metropolitane/equivalenti e comuni; i pacchetti WGS84 includono codici, nomi e gerarchia amministrativa e sono disponibili in versione generalizzata e dettagliata. La licenza ISTAT è CC BY 4.0. ([ISTAT, confini](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/), [note legali ISTAT](https://www.istat.it/note-legali/))

| Campo | Evidenza verificata |
| --- | --- |
| Prodotto/editore | “Confini delle unità amministrative a fini statistici”, ISTAT |
| Periodi | censimenti 1991/2001/2011; annuale 2002–2026 |
| Livelli nei pacchetti | regioni, province/città metropolitane/liberi consorzi, comuni e ripartizioni geografiche; non è pubblicizzato un layer nazionale separato |
| Formato/accesso | Shapefile in `ZIP archive`; `direct stable URL` dalla pagina annuale |
| Riferimento | in genere 01-01; 20-10-1991, 21-10-2001, 09-10-2011 e 31-12-2021 sono eccezioni esplicite |
| Geometria/attributi | generalizzata e dettagliata; WGS84; codici, nomi e gerarchia inclusi |
| Struttura storica | ogni pacchetto rappresenta la struttura valida alla propria data, incluse le unità provinciali equivalenti di quell'anno |
| Licenza | CC BY 4.0 |
| Revisioni | prodotti sostituibili; 2022/2023 sostituiti il 05-04-2024 |
| Evidenza | `VERIFIED_DOWNLOAD` ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/), [licenza](https://www.istat.it/note-legali/)) |

Le geometrie 2022 e 2023 risultano sostituite il 5 aprile 2024 e la pagina avverte che i dati possono essere ulteriormente revisionati: un'acquisizione futura dovrà conservare URL risolto, byte e SHA-256, non soltanto l'anno nominale. ([ISTAT, confini](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/))

Le “Basi territoriali e variabili censuarie” coprono i censimenti 1991, 2001 e 2011; l'analisi storica 1861–1981 ricostruisce confini comunali più antichi partendo dalla geografia 2011, con possibili approssimazioni, perché prima del 1991 non esistevano confini comunali elettronici originali. Queste ricostruzioni sono utili per ricerca storica ma non risolvono i periodi emissioni 1990/1995/2000. ([ISTAT, basi censuarie](https://www.istat.it/notizia/basi-territoriali-e-variabili-censuarie/), [ISTAT, confini storico-amministrativi](https://www.istat.it/notizia/confini-statistico-amministrativi-analisi-storica/))

SITUAS permette interrogazioni per data e documenta costituzioni, soppressioni, fusioni, trasferimenti, cambi di codice e denominazione. La presenza del registro è `VERIFIED_OFFICIAL_PAGE`, formato `interactive portal only`, accesso `discoverable dynamic URL`; non è stata verificata un'API stabile e non si ricava alcuna autorizzazione a redistribuire osservazioni fra unità. ([SITUAS](https://situas.istat.it/web/), [ISTAT, classificazioni territoriali](https://www.istat.it/classificazione/codici-dei-comuni-delle-province-e-delle-regioni/))

Gap: confini annuali dichiarati ma non materializzati = `registered_not_ingested`; 1990/1995/2000 = `territory_geometry_missing`; uso di date censuarie, change log o geografie armonizzate = `requires_H1C_policy`.

## Soil

La pagina ISPRA dichiara indicatori di suolo consumato, consumo e consumo netto calcolati annualmente per tutti i livelli amministrativi, dall'Italia ai comuni. L'archivio ufficiale espone cartografie 2006, 2012 e 2015–2024 e cartelle di indicatori corrispondenti; il workbook complessivo 2025 è scaricabile come XLSX. ([ISPRA, dati sul consumo di suolo](https://www.isprambiente.gov.it/it/attivita/suolo-e-territorio/suolo/il-consumo-di-suolo/i-dati-sul-consumo-di-suolo), [archivio cartografie](https://groupware.sinanet.isprambiente.it/uso-copertura-e-consumo-di-suolo/library/consumo-di-suolo), [archivio indicatori](https://groupware.sinanet.isprambiente.it/uso-copertura-e-consumo-di-suolo/library/consumo-di-suolo/indicatori))

Il pacchetto `Consumo_REG06.zip` è `VERIFIED_DOWNLOAD`; contiene Shapefile e metadata. Il lineage del metadata copia `Reg_2024_r_LAEA.shp` e unisce `Regioni2006.csv`: la geometria di quel prodotto è armonizzata al 2024. Prima di proporre vecchie edizioni, H1C deve verificare se i campi stock aggiungono davvero osservazioni non già contenute nel workbook complessivo 2025 e identificare il dizionario delle colonne. ([ISPRA, indicatori regionali 2006](https://groupware.sinanet.isprambiente.it/uso-copertura-e-consumo-di-suolo/library/consumo-di-suolo/indicatori/consumo_2006/poligoni/consumo_reg06/download/en/1/Consumo_REG06.zip), [workbook 2025](https://groupware.sinanet.isprambiente.it/uso-copertura-e-consumo-di-suolo/library/consumo-di-suolo/indicatori/consumo_suolo_2025_com_prov_reg_naz_v1.1/download/en/1/consumo_suolo_2025_Com_Prov_Reg_Naz_v1.1.xlsx))

Rispetto al solo estratto compatto descritto in H1A, i pacchetti storici mostrano campi di stock per l'anno nominale e sono quindi informazione candidata aggiuntiva. Non è però ancora dimostrato che siano unici rispetto al workbook complessivo 2025 da circa 60 MB: la risposta corretta è “nuova informazione rispetto all'estratto H1A, possibile duplicato rispetto alla distribuzione completa”, con `requires_H1C_policy`, non una raccomandazione automatica di ingest. ([ISPRA, archivio indicatori](https://groupware.sinanet.isprambiente.it/uso-copertura-e-consumo-di-suolo/library/consumo-di-suolo/indicatori), [workbook 2025](https://groupware.sinanet.isprambiente.it/uso-copertura-e-consumo-di-suolo/library/consumo-di-suolo/indicatori/consumo_suolo_2025_com_prov_reg_naz_v1.1/download/en/1/consumo_suolo_2025_Com_Prov_Reg_Naz_v1.1.xlsx))

Le pubblicazioni ufficiali riportano stime antecedenti al 2006, ma H1B non ha trovato una serie machine-readable omogenea con geografia e metodologia sufficienti. La classificazione è `OFFICIAL_MENTION_NO_DATASET`, con `machine_readable_source_not_found` e `methodology_evidence_missing`, non una nuova profondità ingestibile automaticamente. ([ISPRA, rapporto 2015](https://www.isprambiente.gov.it/files/pubblicazioni/rapporti/Rapporto_218_15.pdf), [ISPRA, rapporto 2018](https://www.isprambiente.gov.it/public_files/ConsumoSuolo2018/Rapporto_Consumo_Suolo_2018_2.pdf))

## Water

BIGBANG 10.0 pubblica bilanci idrologici mensili e annuali 1951–2025 su griglia ETRS89-LAEA da 1 km e ricalcola diciassette variabili mensili per ogni anno. Gli archivi ufficiali mettono a disposizione grid e tabelle; versioni 7, 8 e 9 arrivavano rispettivamente al 2022, 2023 e 2024, senza estendere l'inizio prima del 1951. ([ISPRA, BIGBANG 10.0](https://www.isprambiente.gov.it/pre_meteo/idro/BIGBANG_ISPRA.html), [archivio grid](https://groupware.sinanet.isprambiente.it/bigbang-data/library/bigbang100/ascii_grid/), [archivio tabelle](https://groupware.sinanet.isprambiente.it/bigbang-data/library/bigbang100/excel_tables/))

Le tabelle ufficiali coprono Italia, regioni e distretti idrografici; le edizioni precedenti comprendevano anche province autonome o compartimenti storici, ma non è stata trovata una serie ufficiale per tutte le province ordinarie. La documentazione ammette estrazioni per territori arbitrari oltre 100 km², ma non prescrive quale confine amministrativo usare per aggregare un raster storico. ([ISPRA, BIGBANG 10.0](https://www.isprambiente.gov.it/pre_meteo/idro/BIGBANG_ISPRA.html))

Conclusione: per il derivato provinciale il dato sorgente non manca. Dal 2002 in poi sono disponibili confini ISTAT annuali che potrebbero ampliare gli anni oggi materializzati; prima del 2002 il blocco resta territoriale. Ogni versione BIGBANG ricalcola l'intera serie, quindi confronti affidabili devono restare dentro la stessa versione del modello. Gap: `registered_not_ingested`, `territory_geometry_missing` e `requires_H1C_policy`. ([ISTAT, confini annuali](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/), [ISPRA, BIGBANG](https://www.isprambiente.gov.it/pre_meteo/idro/BIGBANG_ISPRA.html))

## Forests

### INFC

Le fonti ufficiali distinguono l'Inventario forestale nazionale 1985, INFC 2005 e INFC 2015. L'edizione 2005 ha periodo di rilievo 2003–2007 e anno di riferimento 2005; le statistiche 2005 e 2015 sono pubblicate a livello nazionale e regionale. ([INFC, portale](https://www.inventarioforestale.org/it/), [prodotti e servizi](https://www.inventarioforestale.org/it/prodotti-e-servizi/), [statistiche 2005](https://www.inventarioforestale.org/it/statistiche-infc/), [statistiche 2015](https://www.inventarioforestale.org/it/statistiche_infc/))

| Edizione | Rilievo/riferimento | Pubblicazione risultati verificata | Livello | Indicatori documentati | Formato/accesso | Evidenza |
| --- | --- | --- | --- | --- | --- | --- |
| IFNI85 | rilievi anni Ottanta; riferimento 1985 | volume risultati 1988 | Italia, regioni nelle tavole pubblicate | superficie, composizione e stime quantitative | PDF/table only; `direct stable URL` | `VERIFIED_DOCUMENTATION_ONLY` ([CREA](https://www.crea.gov.it/it/web/foreste-e-legno/pubblicazioni-istituzionali-e-schede-tecniche?_com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_hL6jCbbk5XCg_cur=4&_com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_hL6jCbbk5XCg_delta=8&p_p_id=com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_hL6jCbbk5XCg&p_p_lifecycle=0&p_p_mode=view&p_p_state=normal&p_r_p_resetCur=false)) |
| INFC2005 | rilievi 2003–2007; riferimento 2005 | “Metodi e risultati” 2011; dati elementari pubblicati anche nel 2016 | Italia, regioni | superficie/composizione, volume, incremento, biomassa, carbonio e altri caratteri inventariali | tabelle ufficiali via portale; `requires session`; pubblicazioni PDF | `VERIFIED_OFFICIAL_PAGE` ([CREA](https://www.crea.gov.it/it/web/foreste-e-legno/pubblicazioni-istituzionali-e-schede-tecniche?_com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_hL6jCbbk5XCg_cur=4&_com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_hL6jCbbk5XCg_delta=8&p_p_id=com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_hL6jCbbk5XCg&p_p_lifecycle=0&p_p_mode=view&p_p_state=normal&p_r_p_resetCur=false), [INFC](https://www.inventarioforestale.org/it/statistiche-infc/)) |
| INFC2015 | terzo ciclo; riferimento 2015 | sintesi risultati 2021; dati elementari 2022 | Italia, regioni | superficie/composizione, volume, incremento, biomassa, carbonio | XLS/XLSX in ZIP archive; `direct stable URL` | `VERIFIED_DOWNLOAD` ([INFC](https://www.inventarioforestale.org/it/statistiche_infc/), [dati elementari](https://www.inventarioforestale.org/it/dati-per-albero-e-ceppaia/)) |

Il download delle tabelle 2005 instrada verso SIAN e, nella verifica H1B, richiede autenticazione/sessione: l'esistenza è `VERIFIED_OFFICIAL_PAGE`, ma l'artefatto operativo è `requires session`. Le pubblicazioni CREA per 1985 e 2005 sono `PDF/table only`; nessun dataset 1985 machine-readable è stato verificato. ([INFC, statistiche 2005](https://www.inventarioforestale.org/it/statistiche-infc/), [CREA, pubblicazioni istituzionali](https://www.crea.gov.it/it/web/foreste-e-legno/pubblicazioni-istituzionali-e-schede-tecniche?_com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_hL6jCbbk5XCg_cur=4&_com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_hL6jCbbk5XCg_delta=8&p_p_id=com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_hL6jCbbk5XCg&p_p_lifecycle=0&p_p_mode=view&p_p_state=normal&p_r_p_resetCur=false))

La pagina ufficiale pubblica una tabella di variazione 2005–2015 per superficie e composizione: è evidenza di comparabilità progettata per quelle specifiche grandezze, non per l'intero dizionario. I dati elementari 2005/2015 non vanno usati per ricostruire statistiche ufficiali nazionali o regionali, come avverte lo stesso portale. ([INFC, superficie e composizione](https://www.inventarioforestale.org/it/superficie-e-composizione-area-and-composition/), [INFC, dati per albero e ceppaia](https://www.inventarioforestale.org/it/dati-per-albero-e-ceppaia/))

Il nuovo IFNI continuo è partito nel 2025 con ciclo quinquennale e aggiornamenti annuali, ma non è stato trovato un dataset statistico pubblicato: `OFFICIAL_MENTION_NO_DATASET`, `official_history_not_found` per nuovi risultati utilizzabili. ([CREA Futuro, nuovo IFNI](https://creafuturo.crea.gov.it/14618/), [portale IFNI](https://ifni.crea.gov.it/))

### Copernicus HRL

La pagina tecnica ufficiale elenca:

- TCD: 2012 e 2015 a 20/100 m; 2018–2023 annuale a 10/100 m;
- DLT: 2012 e 2015 a 20 m; 2018–2023 annuale a 10 m;
- FTY: 2012 e 2015 a 20 m, 2018 e 2021 a 10 m; tutti anche a 100 m;
- Tree Cover Change: 2012–2015, 2015–2018 e 2018–2021 a 20 m.

La stessa documentazione segnala che il layer change 2015–2018 non è stato aggiornato in linea con lo status 2018 revisionato. I prodotti 2018+ appartengono al nuovo ciclo HRL/VLCC: risoluzione, produzione e reprocessing sono `changed`, non presumibilmente stabili. ([CLMS, technical summary](https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover?tab=technical_summary))

I dataset sono accessibili tramite i servizi CLMS/CDSE e ricadono nella politica Copernicus di accesso pieno, aperto e gratuito con attribuzione. Le opportunità sono `source_available_not_registered` per le nuove annualità, `registered_not_ingested` per DLT già configurato e `requires_H1C_policy` per confronti tra cicli. ([CLMS, datasets](https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover), [CLMS, data policy](https://land.copernicus.eu/en/data-policy))

### CORINE

CLMS conferma cinque status CLC: 1990, 2000, 2006, 2012 e 2018. Il prodotto ha 44 classi, MMU 25 ha e larghezza minima 100 m; è distribuito come raster 100 m e vettore GeoPackage/File Geodatabase in ETRS89-LAEA (EPSG:3035). I change layer 1990–2000, 2000–2006, 2006–2012 e 2012–2018 hanno MMU 5 ha. ([CLMS, technical summary](https://land.copernicus.eu/en/products/corine-land-cover?tab=technical_summary), [CLMS, datasets](https://land.copernicus.eu/en/products/corine-land-cover/?tab=datasets))

Non risulta uno status post-2018 nella pagina ufficiale corrente. La data nominale 1990 deriva da acquisizioni nazionali eterogenee 1985–1996; gli status storici possono essere rimpiazzati da versioni riviste. CLMS raccomanda i change layer per misurare transizioni, invece di sottrarre due status. ([CLMS, CLC 1990](https://land.copernicus.eu/en/products/corine-land-cover/clc-1990?tab=mapview), [CLMS FAQ](https://land.copernicus.eu/en/faq/products/corine-land-cover))

Le classi forestali CLC possono sostenere una serie di copertura/uso del suolo di lungo periodo, purché restino semanticamente distinte da inventario INFC, densità TCD, tipo FTY e foglia dominante DLT. Gap: `registered_not_ingested`, poi potenzialmente `ingested_not_delivered`; la modalità di confronto resta `requires_H1C_policy`.

## Dissesto / IdroGEO

Il catalogo IdroGEO corrente offre mosaici scaricabili della pericolosità da frana e idraulica: 2017 per entrambi i fenomeni, 2020 per alluvioni, 2020–2021 e 2024 per frane. I formati verificati sono Shapefile in ZIP e, per il 2024, un archivio ZIP contenente File Geodatabase; le licenze indicate sono CC BY-SA 4.0 per i mosaici e CC BY 4.0 per gli indicatori. ([IdroGEO, open data](https://beta.idrogeo.isprambiente.it/app/page/open-data))

| Edizione/asset | Reference year | Publication year | Level | Machine-readable/access | Method/version | Territorial reference | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Rapporto nazionale | 2015 | 2015 | Italia, regione, provincia, comune in tabelle/appendici | PDF/table only; `direct stable URL` | prima mosaicatura nazionale indicata dall'edizione; dettagli nel rapporto | confini dell'edizione, dataset riusabile non verificato | `OFFICIAL_MENTION_NO_DATASET` ([ISPRA](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/dissesto-idrogeologico-in-italia-pericolosita-e-indicatori-di-rischio-rapporto-2015)) |
| Mosaici hazard | 2017 | pubblicazione corrente dell'archivio, data originaria non stabilita | copertura nazionale geospaziale | Shapefile; ZIP archive; `manual download` | snapshot 2017 | geometrie di pericolosità, non aggregati amministrativi | `VERIFIED_DOWNLOAD` ([IdroGEO](https://beta.idrogeo.isprambiente.it/app/page/open-data)) |
| Rapporto nazionale | 2018 | 2018 | Italia, regione, provincia, comune in tabelle/appendici | PDF/table only; `direct stable URL` | edizione 2018 | confini dell'edizione, dataset riusabile non verificato | `OFFICIAL_MENTION_NO_DATASET` ([ISPRA](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/dissesto-idrogeologico-in-italia-pericolosita-e-indicatori-di-rischio-edizione-2018)) |
| Alluvioni | 2020 | edizione/report 2021 | geodata nazionale; indicatori per tutti i livelli | Shapefile; CSV; XLS/XLSX; API; `manual download` e `API-generated` | mosaico v5 | ISTAT 2020 per gli aggregati | `VERIFIED_DOWNLOAD` ([IdroGEO](https://beta.idrogeo.isprambiente.it/app/page/open-data), [ISPRA](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/dissesto-idrogeologico-in-italia-pericolosita-e-indicatori-di-rischio-edizione-2021)) |
| Frane | 2020–2021 | edizione/report 2021 | geodata nazionale | Shapefile; ZIP archive; `manual download` | mosaico v4 | non applicabile al raster/vettore hazard; aggregati da qualificare | `VERIFIED_DOWNLOAD` ([IdroGEO](https://beta.idrogeo.isprambiente.it/app/page/open-data)) |
| Frane | 2024 | 2024 | geodata nazionale; indicatori per tutti i livelli | ZIP archive; CSV; XLS/XLSX; API; `manual download` e `API-generated` | mosaico v5 | ISTAT 2024 per gli aggregati | `VERIFIED_DOWNLOAD` ([IdroGEO](https://beta.idrogeo.isprambiente.it/app/page/open-data), [ISPRA](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/dissesto-idrogeologico-in-italia-pericolosita-e-indicatori-di-rischio-edizione-2024)) |

La stessa pagina espone indicatori correnti per Italia, regioni, province e comuni come XLS/XLSX, CSV e API JSON: frane 2024, alluvioni 2020, con `-1` distinto da zero. Il rapporto 2024 usa limiti ISTAT 2024, mentre l'edizione alluvioni 2020 usa i limiti dell'anno corrispondente. ([IdroGEO, open data](https://beta.idrogeo.isprambiente.it/app/page/open-data), [ISPRA, rapporto 2024](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/dissesto-idrogeologico-in-italia-pericolosita-e-indicatori-di-rischio-edizione-2024))

Esistono rapporti ufficiali 2015, 2018, 2021 e 2024 con pericolosità e indicatori di rischio per popolazione, famiglie, edifici, imprese e beni culturali. Per le edizioni storiche non è stato verificato un archivio machine-readable completo equivalente all'export corrente: sono `OFFICIAL_MENTION_NO_DATASET`, non nuovi snapshot pronti all'ingest. ([ISPRA, 2015](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/dissesto-idrogeologico-in-italia-pericolosita-e-indicatori-di-rischio-rapporto-2015), [2018](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/dissesto-idrogeologico-in-italia-pericolosita-e-indicatori-di-rischio-edizione-2018), [2021](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/dissesto-idrogeologico-in-italia-pericolosita-e-indicatori-di-rischio-edizione-2021), [2024](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/dissesto-idrogeologico-in-italia-pericolosita-e-indicatori-di-rischio-edizione-2024))

I mosaici incorporano l'evoluzione dei PAI e dell'armonizzazione nazionale. Mostrare più snapshot può essere difendibile; interpretarli come occorrenze annuali o calcolare variazioni senza qualificare copertura, versione e territorio non lo è. Gap: `source_available_not_registered`, `machine_readable_source_not_found`, `methodology_evidence_missing` e `requires_H1C_policy`.

## Emissions

### National

NID 2026 e IIR 2026 coprono rispettivamente gas serra e inquinanti atmosferici dal 1990 al 2024 senza buchi annuali. Entrambi descrivono un processo di controllo e ricalcolo dell'intera serie per incorporare miglioramenti metodologici, nuove informazioni e correzioni. L'anno 1990 nella pubblicazione 2026 è quindi il valore ufficiale corrente ricostruito, non una copia immutata dell'edizione originaria. ([ISPRA, NID 2026](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/national-inventory-document-2026-italian-greenhouse-gas-inventory-1990-2024), [PDF NID](https://www.isprambiente.gov.it/files2026/pubblicazioni/rapporti/rpporto-428_26_nid2026_italy_stampa.pdf), [ISPRA, IIR 2026](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/italian-emission-inventory-1990-2024-informative-inventory-report-2026), [PDF IIR](https://www.isprambiente.gov.it/files2026/pubblicazioni/rapporti/iir_r426_2026.pdf))

Non c'è nuovo arco storico da acquisire: `no_gap`. H1C deve solo definire come rappresentare la versione della ricostruzione e come evitare confronti fra submission diverse senza evidenza.

### Provincial

La pagina e il workbook ufficiali confermano gli snapshot 1990, 1995, 2000, 2005, 2010, 2015, 2019 e 2023. La tabella `DB_ON_LINE_1` contiene codice/nome di regione, provincia e comune, identificativo e coordinate della griglia, SNAP, inquinante, unità e otto colonne annuali. Le righe provinciali non nulle contengono rispettivamente 95, 95, 103, 103, 110, 110, 107 e 107 codici distinti. ([ISPRA, landing](https://emissioni.sina.isprambiente.it/disaggregazione-provinciale/), [workbook](https://emissioni.sina.isprambiente.it/wp-content/uploads/2026/06/Disaggregazione_provinciale_inventario_2023_rev06_2026.xlsx))

| Periodo | Codici provincia distinti | Grid rows | SNAP | Pollutants | Units | Territorial evidence |
| --- | ---: | --- | --- | --- | --- | --- |
| 1990 | 95 | present | present | present | campo ufficiale `UNI_mis` per riga | struttura storica, exact geometry non trovata |
| 1995 | 95 | present | present | present | campo ufficiale `UNI_mis` per riga | struttura storica, exact geometry non trovata |
| 2000 | 103 | present | present | present | campo ufficiale `UNI_mis` per riga | struttura storica, exact geometry non trovata |
| 2005 | 103 | present | present | present | campo ufficiale `UNI_mis` per riga | confine ISTAT 01-01-2005 disponibile |
| 2010 | 110 | present | present | present | campo ufficiale `UNI_mis` per riga | confine ISTAT 01-01-2010; struttura sarda storica |
| 2015 | 110 | present | present | present | campo ufficiale `UNI_mis` per riga | confine ISTAT 01-01-2015; struttura sarda storica |
| 2019 | 107 | present | present | present | campo ufficiale `UNI_mis` per riga | configurazione 2019 dichiarata nel rapporto |
| 2023 | 107 | present | present | present | campo ufficiale `UNI_mis` per riga | stessa configurazione 2019 dichiarata nel rapporto |

La presenza per-periodo è `VERIFIED_DOWNLOAD` sul [workbook ufficiale](https://emissioni.sina.isprambiente.it/wp-content/uploads/2026/06/Disaggregazione_provinciale_inventario_2023_rev06_2026.xlsx); composizione e mutamenti provinciali sono descritti dal [rapporto ISPRA 2026](https://www.isprambiente.gov.it/files2026/pubblicazioni/rapporti/rapporto_prov_432_2026.pdf). “Present” significa che la dimensione compare nelle righe valorizzate di quel periodo, non che H1B abbia approvato ogni combinazione inquinante × SNAP come serie confrontabile. Le unità restano quelle della singola riga e non vengono normalizzate o generalizzate.

Il rapporto descrive la disaggregazione come top-down a partire dall'inventario nazionale e conserva la classificazione SNAP. Evidenzia la variazione del numero e della composizione delle province, incluse le strutture sarde, e tratta il 2023 con la stessa configurazione territoriale del 2019. Il foglio `modifiche` del workbook rev. 06/2026 documenta correzioni a coordinate storiche e a una classificazione SNAP: anche questa sorgente è revisionabile. ([ISPRA, metodologia](https://emissioni.sina.isprambiente.it/disaggregazione-provinciale-emissioni/), [rapporto 2026](https://www.isprambiente.gov.it/files2026/pubblicazioni/rapporti/rapporto_prov_432_2026.pdf), [workbook](https://emissioni.sina.isprambiente.it/wp-content/uploads/2026/06/Disaggregazione_provinciale_inventario_2023_rev06_2026.xlsx))

I confini ISTAT esatti rendono 2005, 2010 e 2015 candidati ad alta priorità. Per 1990, 1995 e 2000 non esiste un prodotto annuale esatto trovato; 1991 e 2001 vanno soltanto registrati come snapshot censuari vicini. Nessuna nota ufficiale verificata autorizza l'uso di quei confini al posto delle strutture sorgente. Gap: 2005/2010/2015 `registered_not_ingested`; 1990/1995/2000 `territory_geometry_missing`; tutti i nuovi periodi `requires_H1C_policy`. ([ISTAT, confini](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/), [ISPRA, rapporto 2026](https://www.isprambiente.gov.it/files2026/pubblicazioni/rapporti/rapporto_prov_432_2026.pdf))

### Grid

Le righe di griglia ufficiali esistono per tutti gli otto snapshot e usano celle EMEP da 0,1° × 0,1° in longitudine/latitudine. Il workbook riporta `G_EMEP`, `LATI` e `LONGI`; il rapporto specifica la convenzione del vertice inferiore sinistro e segnala che la prossima edizione prevista adotterà la convenzione CEIP del centro cella. Non è dichiarato un EPSG: resta `unknown`, senza inferenza. ([ISPRA, workbook](https://emissioni.sina.isprambiente.it/wp-content/uploads/2026/06/Disaggregazione_provinciale_inventario_2023_rev06_2026.xlsx), [rapporto 2026](https://www.isprambiente.gov.it/files2026/pubblicazioni/rapporti/rapporto_prov_432_2026.pdf))

Potenziale `HIGH`: offre una vista storica ufficiale non dipendente dalle variazioni amministrative, ma non sostituisce la lettura provinciale. La stabilità è verificata soltanto all'interno dell'edizione corrente; convenzione delle coordinate, rendering, aggregazioni e relazione con le province richiedono `new_ADR_needed` e decisione H1C.

## Candidate-period matrix

| Dataset | Periodo | Evidenza ufficiale | Stato H1A | Territorio / blocco | Gap |
| --- | --- | --- | --- | --- | --- |
| ISTAT boundaries | 1990 | nessun prodotto exact-year trovato; 1991 è vicino ma distinto ([ISTAT](https://www.istat.it/notizia/basi-territoriali-e-variabili-censuarie/)) | assente | exact-year mancante | `territory_geometry_missing` |
| ISTAT boundaries | 1991 | snapshot censuario 20-10-1991 ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) | assente | tutti i livelli; non sostituisce 1990/1995 | `registered_not_ingested` |
| ISTAT boundaries | 1995 | nessun prodotto exact-year trovato ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) | assente | exact-year mancante | `territory_geometry_missing` |
| ISTAT boundaries | 2000 | nessun prodotto exact-year trovato; 2001 è vicino ma distinto ([ISTAT](https://www.istat.it/notizia/basi-territoriali-e-variabili-censuarie/)) | assente | exact-year mancante | `territory_geometry_missing` |
| ISTAT boundaries | 2001 | snapshot censuario 21-10-2001 ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) | assente | tutti i livelli; non sostituisce 2000 | `registered_not_ingested` |
| ISTAT boundaries | 2005 | exact-year 01-01-2005 ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) | assente | candidato emissioni/acqua | `registered_not_ingested` |
| ISTAT boundaries | 2006 | exact-year 01-01-2006 ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) | materializzato | tutti i livelli | `no_gap` |
| ISTAT boundaries | 2010 | exact-year 01-01-2010 ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) | assente | candidato emissioni/acqua | `registered_not_ingested` |
| ISTAT boundaries | 2011 | snapshot censuario 09-10-2011 ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) | assente | data non 01-01; policy necessaria | `requires_H1C_policy` |
| ISTAT boundaries | 2012 | exact-year 01-01-2012 ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) | materializzato | tutti i livelli | `no_gap` |
| ISTAT boundaries | 2015 | exact-year 01-01-2015 ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) | materializzato | candidato emissioni già disponibile | `no_gap` |
| ISTAT boundaries | 2016–2020 | exact-year 01-01 annuale ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) | materializzato | tutti i livelli | `no_gap` |
| ISTAT boundaries | 2021 | exact 31-12-2021 ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) | materializzato | eccezione già governata | `no_gap` |
| ISTAT boundaries | 2022–2025 | exact-year annuale; 2022/2023 revisionati ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) | materializzato | preservare revisione/hash | `no_gap` |
| ISTAT boundaries | 2026 | exact-year 01-01-2026 ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) | non materializzato | tutti i livelli | `registered_not_ingested` |
| Emissions provincial/grid | 1990 | colonna e righe ufficiali verificate ([ISPRA](https://emissioni.sina.isprambiente.it/wp-content/uploads/2026/06/Disaggregazione_provinciale_inventario_2023_rev06_2026.xlsx)) | non ingested | 95 province; exact geometry mancante | `territory_geometry_missing` |
| Emissions provincial/grid | 1995 | colonna e righe ufficiali verificate ([ISPRA](https://emissioni.sina.isprambiente.it/wp-content/uploads/2026/06/Disaggregazione_provinciale_inventario_2023_rev06_2026.xlsx)) | non ingested | 95 province; exact geometry mancante | `territory_geometry_missing` |
| Emissions provincial/grid | 2000 | colonna e righe ufficiali verificate ([ISPRA](https://emissioni.sina.isprambiente.it/wp-content/uploads/2026/06/Disaggregazione_provinciale_inventario_2023_rev06_2026.xlsx)) | non ingested | 103 province; exact geometry mancante | `territory_geometry_missing` |
| Emissions provincial/grid | 2005 | colonna e righe ufficiali verificate ([ISPRA](https://emissioni.sina.isprambiente.it/wp-content/uploads/2026/06/Disaggregazione_provinciale_inventario_2023_rev06_2026.xlsx)) | non ingested | 103 province; confine ISTAT esatto disponibile | `registered_not_ingested` |
| Emissions provincial/grid | 2010 | colonna e righe ufficiali verificate ([ISPRA](https://emissioni.sina.isprambiente.it/wp-content/uploads/2026/06/Disaggregazione_provinciale_inventario_2023_rev06_2026.xlsx)) | non ingested | 110 province; confine esatto, incluse strutture sarde storiche | `registered_not_ingested` |
| Emissions provincial/grid | 2015 | colonna e righe ufficiali verificate ([ISPRA](https://emissioni.sina.isprambiente.it/wp-content/uploads/2026/06/Disaggregazione_provinciale_inventario_2023_rev06_2026.xlsx)) | non ingested | 110 province; confine esatto già materializzato | `registered_not_ingested` |
| Emissions provincial/grid | 2019 | colonna e righe ufficiali verificate ([ISPRA](https://emissioni.sina.isprambiente.it/wp-content/uploads/2026/06/Disaggregazione_provinciale_inventario_2023_rev06_2026.xlsx)) | pubblicato provincia | 107 province; grid non ingested | `registered_not_ingested` per grid |
| Emissions provincial/grid | 2023 | colonna e righe ufficiali verificate ([ISPRA](https://emissioni.sina.isprambiente.it/wp-content/uploads/2026/06/Disaggregazione_provinciale_inventario_2023_rev06_2026.xlsx)) | pubblicato provincia | 107 province; grid non ingested | `registered_not_ingested` per grid |
| INFC | 1985 | inventario/pubblicazione ufficiale ([CREA](https://www.crea.gov.it/it/web/foreste-e-legno/pubblicazioni-istituzionali-e-schede-tecniche?_com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_hL6jCbbk5XCg_cur=4&_com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_hL6jCbbk5XCg_delta=8&p_p_id=com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_hL6jCbbk5XCg&p_p_lifecycle=0&p_p_mode=view&p_p_state=normal&p_r_p_resetCur=false)) | assente | PDF, metodo da qualificare | `machine_readable_source_not_found` |
| INFC | 2005 | tabelle ufficiali e confronto 2005–2015 ([INFC](https://www.inventarioforestale.org/it/statistiche-infc/)) | assente | Italia/regione; download richiede sessione | `source_available_not_registered` |
| INFC | 2015 | statistiche ufficiali ([INFC](https://www.inventarioforestale.org/it/statistiche_infc/)) | pubblicato | Italia/regione | `no_gap` |
| IFNI continuo | 2025– | programma ufficiale in corso, nessun risultato statistico trovato ([CREA](https://creafuturo.crea.gov.it/14618/)) | assente | non ancora dataset | `official_history_not_found` |
| CORINE status | 1990 | status ufficiale; acquisizione 1985–1996 ([CLMS](https://land.copernicus.eu/en/products/corine-land-cover/clc-1990?tab=mapview)) | registrato, non ingested | data nominale eterogenea | `registered_not_ingested` |
| CORINE status | 2000 | status ufficiale ([CLMS](https://land.copernicus.eu/en/products/corine-land-cover/?tab=datasets)) | registrato, non ingested | change 1990–2000 disponibile | `registered_not_ingested` |
| CORINE status | 2006 | status ufficiale ([CLMS](https://land.copernicus.eu/en/products/corine-land-cover/?tab=datasets)) | registrato, non ingested | change 2000–2006 disponibile | `registered_not_ingested` |
| CORINE status | 2012 | status ufficiale ([CLMS](https://land.copernicus.eu/en/products/corine-land-cover/?tab=datasets)) | registrato, non ingested | change 2006–2012 disponibile | `registered_not_ingested` |
| CORINE status | 2018 | ultimo status ufficiale corrente ([CLMS](https://land.copernicus.eu/en/products/corine-land-cover/?tab=datasets)) | registrato, non ingested | change 2012–2018 disponibile | `registered_not_ingested` |
| IdroGEO | 2015 | rapporto nazionale e indicatori pubblicati ([ISPRA](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/dissesto-idrogeologico-in-italia-pericolosita-e-indicatori-di-rischio-rapporto-2015)) | assente | dataset aggregato non verificato | `machine_readable_source_not_found` |
| IdroGEO | 2017 | mosaici hazard frane/alluvioni scaricabili ([IdroGEO](https://beta.idrogeo.isprambiente.it/app/page/open-data)) | assente | geodata, non aggregati rischio | `source_available_not_registered` |
| IdroGEO | 2018 | rapporto nazionale ([ISPRA](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/dissesto-idrogeologico-in-italia-pericolosita-e-indicatori-di-rischio-edizione-2018)) | assente | dataset aggregato non verificato | `machine_readable_source_not_found` |
| IdroGEO | 2020 | mosaico alluvioni e indicatori ([IdroGEO](https://beta.idrogeo.isprambiente.it/app/page/open-data)) | indicatori pubblicati | snapshot, non serie annuale | `no_gap` |
| IdroGEO | 2020–2021 | mosaico frane v4 scaricabile ([IdroGEO](https://beta.idrogeo.isprambiente.it/app/page/open-data)) | assente | geodata; comparabilità da decidere | `source_available_not_registered` |
| IdroGEO | 2021 | rapporto nazionale ([ISPRA](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/dissesto-idrogeologico-in-italia-pericolosita-e-indicatori-di-rischio-edizione-2021)) | assente | dataset aggregato non verificato | `machine_readable_source_not_found` |
| IdroGEO | 2024 | mosaico frane v5 e indicatori ([IdroGEO](https://beta.idrogeo.isprambiente.it/app/page/open-data)) | indicatori pubblicati | ISTAT 2024 | `no_gap` |

## Territory availability matrix

| Period/year | Official ISTAT geometry available | Levels | Exact reference date | Suitable candidate for project | Caveats |
| ----------- | --------------------------------- | ------ | -------------------- | ------------------------------ | ------- |
| 1990 | no; snapshot vicino 1991 | regione, provincia, comune nel 1991 | 20-10-1991, non 1990 | no per exact-year | nessun nearest-year fallback ([ISTAT](https://www.istat.it/notizia/basi-territoriali-e-variabili-censuarie/)) |
| 1991 | sì, censimento | regione, provincia, comune | 20-10-1991 | sì per osservazioni con tale data | non rappresenta automaticamente 1990/1995 ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) |
| 1995 | no | — | — | no | registro SITUAS documenta variazioni ma non crea geometria ([SITUAS](https://situas.istat.it/web/)) |
| 2000 | no; snapshot vicino 2001 | regione, provincia, comune nel 2001 | 21-10-2001, non 2000 | no per exact-year | nessun nearest-year fallback ([ISTAT](https://www.istat.it/notizia/basi-territoriali-e-variabili-censuarie/)) |
| 2001 | sì, censimento | regione, provincia, comune | 21-10-2001 | sì per osservazioni con tale data | non rappresenta automaticamente 2000 ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) |
| 2002–2004 | sì, annuale | regione, provincia, comune | 01-01 di ogni anno | sì, dopo registrazione | non materializzato oggi ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) |
| 2005 | sì | regione, provincia, comune | 01-01-2005 | sì; emissioni e acqua | non materializzato oggi ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) |
| 2006 | sì | regione, provincia, comune | 01-01-2006 | sì | già materializzato ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) |
| 2007–2009 | sì, annuale | regione, provincia, comune | 01-01 di ogni anno | sì; acqua | non materializzato oggi ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) |
| 2010 | sì | regione, provincia, comune | 01-01-2010 | sì; emissioni e acqua | verificare identità contro le 110 province sorgente ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/), [ISPRA](https://www.isprambiente.gov.it/files2026/pubblicazioni/rapporti/rapporto_prov_432_2026.pdf)) |
| 2011 | sì, censimento | regione, provincia, comune | 09-10-2011 | candidato condizionato | non è uno snapshot al 01-01; H1C deve decidere ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) |
| 2012 | sì | regione, provincia, comune | 01-01-2012 | sì | già materializzato ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) |
| 2013–2014 | sì, annuale | regione, provincia, comune | 01-01 di ogni anno | sì; acqua | non materializzato oggi ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) |
| 2015 | sì | regione, provincia, comune | 01-01-2015 | sì; emissioni/acqua/INFC | già materializzato; verificare match 110 province emissioni ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/), [ISPRA](https://www.isprambiente.gov.it/files2026/pubblicazioni/rapporti/rapporto_prov_432_2026.pdf)) |
| 2016–2020 | sì, annuale | regione, provincia, comune | 01-01 di ogni anno | sì | già materializzato ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) |
| 2021 | sì | regione, provincia/UTS, comune | 31-12-2021 | sì | data e gerarchia speciali già governate ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) |
| 2022–2023 | sì, annuale | regione, provincia, comune | 01-01 | sì | file sostituiti il 05-04-2024; fissare SHA-256 ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) |
| 2024–2025 | sì, annuale | regione, provincia, comune | 01-01 | sì | già materializzato ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) |
| 2026 | sì | regione, provincia, comune | 01-01-2026 | sì, quando richiesto | non materializzato oggi ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) |

## Comparability evidence

La tabella raccoglie evidenza, non abilita confronti. `stable` significa soltanto che la documentazione verificata supporta stabilità nella dimensione indicata e nel perimetro specifico.

| Dataset family | Metric definition | Unit | Method/version | Territory geometry | Revision/reprocessing | Classification | Period duration | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ISTAT boundaries | not_applicable | not_applicable | changed | changed | changed | changed | not_applicable | gerarchie annuali e revisioni ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)) |
| Soil indicators | changed | unknown | changed | changed | changed | changed | changed | serie aggiornate e geografia 2024 nel prodotto 2006 ([ISPRA](https://groupware.sinanet.isprambiente.it/uso-copertura-e-consumo-di-suolo/library/consumo-di-suolo/indicatori/consumo_2006/poligoni/consumo_reg06/download/en/1/Consumo_REG06.zip)) |
| BIGBANG within v10 | stable | stable | stable | not_applicable per raster | stable dentro v10 | stable | stable | unica rielaborazione 1951–2025 ([ISPRA](https://www.isprambiente.gov.it/pre_meteo/idro/BIGBANG_ISPRA.html)) |
| BIGBANG across versions | stable | stable | changed | not_applicable per raster | changed | stable | stable | intera serie ricalcolata ([ISPRA](https://www.isprambiente.gov.it/pre_meteo/idro/BIGBANG_ISPRA.html)) |
| INFC 2005–2015 | unknown, salvo metriche esplicitamente confrontate | unknown | changed | changed | unknown | changed | changed | confronto ufficiale limitato e cicli diversi ([INFC](https://www.inventarioforestale.org/it/superficie-e-composizione-area-and-composition/)) |
| HRL TCD/DLT/FTY | changed | stable | changed | not_applicable per raster; changed per aggregati | changed | changed | stable per status | 20 m/10 m e cicli distinti ([CLMS](https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover?tab=technical_summary)) |
| HRL change/TCPC | changed | stable | changed | changed per aggregati | changed | changed | changed | tre intervalli e revisione 2018 non propagata ([CLMS](https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover?tab=technical_summary)) |
| CORINE status | stable nel nomenclatore di base | stable | changed | not_applicable per raster; changed per aggregati | changed | stable con revisioni | changed | MMU e acquisizioni nominali ([CLMS](https://land.copernicus.eu/en/products/corine-land-cover?tab=technical_summary)) |
| CORINE change | stable | stable | changed | not_applicable per raster | changed | stable | changed | intervalli diseguali, MMU 5 ha ([CLMS](https://land.copernicus.eu/en/faq/products/corine-land-cover)) |
| IdroGEO hazard/risk | changed | unknown | changed | changed | changed | changed | not_applicable | versioni PAI/mosaico e basi esposte ([IdroGEO](https://beta.idrogeo.isprambiente.it/app/page/open-data)) |
| GHG national within NID 2026 | stable | stable | stable nella submission | not_applicable | stable nella submission | stable | stable | serie coerente ricalcolata 1990–2024 ([NID](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/national-inventory-document-2026-italian-greenhouse-gas-inventory-1990-2024)) |
| NFR national within IIR 2026 | stable | stable | stable nella submission | not_applicable | stable nella submission | stable | stable | serie coerente ricalcolata 1990–2024 ([IIR](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/italian-emission-inventory-1990-2024-informative-inventory-report-2026)) |
| National inventories across submissions | unknown | stable | changed | not_applicable | changed | changed | stable | ricalcolo annuale della storia ([NID](https://www.isprambiente.gov.it/files2026/pubblicazioni/rapporti/rpporto-428_26_nid2026_italy_stampa.pdf), [IIR](https://www.isprambiente.gov.it/files2026/pubblicazioni/rapporti/iir_r426_2026.pdf)) |
| Emissions provincial within workbook 2026 | stable | stable per riga, non unica | stable nell'edizione | changed | changed | stable SNAP salvo correzioni | not_applicable, snapshot | otto colonne e revision log ([workbook](https://emissioni.sina.isprambiente.it/wp-content/uploads/2026/06/Disaggregazione_provinciale_inventario_2023_rev06_2026.xlsx)) |
| Emissions grid within workbook 2026 | stable | stable per riga | stable nell'edizione | stable come celle, non come convenzione futura | changed | stable SNAP salvo correzioni | not_applicable, snapshot | griglia 0,1° e cambio convenzione annunciato ([ISPRA](https://www.isprambiente.gov.it/files2026/pubblicazioni/rapporti/rapporto_prov_432_2026.pdf)) |

## Newly discovered opportunities

1. **Emissioni provinciali 2005, 2010, 2015 — HIGH.** Valori e geometrie exact-year ufficiali esistono; occorre verificare il join completo di codici/nomi e la semantica della struttura sarda. ([ISPRA](https://emissioni.sina.isprambiente.it/disaggregazione-provinciale/), [ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/))
2. **Griglia emissioni 1990–2023 — HIGH.** Offre otto snapshot ufficiali senza dipendere dai confini amministrativi; necessita nuovo contratto/ADR e non sostituisce le province. ([ISPRA](https://www.isprambiente.gov.it/files2026/pubblicazioni/rapporti/rapporto_prov_432_2026.pdf))
3. **Confini ISTAT annuali 2002–2014 e 2026 non materializzati — HIGH.** Sono già dichiarati dal source contract H1A e possono ampliare in modo fail-closed BIGBANG provinciale e altri derivati exact-year. ([ISTAT](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/))
4. **CORINE status/change 1990–2018 — HIGH.** È la profondità più lunga per copertura forestale del suolo, semanticamente separata dagli inventari e dagli HRL. ([CLMS](https://land.copernicus.eu/en/products/corine-land-cover?tab=technical_summary))
5. **HRL TCD/DLT 2012, 2015 e annualità 2019/2020/2022 — HIGH.** Nuova profondità e densità temporale, con rottura 20 m/10 m da rendere esplicita. ([CLMS](https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover?tab=technical_summary))
6. **INFC 2005 — HIGH condizionato all'accesso.** Le tabelle e alcune comparazioni ufficiali esistono, ma il download operativo richiede sessione e le metriche vanno abbinate una per una. ([INFC](https://www.inventarioforestale.org/it/statistiche-infc/), [INFC confronto](https://www.inventarioforestale.org/it/superficie-e-composizione-area-and-composition/))
7. **IdroGEO mosaici 2017 e frane 2020–2021 — MEDIUM.** Aggiungono snapshot geospaziali ufficiali, non una serie annuale di rischio. ([IdroGEO](https://beta.idrogeo.isprambiente.it/app/page/open-data))
8. **Stock storici del consumo di suolo — MEDIUM condizionato.** L'archivio offre artefatti storici, ma almeno il 2006 è armonizzato a geografia 2024 e deve dimostrare contenuto aggiuntivo rispetto al workbook corrente. ([ISPRA](https://groupware.sinanet.isprambiente.it/uso-copertura-e-consumo-di-suolo/library/consumo-di-suolo/indicatori))

| Finding | Gap classification | Prossimo confine corretto |
| --- | --- | --- |
| Confini ISTAT annuali non materializzati | `registered_not_ingested` | H1C decide priorità e date ammissibili |
| Emissioni provinciali 2005/2010/2015 | `registered_not_ingested` | H1C verifica identity join exact-year |
| Emissioni 1990/1995/2000 | `territory_geometry_missing` | nessun ingest amministrativo senza nuova evidenza/policy |
| Griglia emissioni | `registered_not_ingested`; `requires_H1C_policy` | nuovo ADR prima dell'implementazione |
| HRL nuovi periodi | `source_available_not_registered` | qualificare ciclo/versione e geometria |
| DLT registrato | `registered_not_ingested` | separare accesso da processing statistico |
| CORINE | `registered_not_ingested` | acquisire status e change come famiglie distinte |
| INFC 2005 | `source_available_not_registered`; access blocker | stabilire download riproducibile e mapping metriche |
| INFC 1985 | `machine_readable_source_not_found` | non trascrivere PDF senza decisione/provenienza |
| IdroGEO mosaici storici | `source_available_not_registered` | distinguere hazard geometry da risk aggregates |
| Rapporti Dissesto storici | `machine_readable_source_not_found` | continuare ricerca archivio ufficiale, non estrazione implicita |
| BIGBANG 1951–2001 provinciale | `territory_geometry_missing` | restare fail-closed |
| Confronti tra versioni/metodi/geografie | `requires_H1C_policy` | ADR cross-domain |

## Sources that did not yield usable historical data

- Le stime ISPRA di consumo di suolo anteriori al 2006 sono documentate in rapporti, ma non è stata trovata una sorgente machine-readable omogenea con contratto territoriale e metodologico riusabile: `OFFICIAL_MENTION_NO_DATASET`. ([ISPRA 2015](https://www.isprambiente.gov.it/files/pubblicazioni/rapporti/Rapporto_218_15.pdf))
- L'inventario forestale 1985 è documentato in pubblicazioni CREA, ma non è stato verificato un download tabellare machine-readable: `OFFICIAL_MENTION_NO_DATASET`. ([CREA](https://www.crea.gov.it/it/web/foreste-e-legno/pubblicazioni-istituzionali-e-schede-tecniche?_com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_hL6jCbbk5XCg_cur=4&_com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_hL6jCbbk5XCg_delta=8&p_p_id=com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_hL6jCbbk5XCg&p_p_lifecycle=0&p_p_mode=view&p_p_state=normal&p_r_p_resetCur=false))
- Il download delle statistiche INFC 2005 non è riproducibile senza sessione SIAN: sorgente ufficiale nota, access blocker `requires session`, non `VERIFIED_DOWNLOAD`. ([INFC](https://www.inventarioforestale.org/it/statistiche-infc/))
- Il nuovo IFNI continuo non espone ancora risultati statistici riusabili trovati in H1B: `OFFICIAL_MENTION_NO_DATASET`. ([IFNI](https://ifni.crea.gov.it/))
- I rapporti Dissesto 2015/2018/2021 esistono, ma non è stato trovato un archivio completo dei corrispondenti indicatori territoriali machine-readable: `OFFICIAL_MENTION_NO_DATASET`. ([ISPRA 2015](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/dissesto-idrogeologico-in-italia-pericolosita-e-indicatori-di-rischio-rapporto-2015), [2018](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/dissesto-idrogeologico-in-italia-pericolosita-e-indicatori-di-rischio-edizione-2018), [2021](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/dissesto-idrogeologico-in-italia-pericolosita-e-indicatori-di-rischio-edizione-2021))
- Nessun confine ISTAT exact-year è stato trovato per 1990, 1995 o 2000. I prodotti censuari 1991 e 2001 restano evidenza vicina, non sostitutiva. ([ISTAT](https://www.istat.it/notizia/basi-territoriali-e-variabili-censuarie/))
- Nessuna versione BIGBANG ufficiale verificata estende l'arco prima del 1951; cercare “più anni” in versioni precedenti non aggiunge profondità. ([ISPRA](https://www.isprambiente.gov.it/pre_meteo/idro/BIGBANG_ISPRA.html))
- Nessuno status CORINE post-2018 è elencato nel catalogo ufficiale corrente. ([CLMS](https://land.copernicus.eu/en/products/corine-land-cover/?tab=datasets))

## H1C decision queue

| Priorità | Decision | Evidence available | Evidence missing | Affected domains | Affected periods | Risk if guessed |
| --- | --- | --- | --- | --- | --- | --- |
| P0 | Un confine censuario può rappresentare uno snapshot emissioni non censuario? | snapshot ISTAT 1991/2001; strutture ISPRA 95/103 province | equivalenza ufficiale o crosswalk per 1990/1995/2000 | Emissioni | 1990, 1995, 2000 | attribuire valori alla provincia sbagliata |
| P0 | Qual è il contratto cross-domain per source geography, exact-year, geografia armonizzata e series break? | confini annuali, SITUAS, suolo 2006 su geografia 2024, policy BIGBANG esistente | regola condivisa e rappresentazione delivery/UI | tutti | tutti | confronto territorialmente falso |
| P0 | Quando display, serie, delta, trend e ranking sono autorizzati separatamente? | matrice di comparabilità H1B e capability model H1A | soglie di evidenza formali per capacità | tutti | tutti | comunicare causalità o variazioni non difendibili |
| P1 | Le righe emissioni 2005/2010/2015 fanno join uno-a-uno ai confini ISTAT esatti? | workbook, conteggi 103/110/110, confini exact-year | audit completo codici/nomi, inclusa Sardegna | Emissioni | 2005, 2010, 2015 | geometrie senza valore o valori mal assegnati |
| P1 | La griglia emissioni va esposta come famiglia ufficiale autonoma? | otto snapshot, celle 0,1°, coordinate nel workbook | CRS formale, convenzione futura, schema delivery/UI, policy aggregazioni | Emissioni | 1990–2023 sparse | rendering spostato o equivalenza impropria con province |
| P1 | Come versionare gli inventari nazionali ricalcolati? | NID/IIR dichiarano revisione dell'intera storia | identificatore e messaggio prodotto tra submission | Emissioni | 1990–2024 | confrontare revisioni come cambi reali |
| P1 | Quali indicatori INFC 2005/2015 sono davvero confrontabili? | tabella ufficiale di variazione per alcune metriche | accesso riproducibile alle tabelle e mapping dizionario completo | Foreste | 2005, 2015 | fondere definizioni o campioni diversi |
| P1 | Come separare cicli HRL 2012/15 e 2018+? | risoluzioni e cicli ufficiali documentati | product-version pinning e test per metrica | Foreste | 2012–2023 | trend dominato dal metodo |
| P1 | Per CORINE, quali capacità usano status e quali change layer? | status, change, MMU e FAQ ufficiali | contratto metriche e aggregazione forestale | Foreste | 1990–2018 | delta ottenuto sottraendo layer incompatibili |
| P1 | Quale data territoriale applicare ai periodi BIGBANG annuali con confine censuario? | raster annuale; confini 2002–2026; 2011 al 09-10 | regola per il 2011 e verifica soglia >100 km² | Acqua | 2002–2014 non pubblicati | violare exact-year o inventare intervallo |
| P2 | Gli stock storici suolo aggiungono informazione al workbook 2025? | archivi annuali e lineage 2006→geografia 2024 | dizionario completo e confronto col workbook grande | Suolo | 2006–2023 | ingest duplicato o falsa geografia storica |
| P2 | Gli snapshot hazard IdroGEO possono formare una serie visuale senza delta? | geodata 2017/2020-21/2024 e rapporti | matrice versione/copertura/territorio per layer | Dissesto | 2017–2024 | interpretare aggiornamenti PAI come cambi ambientali |
| P2 | Come trattare i report storici senza dataset? | rapporti ufficiali esistenti | artifact machine-readable e licenza/lineage per tabelle | Suolo, Foreste, Dissesto | vari | trascrizione non riproducibile o selettiva |

### ADR impact assessment

| ADR | Candidate action | Exact reason |
| --- | --- | --- |
| ADR 0002 — territory history | `no_change` | l'evidenza ISTAT rafforza identità/versioni datate e divieto di join implicito; SITUAS non è un crosswalk automatico |
| ADR 0007 — analytics and comparisons | `clarification_candidate` | deve distinguere serie visualizzabile da delta/trend quando metodo, classificazione o geografia cambiano |
| ADR 0009 — temporal UI comparisons | `clarification_candidate` | va resa esplicita la precedenza del gate di evidenza/capacità prima del calcolo client |
| ADR 0015 — BIGBANG historical territory policy | `extension_candidate` | la policy fail-closed resta valida; l'inventario anni ammissibili può includere nuovi exact-year ISTAT 2002–2014 dopo H1C |
| ADR 0020 — ISTAT 2021 hierarchy | `no_change` | la fonte ufficiale conferma l'eccezione 31-12-2021; nessuna nuova semantica 2021 |
| ADR 0022 — capability-driven explorer model | `clarification_candidate` | occorre codificare l'evidenza minima distinta per display, serie, confronto e ranking attraverso i domini |
| ADR 0023 — water explorer adapter | `extension_candidate` | può accogliere ulteriori periodi provinciali exact-year senza cambiare la separazione ufficiale/derivato |
| ADR 0024 — emissions provincial explorer adapter | `extension_candidate` | 2005/2010/2015 possono estendere la slice amministrativa dopo verifica del join; 1990/95/2000 restano bloccati |
| Nuovo ADR cross-domain storico | `new_ADR_needed` | serve una decisione comune su profondità storica, source geography, series breaks, revisioni, visualizzazione e comparabilità |
| Nuovo ADR emissioni grid | `new_ADR_needed` | griglia ufficiale, CRS/convenzione, schema delivery, capacità e relazione con le province sono fuori da ADR 0024 |

H1B non propone `supersession_candidate` per alcun ADR: nessuna evidenza esterna invalida le decisioni correnti; emergono chiarimenti ed estensioni circoscritte.

### Official source index

**ISTAT**

- [Confini delle unità amministrative a fini statistici](https://www.istat.it/notizia/confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/)
- [Basi territoriali e variabili censuarie](https://www.istat.it/notizia/basi-territoriali-e-variabili-censuarie/)
- [Confini statistico-amministrativi: analisi storica](https://www.istat.it/notizia/confini-statistico-amministrativi-analisi-storica/)
- [Codici territoriali e SITUAS](https://www.istat.it/classificazione/codici-dei-comuni-delle-province-e-delle-regioni/)
- [SITUAS](https://situas.istat.it/web/)
- [Note legali e licenza](https://www.istat.it/note-legali/)

**ISPRA/SINA — suolo e acqua**

- [Dati sul consumo di suolo](https://www.isprambiente.gov.it/it/attivita/suolo-e-territorio/suolo/il-consumo-di-suolo/i-dati-sul-consumo-di-suolo)
- [Archivio cartografie consumo di suolo](https://groupware.sinanet.isprambiente.it/uso-copertura-e-consumo-di-suolo/library/consumo-di-suolo)
- [Archivio indicatori consumo di suolo](https://groupware.sinanet.isprambiente.it/uso-copertura-e-consumo-di-suolo/library/consumo-di-suolo/indicatori)
- [BIGBANG 10.0](https://www.isprambiente.gov.it/pre_meteo/idro/BIGBANG_ISPRA.html)
- [BIGBANG grid archive](https://groupware.sinanet.isprambiente.it/bigbang-data/library/bigbang100/ascii_grid/)
- [BIGBANG tables archive](https://groupware.sinanet.isprambiente.it/bigbang-data/library/bigbang100/excel_tables/)

**CUFAA/CREA — foreste**

- [Inventario forestale nazionale](https://www.inventarioforestale.org/it/)
- [Prodotti e servizi INFC](https://www.inventarioforestale.org/it/prodotti-e-servizi/)
- [Statistiche INFC 2005](https://www.inventarioforestale.org/it/statistiche-infc/)
- [Statistiche INFC 2015](https://www.inventarioforestale.org/it/statistiche_infc/)
- [Superficie e composizione 2005–2015](https://www.inventarioforestale.org/it/superficie-e-composizione-area-and-composition/)
- [Nuovo IFNI](https://ifni.crea.gov.it/)

**Copernicus Land Monitoring Service**

- [High Resolution Layer Forests and Tree Cover](https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover)
- [HRL technical summary](https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover?tab=technical_summary)
- [CORINE Land Cover technical summary](https://land.copernicus.eu/en/products/corine-land-cover?tab=technical_summary)
- [CORINE datasets](https://land.copernicus.eu/en/products/corine-land-cover/?tab=datasets)
- [CORINE FAQ](https://land.copernicus.eu/en/faq/products/corine-land-cover)
- [Copernicus data policy](https://land.copernicus.eu/en/data-policy)

**ISPRA/IdroGEO — dissesto**

- [IdroGEO open data](https://beta.idrogeo.isprambiente.it/app/page/open-data)
- [Dissesto idrogeologico](https://www.isprambiente.gov.it/it/attivita/suolo-e-territorio/dissesto-idrogeologico)
- [Rapporto 2015](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/dissesto-idrogeologico-in-italia-pericolosita-e-indicatori-di-rischio-rapporto-2015)
- [Rapporto 2018](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/dissesto-idrogeologico-in-italia-pericolosita-e-indicatori-di-rischio-edizione-2018)
- [Rapporto 2021](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/dissesto-idrogeologico-in-italia-pericolosita-e-indicatori-di-rischio-edizione-2021)
- [Rapporto 2024](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/dissesto-idrogeologico-in-italia-pericolosita-e-indicatori-di-rischio-edizione-2024)

**ISPRA/SINA — emissioni**

- [NID 2026, GHG 1990–2024](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/national-inventory-document-2026-italian-greenhouse-gas-inventory-1990-2024)
- [IIR 2026, NFR 1990–2024](https://www.isprambiente.gov.it/it/pubblicazioni/rapporti/italian-emission-inventory-1990-2024-informative-inventory-report-2026)
- [Disaggregazione provinciale](https://emissioni.sina.isprambiente.it/disaggregazione-provinciale/)
- [Metodologia della disaggregazione](https://emissioni.sina.isprambiente.it/disaggregazione-provinciale-emissioni/)
- [Workbook provinciale 2023 rev. 06/2026](https://emissioni.sina.isprambiente.it/wp-content/uploads/2026/06/Disaggregazione_provinciale_inventario_2023_rev06_2026.xlsx)
- [Rapporto provinciale 2026](https://www.isprambiente.gov.it/files2026/pubblicazioni/rapporti/rapporto_prov_432_2026.pdf)

H1B si ferma alla ricerca e alla coda decisionale. Non autorizza H1C né alcuna modifica operativa.
