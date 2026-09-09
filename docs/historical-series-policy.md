# Historical series policy

## Purpose

Questa policy traduce l'evidenza repository di
[H1A](historical-coverage-audit.md), la ricerca ufficiale di
[H1B](historical-source-research.md) e la decisione architetturale
[ADR 0025](adr/0025-cross-domain-historical-series-contract.md) in regole
cross-domain. Definisce cosa una fase successiva potrà implementare; non
modifica sorgenti, canonical, derived, delivery, frontend o R2.

Principio centrale:

> Stato d'Italia può esporre la massima profondità storica difendibile, ma non
> deve mai implicare una comparabilità territoriale o metodologica che
> l'evidenza non supporta.

## Terminology

- **Reference period**: istante o intervallo a cui il valore si riferisce. Non è
  la data di pubblicazione.
- **Source release**: pubblicazione immutabile o acquisizione identificata da
  editore, data, URL risolto e SHA-256.
- **Source version**: versione dichiarata del dataset, modello, metodologia o
  submission.
- **Project release**: release immutabile Stato d'Italia che seleziona una
  combinazione coerente di sorgenti e derivati.
- **Territory reference date**: data ufficiale della struttura territoriale a
  cui il valore è attribuito.
- **Series break**: discontinuità in almeno una dimensione necessaria a una
  capacità comparativa. Non equivale alla semplice assenza di un periodo.
- **Sparse series**: insieme di snapshot o intervalli reali che non costituisce
  una sequenza annuale completa.
- **Status product**: rappresentazione dello stato in un periodo.
- **Change product**: prodotto ufficiale che rappresenta il cambiamento fra due
  riferimenti. Non è intercambiabile con la sottrazione di due status.

I termini `allowed`, `allowed_with_annotation`, `blocked`, `not_applicable` e
`unresolved` descrivono l'eleggibilità semantica. La disponibilità effettiva
resta l'intersezione con gli asset pubblicati secondo ADR 0022.

## Territorial modes

| Valore | Significato | Uso ammesso |
| --- | --- | --- |
| `contemporaneous_exact` | Valore amministrativo collegato a una geometria ufficiale valida alla data dichiarata dalla fonte | display e mappa; confronti solo se gli altri gate passano |
| `source_harmonized` | L'editore pubblica esplicitamente valori storici su una geografia comune diversa da quella contemporanea | display, mappa e serie con annotazione della geografia comune |
| `project_aggregated_exact` | Stato d'Italia aggrega una fonte ufficiale non amministrativa su geometria ufficiale compatibile con il periodo | solo come derivato, con algoritmo e coverage |
| `non_administrative_grid` | Il valore resta sulla griglia ufficiale nativa | nessun join amministrativo implicito |
| `official_crosswalk` | Una fonte ufficiale fornisce mapping, validità, regola e pesi | capacità limitate a quanto il mapping documenta |
| `project_harmonized` | Il progetto applica un crosswalk dichiarato | solo derivato e dopo ADR specifico; mai osservazione ufficiale |
| `unknown` | Data, geometria o relazione territoriale non dimostrata | attribuzione e mappa amministrativa bloccate |

La modalità è una proprietà del dataset e del periodo, non del solo dominio. Un
dataset può usare modalità diverse per livelli diversi, per esempio BIGBANG
ufficiale a livello Italia/Regione e `project_aggregated_exact` per le Province.

| Evidenza territoriale incontrata | Classificazione H1C | Esito predefinito |
| --- | --- | --- |
| exact-year official geography | `contemporaneous_exact` | eleggibile dopo verifica identitaria |
| source-declared harmonized geography | `source_harmonized` | eleggibile con annotazione |
| official census snapshot | `contemporaneous_exact` soltanto per la data censuaria dichiarata | non sostituisce un altro anno o un intero intervallo |
| nearest-year geography | nessuna modalità ammessa | `blocked` |
| current geography applied retrospectively dal progetto | nessuna modalità ammessa | `blocked` |
| explicit official crosswalk | `official_crosswalk` | eleggibile entro scopo e validità documentati |
| project-derived crosswalk | `project_harmonized` | derivato, nuovo ADR obbligatorio, nessuna attribuzione ufficiale |

