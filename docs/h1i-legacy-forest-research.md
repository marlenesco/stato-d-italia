# H1I Legacy Forest Research

## Decision

Evidenze verificate l'11 settembre 2026. H1I-A chiude la ricerca per implementare TCD 2012/2015 e FTY 2012/2015 come asset legacy distinti. Per FTY si propone l'aggregato ufficiale a 100 m della generazione nativa a 20 m: una scelta di prodotto da accettare in H1I-B, non un ricampionamento locale. DLT resta differito e disabilitato: non emerge un requisito di prodotto aggiuntivo che ne giustifichi l'attivazione.

`READY_FOR_H1I_IMPLEMENTATION` indica un contratto documentato sufficiente a costruire l'adapter, non un download autenticato collaudato né dati materializzati. Nessun codice, configurazione o dato cambia in H1I-A.

## Evidence matrix

Le schede CLMS e i relativi JSON pubblici confermano tutti i sei prodotti. Gli anni sono anni di riferimento: le finestre di osservazione sono 2011–2013 e 2014–2016, non misure annuali continue.

| Candidato | Stato | Risoluzione nativa → input proposto | Evidenza ufficiale machine-readable |
| --- | --- | --- | --- |
| TCD 2012 | READY_FOR_H1I_IMPLEMENTATION | 20 m → 20 m | [CLMS JSON TCD 2012](https://land.copernicus.eu/api/en/products/high-resolution-layer-forests-and-tree-cover/tree-cover-density-2012) |
| TCD 2015 | READY_FOR_H1I_IMPLEMENTATION | 20 m → 20 m | [CLMS JSON TCD 2015](https://land.copernicus.eu/api/en/products/high-resolution-layer-forests-and-tree-cover/tree-cover-density-2015) |
| FTY 2012 | READY_FOR_H1I_IMPLEMENTATION | 20 m → aggregato ufficiale 100 m | [CLMS JSON FTY 2012](https://land.copernicus.eu/api/en/products/high-resolution-layer-forests-and-tree-cover/forest-type-2012) |
| FTY 2015 | READY_FOR_H1I_IMPLEMENTATION | 20 m → aggregato ufficiale 100 m | [CLMS JSON FTY 2015](https://land.copernicus.eu/api/en/products/high-resolution-layer-forests-and-tree-cover/forest-type-2015) |
| DLT 2012 | VERIFIED_BUT_DEFER | 20 m → nessun processing | [CLMS JSON DLT 2012](https://land.copernicus.eu/api/en/products/high-resolution-layer-forests-and-tree-cover/dominant-leaf-type-2012) |
| DLT 2015 | VERIFIED_BUT_DEFER | 20 m → nessun processing | [CLMS JSON DLT 2015](https://land.copernicus.eu/api/en/products/high-resolution-layer-forests-and-tree-cover/dominant-leaf-type-2015) |

## Access contract

Route scelta: download preconfezionato CLMS, GeoTIFF distribuito in ZIP, mosaico europeo EPSG:3035. I seguenti valori sono letti da `UID` e `downloadable_files.items` dei JSON sopra. `DatasetID` è un UID del portale CLMS; `FileID` è l'`@id` della voce scaricabile. Non sono collection ID CDSE/BYOC.

| Prodotto/input | DatasetID | FileID | Nome esatto nel campo `file` |
| --- | --- | --- | --- |
| TCD 2012 / 20 m | `b903be8a861d48d9af41266ce63cc287` | `266be23f-29a1-41f8-899d-a57c35d572fc` | `TCD_2012_020m_eu_03035_d03_Full` |
| TCD 2015 / 20 m | `860eee4b9af64f6283e8097f533456f9` | `245b8a61-e053-4509-b7c6-b79294d93576` | `TCD_2015_020m_eu_03035_d05_Full` |
| FTY 2012 / 100 m | `6606864bf28345438b7fc091ddb0a445` | `b29631a1-ae8c-42f9-8206-f10bb752ee52` | `FTY_2012_100m_eu_03035_d02_Full` |
| FTY 2015 / 100 m | `c53f82d466354da09de7c7e4ca44b030` | `d09e3605-92d8-4e6a-a401-220e2e4581e9` | `FTY_2015_100m_eu_03035_d02_Full` |
| DLT 2012 / 20 m | `cfa1c94c786d4332a11f58ed59d5e204` | `8ac9a4d4-8998-40d9-b0ec-a7ec71f150b5` | `DLT_2012_020m_eu_03035_d03_Full` |
| DLT 2015 / 20 m | `a07881fb9f624b72ae08eb4dbc4bfc7c` | `92e3bc0c-254f-46ea-bade-e054bc34c0de` | `DLT_2015_020m_eu_03035_d04_Full` |

Il nome riportato non certifica il nome del TIFF interno allo ZIP. Non costruire URL dal percorso interno del server presente nei metadati.

L'[API download ufficiale CLMS](https://eea.github.io/clms-api-docs/download.html) documenta:

1. POST `https://land.copernicus.eu/api/@datarequest_post` con `{"Datasets":[{"DatasetID":"<UID>","FileID":"<FileID>"}]}`.
2. Poll autenticato GET `/api/@datarequest_status_get?TaskID=<id>`; usare `DownloadURL` restituito a completamento.
3. Conservare identificatori, versione, metadati e checksum dei byte acquisiti; un cambio di versione richiede rivalidazione. L'URL temporaneo non è l'identità del prodotto.

L'[autenticazione CLMS](https://eea.github.io/clms-api-docs/authentication.html) richiede provisioning iniziale di una service key tramite account EU Login. In seguito firma JWT, scambio al `token_uri` e rinnovo del bearer sono automatizzabili senza sessione browser. Questa ricerca ha verificato GET pubblici e documentazione; non ha creato chiavi, inviato richieste di download o scaricato raster.

La [tabella CDSE CLMS](https://documentation.dataspace.copernicus.eu/Data/CopernicusServices/CLMS.html) documenta le collezioni Forest moderne dal 2018. Identificatori OData/BYOC e bande Process API per questi sei legacy: **UNRESOLVED**, non necessari alla route CLMS scelta. Nessun ID moderno è riutilizzabile per presunzione.

## Series break contract

Famiglia proposta: `copernicus_hrl_forest_legacy_2012_2015`, distinta da HR-VLCC moderno. La [specifica CLMS 2012/2015](https://land.copernicus.eu/en/technical-library/hrl-forest-2012-2015/@@download/file) descrive la generazione legacy e il ritrattamento del 2012: fissare la versione effettiva, non solo l'anno nominale.

Geometria obbligatoria: ISTAT esatta 2012 per il riferimento 2012, ISTAT esatta 2015 per il riferimento 2015. Le finestre di osservazione non autorizzano altre geometrie. Nessun fallback corrente o all'anno più vicino.

Il passaggio **2015 → 2018** porta almeno i break `methodology` e `spatial_resolution`. Serie segmentate; delta e trend attraverso il break bloccati; niente interpolazione o armonizzazione implicita. Anche FTY legacy e moderno entrambi elaborati a 100 m restano separati: stessa risoluzione di output non elimina il cambio di generazione nativa/metodo.

## Recommended H1I-B scope

| Asset proposto, distinto dal moderno | Kind | Riferimenti / geometrie | Risoluzione di processing | Metriche attese |
| --- | --- | --- | --- | --- |
| `hrl_legacy_tree_cover_density_20m` | `tree_cover_density` | 2012→2012; 2015→2015 | 20 m nativi | Densità media di copertura arborea, ponderata per area valida |
| `hrl_legacy_forest_type_100m` | `forest_type` | 2012→2012; 2015→2015 | 100 m ufficiali, nessun ricampionamento locale | Aree/quote forestali e composizione per classe, con copertura valida esplicita |

Per entrambi valgono identificatori/versioni e route della tabella di accesso, famiglia legacy e break sopra. Non aggiungere anni agli asset H1H.

Contratto valori dalla [specifica CLMS](https://land.copernicus.eu/en/technical-library/hrl-forest-2012-2015/@@download/file), tabelle prodotto §§4.1–4.3 e 4.6:

- TCD 20 m: `0` assenza di alberi valida; `1–100` densità percentuale.
- FTY 100 m: `0` non foresta; `1` latifoglie; `2` conifere; `3` bosco misto.
- DLT 20 m: `0` assenza di alberi; `1` latifoglie; `2` conifere.
- `254` non classificabile e `255` fuori area sono distinti; escluderli dai valori validi senza convertirli in zero. Verificare anche maschera e NoData effettivi del file.

La [sintesi tecnica CLMS](https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover?tab=technical_summary) precisa che nel 2012/2015 solo FTY 100 m esclude già alberi agricoli/urbani; FTY 20 m richiede il support layer. Per questo H1I-B propone il 100 m ufficiale: non attribuire al 20 m grezzo la semantica del prodotto filtrato, né inventare la classe mista nel 20 m.

## Unresolved / deferred

- **Gate H1I-B:** accettare esplicitamente FTY nell'aggregato ufficiale 100 m e predisporre credenziali CLMS. Collaudare autenticazione/download prima di una materializzazione; la ripetibilità è documentata, non provata end-to-end in H1I-A.
- **UNRESOLVED a livello di file:** nomi TIFF interni, conteggio/descrizione delle bande e tag NoData effettivi non verificati senza raster. `TCD`, `FTY`, `DLT` identificano prodotti, non bande BYOC accertate. L'adapter dovrà validare header, CRS, risoluzione, valori e maschere prima dell'aggregazione; non assumere silenziosamente band 1.
- **FTY 20 m alternativo:** support layer e relativo identificatore operativo non chiusi qui; richiedono evidenza dedicata se si rifiuta l'input 100 m proposto.
- **DLT 2012/2015:** prodotti/accesso verificati, ma `VERIFIED_BUT_DEFER` per assenza di esigenza aggiuntiva approvata. Moderno e legacy restano disabilitati.
- Nessun candidato complessivamente `UNRESOLVED` o `NOT_SUITABLE`; le lacune tecniche sopra restano esplicite e non autorizzano fallback.
- TCPC resta esclusivamente 2018–2021. TCPC 2021–2024 non verificato nel contratto corrente; CORINE e INFC storico restano fuori ambito.
