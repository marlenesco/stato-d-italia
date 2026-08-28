# ADR 0010: shell responsive e workspace cartografico data-first

**Stato:** accepted

## Contesto

Le prime vertical slice frontend hanno riusato una sidebar editoriale per
navigazione, filtri, serie e contesto. Su schermi stretti la sidebar precede il
contenuto principale, ritarda la mappa di più viewport e rende difficile passare
fra domini. Un rapporto fisso del canvas produce inoltre mappe eccessivamente alte
su desktop e tablet.

## Decisione

La UI dei domini adotta un workspace data-first condiviso:

- header compatto con fonte, copertura e release;
- filtri principali in una toolbar sopra la mappa, non in una sidebar persistente;
- mappa come superficie primaria, dimensionata rispetto al viewport;
- dettaglio e serie del territorio dopo la selezione;
- metodo e provenance dopo il contenuto operativo.

Su mobile la navigazione globale usa un menu esplicito. Filtri, timeline e
controlli cartografici devono avere target di almeno 44×44 CSS pixel. Nessuna
navigazione primaria può allargare il documento oltre il viewport.

La home mostra un segnale reale per ogni dominio. Quando manca un aggregato
nazionale corretto, espone copertura e periodo della release invece di calcolare
un totale non pubblicato. Valori ufficiali, stime modellistiche ed elaborazioni
del progetto restano etichettati separatamente.

Restano validi i contratti di ADR 0004 e ADR 0009:

- geometria e valori tematici restano separati;
- la mappa mantiene un'alternativa testuale o tabellare;
- cambio metrica/periodo aggiorna i dati senza ricreare MapLibre quando la
  geometria non cambia;
- confronti temporali rispettano comparabilità e indisponibilità dichiarate.

## Verifica richiesta

Ogni modifica al workspace deve essere verificata almeno a 390×844, 768×1024,
1024×768 e 1440×1000, includendo:

- assenza di overflow orizzontale;
- accesso a tutti i domini e filtri;
- mappa leggibile e ridimensionata correttamente;
- navigazione da tastiera e focus visibile;
- URL condivisibile dopo cambio di metrica, livello e periodo;
- nessun flicker MapLibre sui cambi che riusano la stessa geometria.

## Conseguenze

- Le sidebar non sono più struttura primaria dei domini.
- Home e pagine operative usano gerarchie diverse: orientamento sulla home,
  controllo e lettura del dato nei domini.
- Nuovi domini devono usare lo stesso workspace prima di introdurre layout propri.