## Exact-year rule

Una osservazione amministrativa può usare una geometria quando ricorre almeno
una delle condizioni seguenti:

1. la fonte dichiara quella esatta versione/data territoriale;
2. esiste una geometria ufficiale alla data richiesta e l'identità sorgente è
   verificata uno-a-uno;
3. una fonte ufficiale documenta un intervallo di validità che copre l'uso;
4. esiste un `official_crosswalk` con provenienza, periodo, regola e pesi.

Se più geometrie o regole risultano applicabili senza precedenza documentata,
la decisione è ambigua e fallisce. Non sono ammessi:

- nearest-year;
- geografia corrente applicata retroattivamente;
- sostituzione automatica con uno snapshot censuario vicino;
- join fondato solo su nome o codice coincidente;
- crosswalk stimato non dichiarato come derivato.

### Decisioni per gli anni critici

| Periodo | Decisione H1C | Motivazione |
| --- | --- | --- |
| Emissioni 1990 | mappa/canonical amministrativo `blocked` | nessuna geometria exact-year o mapping ufficiale; il 1991 non è sostitutivo |
| Emissioni 1995 | mappa/canonical amministrativo `blocked` | nessuna geometria exact-year o mapping ufficiale |
| Emissioni 2000 | mappa/canonical amministrativo `blocked` | nessuna geometria exact-year o mapping ufficiale; il 2001 non è sostitutivo |
| Emissioni 2005 | `requires_identity_audit` | geometria ISTAT 01-01-2005 disponibile; serve join completo sulle 103 unità sorgente |
| Emissioni 2010 | `requires_identity_audit` | geometria ISTAT 01-01-2010 disponibile; serve verifica delle 110 unità e della struttura sarda |
| Confini 2011 | snapshot ufficiale utilizzabile solo come `2011-10-09` | è una data censuaria, non un confine annuale al 01-01 |
| BIGBANG 2011 provinciale | `blocked` | lo snapshot censuario non copre automaticamente l'intero anno; manca un intervallo ufficiale |
| Emissioni 2015 | `requires_identity_audit` | geometria ISTAT 01-01-2015 già materializzata; serve join completo sulle 110 unità sorgente |

Gli anni 2019 e 2023 restano governati dall'adapter accettato in ADR 0024. Il
2021 ISTAT al 31 dicembre è l'eccezione annuale esplicita già governata dagli
ADR 0020 e 0021; non crea una regola generale per altri snapshot censuari.

Per BIGBANG provinciale la presenza del raster 1951–2025 non basta. Ogni anno
richiede una geometria ufficiale ammissibile, la data esatta attesa e il gate
metodologico già accettato. Un nuovo confine materializzato amplia la matrice
solo dopo validazione; non modifica retroattivamente i risultati precedenti.

## Source-harmonized geography

`source_harmonized` è ammesso soltanto quando è l'editore a dichiarare la
geografia comune. Deve esporre `territory_reference_date`, fonte e versione
della geometria armonizzata e non può essere etichettato come “confini storici”.

Regole:

- display e mappe sono ammessi con etichetta “geografia armonizzata dalla
  fonte”;
- una serie è ammessa se tutti i punti usano la stessa base armonizzata e gli
  altri assi di comparabilità sono compatibili;
- delta, trend e ranking sono valutati soltanto all'interno della stessa base
  armonizzata;
- il confronto diretto con una serie `contemporaneous_exact` è bloccato, salvo
  un prodotto ufficiale che definisca l'equivalenza;
- un cambio della base armonizzata produce una rottura territoriale.

Il Suolo è il caso noto: il workbook corrente usa la geografia di fonte 2025,
mentre almeno un prodotto storico 2006 verificato usa la geografia 2024. Le due
edizioni non vengono unite finché identità, contenuto e metodologia non sono
riconciliati.

## Series breaks

Le dimensioni sono valutate indipendentemente. `same` deve essere dimostrato;
assenza di metadata equivale a `unknown`, non a stabilità.

