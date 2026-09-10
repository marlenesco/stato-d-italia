# ADR 0019: intervallo sorgente TCPC e geometrie storiche Foreste

**Stato:** accepted

## Contesto

La prima candidate validation nazionale ha evidenziato che Tree Cover Presence
Change (TCPC) veniva richiesto al Processing API con il solo giorno iniziale
`2018-01-01`. Il catalogo CDSE dichiara invece il prodotto TCPC come periodo
`2018–2021`: l'intervallo reale del `ContentDate` è parte del contratto di
sorgente. La stessa candidate usava inoltre le geometrie ISTAT 2023 per tutti
gli snapshot Copernicus, inclusi quelli 2018 e 2021.

## Decisione

Per ogni snapshot, il catalogo CDSE conserva ID prodotto, nome, `ContentDate`
iniziale e finale, `PublicationDate`, `ModificationDate`, checksum, `S3Path` e
`OriginDate`. TCPC usa nel Processing API esattamente l'intervallo
`ContentDate` del catalogo; query senza prodotti, con nomi non conformi,
confidence layer, date mancanti o date ambigue falliscono chiuse.

La cache delle slice include la firma SHA-256 della request Process completa.
Questa invalida le sole slice TCPC prodotte con l'intervallo errato. Le slice
annuali TCD e FTY precedenti possono essere riusate soltanto dopo verifica di
checksum, request, prodotto e `ContentDate`; non vengono accettate per TCPC.

Le classi TCPC ammesse sono `0`, `1`, `2`, `10` e `255`. `255` è NoData
sorgente; `0` e `10` restano osservazioni valide. Classi sconosciute fanno
fallire il processing. Una copertura TCPC nazionale con zero Regioni numeriche
è un errore di contratto e non può produrre canonical/delivery.

Le geometrie ISTAT esatte sono selezionate per asset/periodo: nella
configurazione operativa moderna H1H, TCD annuale 2018–2024 usa la geometria
dello stesso anno, FTY 2018, 2021 e 2024 usa le rispettive geometrie e TCPC
resta 2018–2021 con anno territoriale di riferimento 2021. Gli anni geometrici
richiesti derivano dai periodi degli asset HRL abilitati, senza una lista
hardcoded duplicata; il risultato corrente è 2018–2024. DLT resta disabilitato
e HRL legacy 2012/2015 resta fuori da H1H. Questa configurazione non implica
che i nuovi dati H1H siano già materializzati o pubblicati. `territoryReferenceYear` e `territoryGeometryReference` sono presenti
in slice manifest, coverage, diagnostica e delivery. Una comparazione tra
snapshot con geometrie diverse resta descrittiva e viene marcata non
territorialmente comparabile: non calcola delta, correlazione o continuità
territoriale implicita.

## Conseguenze

- Il manifest production resta invariato durante le validation candidate;
  l'idratazione R2 è sola lettura e l'output è locale.
- Le PMTiles Copernicus Foreste richieste seguono gli anni derivati dai
  periodi HRL abilitati: con il config H1H, 2018–2024. INFC resta separato
  sulla geometria regionale 2015.
- Questa decisione integra ADR 0018 senza modificarne il contratto TCD 100 m o
  la semantica NoData.
