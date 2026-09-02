# Runbook operativo

## Setup locale

```sh
uv sync --all-groups --frozen
```

## Test

```sh
uv run pytest -q
git diff --check
```

## Pipeline locale

```sh
uv run stato-data run --workdir data --output artifacts
```

L'esecuzione locale non deve modificare la release R2 attiva.

## Acquisizione automatica locale

Ogni dominio scarica direttamente dalla propria fonte ufficiale e archivia raw,
licenza/metadati, checksum e URL. Nessun `cp` o input manuale.

Per acquisire solo dissesto IdroGEO:

```sh
uv run stato-data fetch dissesto --workdir data
```

Per acquisire solo raw del dominio Emissioni ISPRA:

```sh
uv run stato-data fetch emissions --workdir data
```

Per acquisire, validare e pubblicare nella object store locale tutti i domini
configurati:

```sh
uv run stato-data run --workdir data --output artifacts --report reports/local-ingestion.json
```

`run` invoca anche l'acquisizione IdroGEO. Usa i quattro export JSON ufficiali
senza `outputFormat`, quindi non scarica CSV/Excel né effettua richieste per
singolo territorio. Archivio raw conserva le risposte esatte. Un errore HTTP,
schema o copertura territoriale interrompe flusso.

## Riesecuzione offline

`--offline` non effettua richieste HTTP e riusa solo raw già acquisiti:

```sh
uv run stato-data run --offline --workdir data --output artifacts --report reports/local-ingestion.json
```

Poi controlli obbligatori:

```sh
uv run pytest -q
git diff --check
```

## Publish R2

```sh
uv run stato-data run --publish r2
```

Prima del publish verificare che le credenziali siano fornite dall'ambiente e non
da file versionati.

## Source state e workflow

Ogni release contiene `metadata/source-state.json` content-addressed. È letto
attraverso release attiva e `manifest.json`; non esiste un secondo puntatore
mutabile. Per controllare una scope senza dipendere dalla cache GitHub:

```sh
uv run stato-data check-sources --scope data --publish r2
uv run stato-data check-sources --scope geospatial --publish r2
```

Il controllo usa `GET` condizionale quando possibile, mai solo `HEAD`. I due
workflow sono `ingest-data.yml` (domini tabellari non forestali e delivery) e
`ingest-geospatial.yml` (intero dominio Foreste: INFC, catalogo Copernicus,
raster, canonical, PMTiles, zonal statistics e delivery).
Cache Actions accelera ma non decide se fonte è nuova. Uno scope recupera gli
input di elaborazione necessari dalla release R2 attiva, che è il last-known-good
autorevole, e porta avanti gli altri artifact per riferimento immutabile: la
release resta completa anche su runner pulito. Questo vale anche per famiglie
invariate dello stesso scope; cache Actions e file locali sono soltanto
acceleratori.

Il report del preflight è anche il piano effimero del run scoped. Ogni asset
ufficiale è marcato `changed`, `unchanged` oppure `unverifiable` e il piano è
vincolato al `releaseId` ancora attivo e non può essere riprodotto dopo un cambio
di manifest. Prima dell'ingestione sono idratati soltanto gli artifact richiesti
dal grafo di elaborazione interessato: un file locale valido viene riusato, uno
mancante o stale viene idratato atomicamente da R2 e verificato con SHA-256. Gli
artifact non necessari localmente restano riferimenti content-addressed. Oggetti
carried mancanti o con key, byte o SHA incoerenti interrompono il publish; errori
R2 di autenticazione o server non sono trattati come semplici `not found`. Gli
adapter contattano la fonte soltanto per asset `changed` senza body già acquisito
dal preflight.
Se un `GET` di controllo ha già letto il body completo, questo viene conservato
in `data/.preflight/<scope>` e promosso atomicamente dal run, senza un secondo
download. La directory è temporanea e non è source state né fonte di verità.

Un errore remoto con baseline attiva valida resta `unverifiable`: non costituisce
prova di cambiamento e conserva il last-known-good. Senza baseline fidata il
flusso resta fail-closed. Le metriche distinguono `sourcesUnverifiable` e non
contano come controllate/acquisite le sorgenti soltanto portate avanti.