| Dimensione | Rottura | Effetto minimo |
| --- | --- | --- |
| Metric definition | significato, popolazione o denominatore cambia | serie segmentata; delta, trend e movimento in ranking bloccati |
| Unit | unità non uguale e conversione semantica non documentata | serie comparativa, delta e trend bloccati |
| Methodology/version | modello, algoritmo o processo di stima cambia | annotazione; delta/trend bloccati attraverso il cambio |
| Classification | classi o mapping cambiano | confronto della classe e ranking bloccati attraverso il cambio |
| Territory geography | cambia `territory_version_id` o base armonizzata | niente linea, delta o trend senza crosswalk ufficiale |
| Revision/reprocessing | si mescolano submission o ricostruzioni diverse | serie mista bloccata; differenza trattata come revisione |
| Period duration | durate o semantica istante/intervallo differiscono | delta/trend bloccati; durata sempre visibile |
| Spatial resolution | cambia griglia, MMU o risoluzione analitica | delta/trend bloccati finché la comparabilità non è documentata |

Una rottura non blocca il display isolato né, se esiste la geometria corretta,
la mappa del singolo periodo. La vista storica può presentare segmenti distinti.
Il ranking del singolo periodo resta possibile soltanto se peer group,
classificazione, unità e metodo sono omogenei in quel periodo.

## Capability eligibility

La capability effettiva deriva da quattro gate:

```text
eleggibilità della famiglia
  ∩ evidenza per metrica/periodo/livello
  ∩ asset dichiarati nella release
  ∩ controlli runtime o algoritmo versionato
```

### Single-period display

Richiede valore o value state esplicito, metrica/unità, periodo, fonte/versione
e geografia nota quando il valore è territoriale. Una rottura non lo blocca.
`unknown` territoriale blocca l'attribuzione amministrativa, ma non impedisce di
conservare l'artefatto raw o descriverlo come evidenza sorgente.

### Map display

Richiede display eleggibile e geometria compatibile con la modalità
territoriale. `mapGeometry` è autoritativo. Una mappa `source_harmonized` mostra
la geografia comune dichiarata; una mappa `non_administrative_grid` resta nella
griglia nativa. Nessun fallback usa il poligono corrente.

### Historical time series

Richiede almeno due periodi reali della stessa famiglia e metrica. I punti
possono essere mostrati anche in presenza di rotture, ma sono segmentati,
annotati e non collegati attraverso il break. L'esistenza della serie non
abilita delta o trend.

### Period-to-period delta

Richiede due valori numerici con identica metrica, unità, metodologia,
classificazione, durata e base territoriale, oppure un change product ufficiale
che definisca direttamente il confronto. Richiede inoltre che la capability sia
autorizzata prima del calcolo previsto da ADR 0009. Zero, missing e periodi
mancanti seguono le regole già accettate; non sono interpolati.

### Trend

Richiede una metodologia derivata specifica e versionata, numerosità e coverage
minimi, cadenza compatibile e nessuna rottura nella finestra. ADR 0007 soddisfa
questi requisiti solo per la finestra annuale del Suolo che disciplina; non
autorizza trend negli altri domini.

### Ranking e confronto territoriale

Richiedono stesso periodo, livello, metrica, unità, metodo, classificazione,
modalità territoriale e popolazione completa/definita. Sono indipendenti dalla
comparabilità temporale. Un cambiamento fra ranking di periodi diversi non è un
trend quando esiste una rottura.

## Sparse series

Le serie sparse mostrano solo snapshot/intervalli pubblicati:

- nessuna interpolazione o imputazione;
- nessun punto sintetico per colmare anni mancanti;
- durata del periodo e distanza temporale visibili;
- punti non collegati per default;
- una linea è ammessa soltanto tra riferimenti adiacenti nella cadenza
  ufficiale, senza break e con semantica continua documentata;
- delta soltanto tra coppie eleggibili, mai “annualizzato” implicitamente;
- trend bloccato per default e abilitabile solo da metodologia specifica;
- ranking valutato separatamente per ogni snapshot.

Applicazioni:

- emissioni provinciali: otto punti irregolari; niente linee, delta o trend
  finché geometria e comparabilità non sono dimostrate;
- INFC: 1985/2005/2015 sono cicli inventariali distinti; solo confronti
  esplicitamente pubblicati o metriche singolarmente qualificate;
