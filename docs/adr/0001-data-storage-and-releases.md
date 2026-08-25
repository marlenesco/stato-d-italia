# ADR 0001: storage R2 e release immutabili content-addressed

**Stato:** accepted

## Contesto

I dataset possono essere più grandi del repository Git e devono potersi aggiornare
senza generare una nuova build del futuro frontend Next.js. La pipeline deve inoltre
garantire riproducibilità, rollback e assenza di release parziali.

## Decisione

Cloudflare R2 è lo storage primario per:

- raw tabellari e vettoriali;
- canonical Parquet;
- delivery artifacts;
- metadata e provenance;
- release descriptor.

Gli oggetti persistenti sono content-addressed tramite SHA-256. Un oggetto con lo
stesso contenuto deve poter essere riutilizzato da più release.

Struttura logica:

```text
/objects/sha256/<prefix>/<sha256>
/releases/<release-id>/release.json
/manifest.json
```

`release.json` è immutabile. `manifest.json` è l'unico puntatore mutabile alla
release attiva.

## Pubblicazione atomica

L'ordine obbligatorio è:

1. acquisizione e validazione in workspace temporaneo;
2. generazione degli oggetti;
3. calcolo SHA-256;
4. upload degli oggetti mancanti;
5. verifica HEAD/dimensione/checksum degli oggetti referenziati;
6. pubblicazione di `release.json`;
7. verifica della release completa;
8. aggiornamento di `manifest.json`.

Una pipeline fallita prima del punto 8 non modifica la release attiva.

Il rollback consiste esclusivamente nel puntare `manifest.json` a una release
precedentemente verificata.

## Retention

- Raw tabellari e vettoriali: conservazione preferenziale permanente.
- Canonical Parquet: conservazione permanente finché economicamente sostenibile.
- Metadata, URL sorgente, licenza e checksum: sempre conservati.
- Raster/griglie pesanti: retention selettiva; il progetto non promette di
  archiviarli indefinitamente nel free tier.
- Gli oggetti delivery sono eliminabili solo se non più referenziati da release
  conservate; nessun garbage collection automatico nelle milestone 1–4.

## Conseguenze

Vantaggi:

- nessun deploy Vercel necessario per pubblicare nuovi dati;
- rollback semplice;
- deduplicazione naturale;
- release riproducibili;
- cache aggressiva sugli oggetti immutabili.

Costi:

- serve un manifest/release protocol esplicito;
- la retention dei raster deve essere governata;
- occorre monitorare spazio e oggetti non più referenziati.

## Alternative scartate

- **Dati nel repository Git:** crescita della history, build non necessarie,
  limiti dimensionali.
- **Database come storage primario:** non necessario per payload read-only e
  storici; introdurrebbe un servizio runtime senza un requisito attuale.
- **Sovrascrittura di file con URL stabili:** rende cache, rollback e coerenza
  delle release più fragili.
