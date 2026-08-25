# ADR 0005: provenance della fonte come parte della release

**Stato:** accepted

## Contesto

Ogni numero pubblicato deve poter essere ricondotto al dataset ufficiale acquisito,
alla sua versione e, quando possibile, alla riga o elemento sorgente. Header HTTP
e URL da soli non sono sufficienti perché le fonti possono cambiare senza URL
versionati.

## Decisione

Ogni acquisizione raw registra almeno:

- `source_id` / `dataset_id`;
- landing URL;
- resolved download URL;
- acquisition timestamp;
- HTTP status;
- ETag, se presente;
- Last-Modified, se presente;
- Content-Type;
- byte size;
- SHA-256 del payload;
- licenza riferita all'artefatto;
- metodologia/riferimenti disponibili;
- note di qualità e stato validated/provisional/unknown.

Il canonical conserva il raw SHA-256 e un `source_row_locator` o riferimento
equivalente quando tecnicamente possibile.

## Change detection

ETag e Last-Modified possono essere usati per richieste condizionali e per evitare
download inutili, ma **SHA-256 del contenuto è l'identità finale del payload**.

Se il payload è identico:

- non si rigenerano automaticamente canonical/delivery;
- non si duplica il raw.

Tuttavia una modifica significativa a licenza, metodologia, stato ufficiale o
metadata di provenance può generare una **metadata-only release** anche se il
payload raw è invariato.

Quindi “raw checksum invariato” non implica necessariamente “nessuna release”:
implica soltanto “nessun nuovo contenuto dati”.

## Provenance delle metriche derivate

Ogni metrica derivata deve puntare agli input canonical e alla versione
dell'algoritmo. La UI futura deve distinguere chiaramente:

```text
dato ufficiale
dato normalizzato
metrica derivata
stima
dato provvisorio
```

## Conseguenze

È possibile auditare e riprodurre le elaborazioni senza affidarsi alla stabilità
del sito sorgente o del suo URL.