- CORINE: status a intervalli irregolari; i change layer ufficiali sono la
  fonte per le transizioni;
- IdroGEO: snapshot di mosaici/versioni PAI; non rappresentano eventi annuali.

## Source revisions and reprocessing

Ogni osservazione distingue:

```text
observation reference period
source publication/release
source version or submission
project release
```

Regole:

1. una project release seleziona una sola ricostruzione coerente per famiglia;
2. non si uniscono anni di submission diverse per riempire buchi;
3. la sostituzione di byte allo stesso URL genera nuova acquisizione, SHA-256 e
   source release;
4. il valore più recente per un vecchio anno è la stima ufficiale corrente di
   quella submission, non il valore originariamente pubblicato in quell'anno;
5. la differenza per lo stesso reference period fra due submission è
   `revision_delta`, non cambiamento ambientale;
6. un confronto di revisioni richiede una vista e un contratto dedicati;
7. una geometria ISTAT sostituita produce nuova `geometry_version_id` e rebuild
   dei derivati dipendenti; non riassegna in place osservazioni già pubblicate;
8. una migrazione di accesso senza dichiarazione di reprocessing non cambia la
   metodologia presunta.

BIGBANG 10.0, NID 2026 e IIR 2026 sono ricostruzioni complete: le loro serie
interne possono essere valutate entro una singola versione, mentre confronti
con BIGBANG 9 o submission emissive precedenti sono revisioni. Il workbook
provinciale rev. 06/2026 è una release indivisibile: correzioni di coordinate o
SNAP non vanno mescolate con revisioni precedenti. Per Copernicus, il 2024 e la
migrazione CDSE non provano da soli un reprocessing scientifico.

## Raster-derived territorial series

Una statistica zonale amministrativa è difendibile soltanto con tutti i
seguenti elementi:

- raster ufficiale e byte identificati da SHA-256;
- reference period e source version noti;
- CRS, risoluzione, extent, NoData e unità noti;
- geometria ufficiale ammessa dalla exact-year rule;
- identità e gerarchia territoriale validate;
- algoritmo e parametri versionati;
- derivazione riproducibile con riferimenti agli input;
- coverage e quality state espliciti;
- separazione `derived_by_stato_italia` dall'osservazione ufficiale.

Per un raster annuale lo snapshot censuario 2011 del 9 ottobre non è sufficiente
senza un intervallo ufficiale. La data speciale ISTAT 2021 resta valida perché
è l'esatto riferimento dell'edizione annuale governata dagli ADR 0020/0021.
Una geometria comune successiva può essere usata soltanto come
`project_harmonized`, dopo ADR specifico, e non sostituisce
`project_aggregated_exact`.

## Dataset-family decisions

La matrice esprime eleggibilità di policy, non disponibilità corrente. Le
condizioni e i blocker nella matrice successiva restano vincolanti.

### Historical capability matrix

