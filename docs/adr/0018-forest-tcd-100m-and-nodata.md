# ADR 0018: contratto TCD 100 m e semantica NoData per Foreste

**Stato:** accepted

## Contesto

ADR 0017 aveva identificato impropriamente `TCDCL` 10 m come Tree Cover
Density. `TCDCL` è invece il confidence layer; non può alimentare la metrica
di copertura arborea. Inoltre, nei prodotti HRL alcune classi del raster
rappresentano esplicitamente area esterna e non lo zero osservato.

## Decisione

L'asset operativo Tree Cover Density è `hrl_tree_cover_density_100m`: prodotto
`CLMS_HRLVLCC_TCD_S{anno}_R100m_{tile}_{EPSG}_V{versione}_R{revisione}`,
collezione BYOC
`edd3c5f5-da8e-463f-8c9a-712aa451d37e`, banda `TCD`, risoluzione nativa e di
processing 100 m. Il catalogo richiede sia il frammento di nome sia una regex
del nome completo, oltre a `ContentDate/Start` dell'anno configurato. Il campo
EPSG del tile non è fissato a `03035`, perché il catalogo contiene anche tile
fuori dall'Europa; nomi TCD 10 m, `TCDCL` e prodotti adiacenti fanno fallire il
contratto.

Forest Type 100 m e Tree Cover Presence Change (periodo `2018–2021`) dichiarano
`255` come NoData sorgente. Dopo l'esclusione del NoData interno Process,
vengono esclusi solo i codici sorgente previsti dal singolo contratto. Se non
restano pixel validi, il territorio è `validNoData`: non è una superficie,
un guadagno o una perdita pari a zero. Lo zero resta un valore valido quando è
una classe del prodotto.

La copertura nazionale viene verificata per ogni coppia asset/periodo: l'unione
delle entry regionali deve essere esattamente la popolazione ISTAT attesa e le
popolazioni numerica e `validNoData` devono essere disgiunte. Le diagnostiche
temporali confrontano solo territori numerici in entrambi gli snapshot e
registrano separatamente le quattro transizioni numeric/NoData; il guardrail
contro snapshot duplicati opera sul payload completo dell'asset e resta attivo
solo quando metric set, popolazioni numerica/NoData e tutti i valori sono
identici. L'identità della source signature continua a essere verificata
separatamente.

## Conseguenze

- Non viene effettuato downsampling TCD 10 m → 100 m: la sorgente TCD è già a
  100 m.
- Le scale colore temporali e le rispettive legende condividono un solo dominio
  calcolato sui periodi compatibili.
- La correzione sostituisce soltanto il contratto operativo errato di ADR 0017;
  non modifica la policy nazionale, la separazione official/derived o
  l'attivazione seriale della release.