Il preflight Copernicus calcola la signature del catalogo remoto senza scrivere
`data/raw`, canonical o cache. Solo il vero run geospaziale persiste
`catalog.json`; una signature nuova forza la rigenerazione delle statistiche
zonali. Il preflight IdroGEO confronta invece una signature deterministica dei
quattro export reali (`country`, `regions`, `provinces`, `municipalities`), non
la risposta dell'URL base dell'API.

Le sole richieste HTTPS verso `www.inventarioforestale.org`, eseguite dal
workflow geospatial su GitHub Actions, possono usare un fallback proxy italiano.
Il trasporto prova prima la connessione diretta, poi i proxy configurati in
`INFC_HTTPS_PROXIES` nell'ordine dichiarato. Ogni candidato deve completare una
richiesta reale a INFC con verifica TLS attiva; errori, certificati non validi e risposte di blocco fanno
passare al candidato successivo. Nessun altro host usa questi proxy. Fuori da
GitHub Actions il fallback è disabilitato anche se la variabile viene impostata:
le esecuzioni locali restano dirette.

Configurare `INFC_HTTPS_PROXIES` come repository secret multilinea, una URL per
riga. È accettata anche la virgola come separatore; l'ordine viene preservato.
Per un proxy HTTP che supporta CONNECT verso destinazioni HTTPS usare
`http://IP:PORT`, non `https://`, salvo che il proxy stesso esponga TLS:

```text
http://proxy-principale.example:3128
http://proxy-fallback.example:8080
```

Gli indirizzi e le credenziali di eventuali proxy devono vivere solo nel secret.
Non impostare `HTTP_PROXY` o `HTTPS_PROXY` globali: instraderebbero anche R2,
CDSE e le altre fonti. Il proxy resta trasporto non autorevole; TLS, SHA-256,
contratti raw e provenance restano invariati.

L'hydration confronta sempre lo SHA-256 locale con quello referenziato dalla
release attiva. Un file di cache con SHA diverso viene riscaricato e verificato
prima della sostituzione atomica: la cache non è mai fonte di verità. Nei run
scoped l'hydration è limitata agli artifact necessari per ricalcolare gli output
effettivamente interessati; gli altri artifact restano referenziati tramite il
loro object key immutabile e non vengono copiati localmente.

## CORS R2/CDN per frontend diretto

MapLibre, PMTiles e JSON vengono letti dal browser direttamente da R2/CDN,
senza proxy Vercel. Configurare quindi CORS sul bucket prima del deploy web:

- `GET`, `HEAD`;
- origine esatta del sito pubblico e origine locale di sviluppo;
- header richiesta `Range` e header esposti `Content-Range`, `Accept-Ranges`,
  `Content-Length`, `ETag`.

`config/r2-cors.example.json` è template: sostituire/aggiungere solo origini
effettivamente autorizzate. Non usare `*` in produzione senza decisione
esplicita. Vercel preview richiede origini preview dichiarate oppure test locale.
Il frontend usa attualmente un endpoint pubblico `r2.dev` configurabile. Il
futuro dominio `data.statoditalia.it` non è ancora attivo e nessuno dei due URL
deve essere hardcoded nella logica storage o pipeline.

## Ordine di publish

```text
download
→ validate
→ normalize
→ generate
→ hash
→ upload immutable objects
→ verify objects
→ publish immutable release.json
→ verify release
→ update manifest.json
```

`manifest.json` non deve essere aggiornato in caso di errore precedente.

## No-op

Se il contenuto della fonte è invariato:

- non duplicare il raw;
- non rigenerare dati senza motivo.
- non caricare oggetti già content-addressed;
- non creare release e non aggiornare `manifest.json`.

L'incrementalità è per asset logico, non per byte: se cambia un archivio o un
workbook monolitico viene riscaricato per intero, mentre gli altri asset dello
stesso scope vengono riusati dalla release attiva. INFC e Copernicus sono due
famiglie indipendenti: un cambiamento INFC non acquisisce raster Copernicus; un
cambiamento Copernicus non contatta INFC. Se cambia un solo ZIP INFC, gli altri
ZIP vengono idratati/riusati e la canonical INFC viene rigenerata in modo
coerente prima del delivery Foreste. Il preflight Copernicus controlla soltanto
la signature del catalogo: le slice generate dal Process API presenti nel
source-state non vengono trattate come URL statici né verificate con GET
individuali. Un catalogo cambiato autorizza l'acquisizione delle slice correnti
nel vero ingest e impedisce che una vecchia slice locale venga riusata come se
fosse ancora autorevole.