| Famiglia | Display | Map | Timeseries | Delta | Trend | Ranking | Cross-territory |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ISTAT boundaries | `allowed` | `allowed` | `allowed_with_annotation` | `not_applicable` | `not_applicable` | `not_applicable` | `not_applicable` |
| Soil | `allowed_with_annotation` | `allowed_with_annotation` | `allowed_with_annotation` | `allowed_with_annotation` | `allowed_with_annotation` | `allowed_with_annotation` | `allowed_with_annotation` |
| BIGBANG | `allowed` | `allowed_with_annotation` | `allowed_with_annotation` | `allowed_with_annotation` | `unresolved` | `blocked` | `allowed_with_annotation` |
| INFC | `allowed` | `allowed` | `unresolved` | `unresolved` | `blocked` | `allowed_with_annotation` | `allowed_with_annotation` |
| Copernicus TCD | `allowed_with_annotation` | `allowed_with_annotation` | `allowed_with_annotation` | `unresolved` | `unresolved` | `allowed_with_annotation` | `allowed_with_annotation` |
| Copernicus DLT | `allowed_with_annotation` | `allowed_with_annotation` | `allowed_with_annotation` | `unresolved` | `unresolved` | `unresolved` | `allowed_with_annotation` |
| Copernicus FTY | `allowed_with_annotation` | `allowed_with_annotation` | `allowed_with_annotation` | `unresolved` | `unresolved` | `allowed_with_annotation` | `allowed_with_annotation` |
| Copernicus change products | `allowed_with_annotation` | `allowed_with_annotation` | `allowed_with_annotation` | `blocked` | `blocked` | `allowed_with_annotation` | `allowed_with_annotation` |
| CORINE status | `allowed_with_annotation` | `allowed_with_annotation` | `allowed_with_annotation` | `blocked` | `blocked` | `unresolved` | `allowed_with_annotation` |
| CORINE change | `allowed_with_annotation` | `allowed_with_annotation` | `allowed_with_annotation` | `blocked` | `blocked` | `unresolved` | `allowed_with_annotation` |
| IdroGEO hazard | `allowed_with_annotation` | `allowed_with_annotation` | `allowed_with_annotation` | `blocked` | `blocked` | `not_applicable` | `not_applicable` |
| IdroGEO risk indicators | `allowed_with_annotation` | `allowed_with_annotation` | `unresolved` | `blocked` | `blocked` | `blocked` | `blocked` |
| GHG national | `allowed` | `not_applicable` | `allowed` | `allowed_with_annotation` | `unresolved` | `not_applicable` | `not_applicable` |
| NFR national | `allowed` | `not_applicable` | `allowed` | `allowed_with_annotation` | `unresolved` | `not_applicable` | `not_applicable` |
| Emissions provincial | `allowed_with_annotation` | `allowed_with_annotation` | `allowed_with_annotation` | `blocked` | `blocked` | `blocked` | `blocked` |
| Emissions grid | `allowed_with_annotation` | `unresolved` | `allowed_with_annotation` | `blocked` | `blocked` | `not_applicable` | `not_applicable` |

### Territory, break, revision and blocker matrix

| Famiglia | Territory rule | Series-break rule | Revision rule | Remaining blocker |
| --- | --- | --- | --- | --- |
| ISTAT boundaries | ogni snapshot conserva data, codici, gerarchia e geometry version | ogni variazione amministrativa è un break | sostituzioni producono nuova versione/hash | exact-year assenti 1990/1995/2000; snapshot non materializzati |
| Soil | `source_harmonized`; geografia 2025 corrente e 2024 nell'artefatto storico verificato non si mescolano | durata, classificazione, metodo o base armonizzata separano segmenti | ogni workbook/edizione resta coerente | unicità degli stock storici e dizionario colonne |
| BIGBANG | Italia/Regioni ufficiali; Province `project_aggregated_exact` | cambio modello o geometry version blocca confronto | una versione ricalcola l'intera storia | geografia regionale di fonte; confini provinciali mancanti; metodo trend |
| INFC | unità inventariali ufficiali; nessuna estensione a Province o Comuni | cicli e definizioni qualificate metrica per metrica | ogni edizione resta separata | accesso 2005 e comparabilità; 1985 senza dataset |
| Copernicus TCD | raster nativo; aggregati solo `project_aggregated_exact` | break 20 m/10 m, metodo, reprocessing e geografia | non inferire reprocessing dalla migrazione CDSE | registrazione anni esterni; evidenza comparabilità 2024 |
| Copernicus DLT | come TCD; derivati 100 m distinti dal DLT 10 m | break di risoluzione/classificazione/geografia | source/product version pinning | processing disabilitato e anni non registrati |
| Copernicus FTY | raster nativo; aggregati exact-period | break 20 m/10 m e classificazione | source/product version pinning | anni non registrati e comparabilità 2024 |
| Copernicus change products | geometria di fine periodo dichiarata | ogni intervallo e versione è un prodotto; niente delta del delta | TCPC/DLTC 2021–2024 non esistono finché non verificati | change 2021–2024 `UNRESOLVED` |
| CORINE status | raster nativo; aggregati exact-period | status revisionati, MMU e anno nominale segmentano | non sottrarre status di revisioni diverse | acquisizione, metodo aggregati, ranking e date 1990 eterogenee |
| CORINE change | prodotto ufficiale distinto dagli status | durata 10/6 anni e revisioni sempre visibili | usare una sola release coerente | registrazione/processing e politica metriche |
| IdroGEO hazard | geodata hazard non è geografia amministrativa | versione mosaico/copertura/PAI è break | ogni mosaico resta snapshot di release | matrice completa versione-copertura-territorio |
| IdroGEO risk indicators | usare la geografia dichiarata dall'edizione | famiglie frane/alluvioni e anni indicatore distinti | non mescolare report e API di edizioni diverse | dataset storici machine-readable mancanti |
| GHG national | livello Italia, territorio non problematico | dimensioni, metodo o submission separano ricostruzioni | default: intera serie della submission corrente | metodo trend ed eventuale contratto di revision comparison |
| NFR national | livello Italia, territorio non problematico | dimensioni NFR, metodo o submission separano ricostruzioni | default: intera serie della submission corrente | metodo trend ed eventuale contratto di revision comparison |
| Emissions provincial | solo periodi `contemporaneous_exact` con identity audit | geometria, SNAP, unità o revisione segmentano | workbook revisionato usato come unità coerente | 1990/95/2000 territorio; audit 2005/10/15 |
| Emissions grid | `non_administrative_grid`; nessun join alle Province | convenzione coordinate o griglia produce break | ogni workbook/versione resta coerente | CRS, cell geometry, futura convenzione e delivery |

