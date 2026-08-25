# ADR 0002: territori storici versionati

**Stato:** accepted

## Contesto

Codici, nomi, confini e relazioni amministrative italiane cambiano nel tempo.
Associare tutte le osservazioni storiche alla geografia corrente produrrebbe serie
apparentemente continue ma metodologicamente scorrette.

## Decisione

Separare identità logica e versione amministrativa:

```text
territory_id
territory_version_id
geometry_version_id
```

- `territory_id` identifica l'entità logica.
- `territory_version_id` identifica codici, nome, livello, genitori e validità/
  data di riferimento.
- `geometry_version_id` identifica il confine cartografico usato per quella
  versione.

Le relazioni parent/child sono temporalizzate.

## Cambi amministrativi

Sono rappresentati esplicitamente almeno:

- rename;
- merge;
- split;
- abolished;
- boundary transfer;
- parent change.

Nessuna pipeline crea un crosswalk storico stimato.

Fusioni, scissioni, soppressioni o trasferimenti producono una **series break**
salvo che il dataset o un'altra fonte ufficiale fornisca un mapping difendibile e
documentato.

Un mapping ufficiale deve conservare:

- fonte;
- periodo di validità;
- regola;
- eventuale peso;
- riferimento metodologico.

## Regole per osservazioni e mappe

Ogni osservazione territoriale deve dichiarare la versione territoriale coerente
con il periodo/riferimento della fonte.

Le mappe storiche devono utilizzare una geometria compatibile con la
`territory_version_id` dell'osservazione. Non è consentito unire implicitamente un
valore storico al poligono corrente solo perché il codice o il nome coincidono.

## Conseguenze

- Alcuni grafici mostreranno interruzioni reali nella serie.
- Il confronto tra anni può richiedere l'esclusione di territori non comparabili.
- La UI futura deve spiegare le rotture territoriali invece di nasconderle.

## Alternative scartate

- **Codice ISTAT come PK eterna:** i codici e i perimetri possono cambiare.
- **Tutto sui confini correnti:** facile da visualizzare, ma produce confronti
  storici potenzialmente falsi.
- **Crosswalk stimati automaticamente:** non accettabili senza base ufficiale.