Uno scope `data` sostituisce solo entry source `data` e conserva entry
`geospatial`; scope geospatial fa opposto. Le fonti con URL scoperto dalla
landing vengono prima ri-risolte: URL nuovo è cambiamento anche se quello
precedente risponde ancora.

Anche gli artifact hanno ownership e famiglia di elaborazione esplicite. Nei run
scoped gli artifact di famiglie non interessate, compresi quelli dello stesso
scope, sopravvivono per riferimento immutabile senza hydration. Una famiglia
interessata viene invece sostituita integralmente dagli artifact dichiarati dal
run: file rimossi o obsoleti non possono essere carried-forward. Gli artifact
condivisi seguono le loro dipendenze: `territory-insights` viene rigenerato solo
se cambia un input semantico e, in quel caso, idrata soltanto le canonical
invariate che consuma. `all` non esegue carry-forward e sostituisce inoltre
l'intero source state: entry e raw obsoleti non restano nella nuova release.

Le dipendenze geometriche sono esplicite per dominio e anno. Un nuovo confine
ISTAT rigenera soltanto PMTiles e delivery che usano quel reference year:
Suolo/Acqua 2025, Dissesto 2024, Emissioni 2019 o 2023. Il bundle Foreste resta
geospatial e internamente coerente per object identity immutabile; quando cambia
INFC viene rigenerata la geometria regionale 2015, quando cambia Copernicus
vengono rigenerate le geometrie 2023. Un aggiornamento di un altro anno non
invalida la geometria storica 2015. Gli indici delivery referenziano soltanto
geometrie presenti nella release e le mappe dichiarano il reference year
compatibile. Le signature delle canonical Foreste e degli input semantici di
`territory-insights` sono ricontrollate prima del publish.

Foreste non è diviso tra scope: `infc-2015-forests`, `raw/infc-*`,
`raw/copernicus-*`, entrambi i rami `canonical/forests/` e
`delivery/foreste/` sono `geospatial`. Un run `data` non contatta né processa
INFC e porta avanti questi artifact immutabili dalla release attiva. La
riclassificazione non modifica SHA-256, validator HTTP, provenance o identità
della sorgente e, da sola, non crea una release.

Per la sola migrazione da una release legacy priva di
`metadata/source-state.json`, il runner ricostruisce lo snapshot dagli artifact
raw e dai relativi sidecar immutabili già presenti nella release attiva. Una
coppia raw/sidecar mancante o metadata non valido interrompe il bootstrap; lo
state ricostruito viene reso persistente solo insieme a una nuova release
completa e verificata.

Se la release legacy precede anche uno dei due scope e quindi non contiene gli
input necessari al carry-forward, avviare manualmente `ingest-geospatial.yml`
con `bootstrap_all=true`. Questo esegue una ricostruzione `scope=all` senza
carry-forward; completato il bootstrap, lasciare `bootstrap_all=false` per tutte
le esecuzioni ordinarie scoped.

Una modifica di provenance significativa può comunque produrre una metadata-only
release secondo ADR 0005.

## Rollback

Il rollback non modifica oggetti già pubblicati.

Procedura:

1. identificare una release precedente verificata;
2. verificare che tutti gli oggetti referenziati esistano ancora;
3. aggiornare `manifest.json` alla release scelta;
4. verificare il manifest pubblico.

## Failure policy

Se schema, unità, periodi o mapping territoriale non corrispondono al contratto:

- fail;
- non pubblicare;
- non correggere automaticamente la fonte;
- produrre diagnostica sufficiente a capire il cambiamento upstream.

## Controlli dopo ingestione reale

Registrare almeno:

```text
raw bytes
source checks / changed / unchanged / unverifiable
canonical bytes
delivery bytes
objects uploaded / reused
bytes uploaded to R2
release referenced bytes (dimensione logica)
record count
accepted/rejected count
territory coverage by level
available periods and gaps
unresolved territory mappings
pipeline duration
source checksum
active release id
```

Queste misure servono anche a stimare la crescita dello storage R2.