## Emissions grid decision

La griglia EMEP 0,1° × 0,1° deve diventare, se implementata, una famiglia
sorgente e capability separata:

- è ufficiale e complementare alle Province;
- conserva cell ID, coordinate, SNAP, inquinante, unità e periodo;
- non sostituisce periodi amministrativi bloccati;
- non viene aggregata alle Province senza una distinta derivazione e policy;
- una futura convenzione centro-cella è una nuova versione/break rispetto al
  vertice inferiore sinistro corrente.

Il relativo ADR specifico è **deferred**. Prima servono evidenza ufficiale del
CRS, convenzione/versione delle coordinate, regola di costruzione delle celle,
schema canonical/delivery e semantica della mappa. H1C consente soltanto di
trattare le righe sorgente come opportunità separata; non autorizza ingest,
rendering o aggregazione.

## Proposed machine-oriented contract

Il seguente è un contratto concettuale, non uno schema production:

```yaml
historical_observation:
  reference_period:
    start: date
    end: date
    kind: instant | annual | interval | change_interval
    duration_days: integer
  source_release:
    published_at: datetime
    release_id: string
    resolved_url: string
    raw_sha256: string
  source_version: string
  project_release_id: string

  territory:
    mode: contemporaneous_exact | source_harmonized |
      project_aggregated_exact | non_administrative_grid |
      official_crosswalk | project_harmonized | unknown
    reference_date: date | null
    source_id: string | null
    territory_version_id: string | null
    geometry_version_id: string | null
    crosswalk_id: string | null

  semantics:
    metric_id: string
    unit: string
    methodology_version: string
    classification_version: string | null
    spatial_resolution: string | null

  series_breaks_before:
    - dimension: metric | unit | methodology | classification |
        territory | revision | period_duration | spatial_resolution
      effect: annotate | segment | block_comparison
      reason: string
      evidence: [provenance_reference]

  capabilities:
    # status usa allowed | allowed_with_annotation | blocked |
    # not_applicable | unresolved
    display: {status: eligibility_status, reason: string, evidence: []}
    map: {status: eligibility_status, reason: string, evidence: []}
    timeseries: {status: eligibility_status, reason: string, evidence: []}
    delta: {status: eligibility_status, reason: string, evidence: []}
    trend: {status: eligibility_status, reason: string, evidence: []}
    ranking: {status: eligibility_status, reason: string, evidence: []}
    cross_territory: {status: eligibility_status, reason: string, evidence: []}

  derivation:
    official_status: official | derived_by_stato_italia
    algorithm_version: string | null
    input_references: []
    coverage: number | null
    quality_status: string | null
```

I campi obbligatori e le enum production saranno decisi nella fase di
implementazione. Uno stato `allowed` senza evidenza referenziata deve fallire la
validazione.

## Capability reason codes

