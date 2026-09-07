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

Le geometrie ISTAT sono selezionate per snapshot: TCD 2018/2021/2023 usa
rispettivamente 2018/2021/2023, FTY 2018/2021 usa 2018/2021 e TCPC 2018–2021
usa 2021. `territoryReferenceYear` e `territoryGeometryReference` sono presenti
in slice manifest, coverage, diagnostica e delivery. Una comparazione tra
snapshot con geometrie diverse resta descrittiva e viene marcata non
territorialmente comparabile: non calcola delta, correlazione o continuità
territoriale implicita.

## Conseguenze

- Il manifest production resta invariato durante le validation candidate;
  l'idratazione R2 è sola lettura e l'output è locale.
- Le PMTiles Foreste includono le geometrie necessarie per 2018, 2021, 2023 e
  la Regione INFC 2015.
- Questa decisione integra ADR 0018 senza modificarne il contratto TCD 100 m o
  la semantica NoData.
