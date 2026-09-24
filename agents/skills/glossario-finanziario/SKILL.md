---
name: glossario-finanziario
description: Vocabolario condiviso dei concetti di finanza personale di base riconoscibili in un estratto conto italiano. Usato dal categorizer per agganciare le commissioni a un concetto, dal concept-mapper per selezionare cosa insegnare, dall'explainer come base della definizione e dal comprehension per costruire distrattori plausibili.
---

# Glossario finanziario

Fonte unica dei concetti che il sistema può insegnare. Un concetto che non è qui
**non esiste** per la pipeline: il `concept-mapper` non può coniarlo e
l'`explainer` non può introdurlo.

I dati stanno in [`concetti.json`](concetti.json).

## Struttura di un concetto

| Campo | A cosa serve | Chi lo usa |
|---|---|---|
| `id` | chiave stabile, referenziata negli artefatti | tutti |
| `label` | nome leggibile | explainer |
| `livello` | `fondamentale` \| `base` \| `intermedio` | concept-mapper, per filtrare su `literacy_level` |
| `trigger` | stringhe che compaiono nelle descrizioni delle transazioni | categorizer |
| `definizione_base` | una frase, registro A2 | explainer con `literacy_level: base` |
| `definizione_intermedio` | può usare i termini tecnici | explainer con `literacy_level: intermedio` |
| `opacita` | 1-3, quanto è probabile che l'utente non sappia cos'è | concept-mapper, terzo criterio di ordinamento |
| `errore_tipico` | l'equivoco più comune su questo concetto | comprehension, per i distrattori |

## Due famiglie di concetti

Il campo `trigger` distingue come un concetto entra nel percorso:

| `trigger` | `livello` | Famiglia | Chi lo attiva |
|---|---|---|---|
| non vuoto | qualsiasi | **da dati** — compare in una transazione | `concept-mapper`, cercando l'evidenza |
| vuoto | `fondamentale` | **da dati** — l'evidenza è qualunque movimento | `concept-mapper`, senza bisogno di indizi |
| vuoto | `base` / `intermedio` | **da scenario** — non lascia traccia in un estratto | `simulator`, quando l'utente imposta la simulazione |

`interesse-composto`, `inflazione` e `potere-acquisto` sono della terza
famiglia: nessun estratto conto contiene una riga "inflazione". Il
`concept-mapper` non li selezionerà mai, ed è corretto — li introduce la
simulazione nel momento in cui diventano osservabili sui numeri dell'utente.

`entrate-uscite` ha anch'esso `trigger` vuoto, ma è `fondamentale`: non serve un
indizio testuale perché la sua evidenza è l'estratto stesso. È la riga di mezzo
della tabella, e la distinzione non è accademica — il fallback del
`concept-mapper` poggia su questo concetto.

Un concetto da scenario **senza** uno scenario in `simulator.md` che lo dichiari
è irraggiungibile: non va aggiunto al glossario.

## Regole d'uso

- I `trigger` sono indizi, non prove. Il categorizer li usa per proporre un
  `concept_id`, ma una corrispondenza testuale da sola non basta: serve che la
  transazione sia coerente per importo e cadenza.
- `definizione_base` e `definizione_intermedio` sono **punti di partenza**, non
  testo da incollare. L'explainer le riformula ancorandole ai numeri
  dell'utente.
- `errore_tipico` descrive un equivoco reale, ed è materiale per i distrattori
  del quiz. Non va mai mostrato all'utente come se fosse vero.

## Estendere il glossario

Un concetto entra solo se è **riconoscibile in un estratto conto o in una
bolletta italiana**. Concetti che richiederebbero dati che il sistema non ha
(patrimonio, orizzonte temporale, profilo di rischio) sono fuori perimetro per
costruzione: sono gli input di una consulenza, non di un percorso educativo.