La pubblicazione futura deve conservare reason code stabili almeno per:

```text
missing_territory_evidence
identity_audit_required
source_harmonized_only
series_break_metric
series_break_unit
series_break_methodology
series_break_classification
series_break_territory
series_break_revision
series_break_period_duration
series_break_spatial_resolution
insufficient_periods
sparse_series_no_interpolation
official_change_product_required
source_version_mismatch
methodology_not_defined
asset_not_published
```

I renderer non trasformano questi stati in capacità. Devono mostrare periodo,
tipo di geografia, provenienza e break; la logica resta nel contratto e nel
resolver.

## Remaining blockers

### Territory

- nessuna geometria o crosswalk exact-year per emissioni 1990/1995/2000;
- snapshot annuali ISTAT 2002–2014 e 2026 non tutti materializzati;
- 2011 disponibile solo alla data censuaria, non come intervallo annuale;
- geografia regionale implicita delle serie BIGBANG da rendere esplicita.

### Methodology

- confrontabilità metrica INFC 2005/2015 incompleta;
- break e reprocessing HRL 2024 non completamente documentati;
- aggregati CORINE e IdroGEO storici senza contratto;
- trend cross-domain non autorizzati da una metodologia comune;
- stock Suolo storici non ancora riconciliati con il workbook corrente.

### Source/access

- INFC 2005 richiede sessione;
- IFNI85 e vecchi risk indicator IdroGEO non hanno dataset machine-readable
  verificato;
- TCPC/DLTC 2021–2024 non sono stati verificati come prodotti pubblicati.

### Identity mapping

- join completo emissioni 2005/2010/2015 con le versioni ISTAT exact-year;
- struttura sarda storica 2010/2015;
- identità fra prodotti Suolo armonizzati di edizioni diverse.

### Architecture

- schema production dei metadata e dei reason code H1C;
- ADR specifico e schema per la griglia emissioni;
- eventuale vista distinta per confrontare revisioni di una fonte.

## Implementation queue

La priorità combina valore storico e difendibilità; non autorizza esecuzione in
H1C.

| Priorità | Candidate | Stato | Gate prima dell'implementazione |
| --- | --- | --- | --- |
| P0 | Contratto metadata/capability H1C | `requires_new_contract` | trasformare il modello concettuale in schema, validator e reason code |
| P0 | Confini ISTAT 2002–2010, 2012–2014 e 2026 | `ready_to_implement` | acquisizione versionata, date esatte, gerarchia e SHA-256; 2011 resta snapshot censuario separato |
| P0 | Emissioni provinciali 2005/2010/2015 | `requires_identity_audit` | join uno-a-uno per codici/nomi/gerarchie e struttura sarda |
| P1 | BIGBANG provinciali per ulteriori anni exact-year | `requires_territory_evidence` | confini materializzati e matrice fail-closed; escludere 2011 senza intervallo ufficiale |
| P1 | HRL status aggiuntivi, incluso 2024 | `requires_source_registration` | versioni prodotto, acquisizione, geometrie e break espliciti |
| P1 | CORINE status e change | `requires_methodology_work` | famiglie distinte, metriche, MMU, revisioni e aggregazione |
| P1 | INFC 2005 | `requires_source_registration` | accesso riproducibile e mapping metrica per metrica |
| P2 | Stock storici Suolo | `requires_methodology_work` | confronto contenuti col workbook corrente e geografia armonizzata |
| P2 | Snapshot IdroGEO hazard | `requires_methodology_work` | matrice mosaico/versione/copertura e policy aggregati |
| P2 | Risk indicator IdroGEO storici | `blocked` | dataset machine-readable e geografia dell'edizione mancanti |
| P2 | Emissions grid | `requires_new_contract` | CRS, convenzione celle, schema separato e ADR specifico |
| P3 | IFNI85 | `blocked` | nessun dataset storico machine-readable verificato |
| P3 | Copernicus change 2021–2024 | `blocked` | nessun prodotto ufficiale pubblicato verificato |

La fase successiva deve scegliere un elemento della coda e mantenere i gate
indicati. Nessuna sorgente viene registrata, acquisita o pubblicata da H1C.
