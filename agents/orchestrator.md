# Orchestrator

Coordina la pipeline di Conti Chiari. Non produce testo per l'utente e non
interpreta dati finanziari: decide **chi viene eseguito, con quale input, e
cosa succede quando qualcosa fallisce**.

## Invarianti

1. Nessun artefatto raggiunge l'utente senza un `verdict: pass` del guardrail.
2. Ogni agente riceve solo la propria fetta di stato (vedi tabella Input).
3. Il CSV grezzo non entra mai in un prompt.
4. Gli scenari di simulazione sono sempre impostati dall'utente.
5. Ogni output è validato contro il suo schema prima di essere scritto su disco.

## Stato

```
state/<session_id>/
├── transactions.json
├── analysis.json
├── concepts.json
├── gaps.json
├── quadro.json
├── explanation.json
├── simulation.json
├── verdict-<artifact>-<index>.json
├── quiz.json
└── run.log            append-only: step, esito, token, durata
```

Lo stato vive su disco. L'orchestratore tiene in memoria solo `session_id` e lo
step corrente.

## Sequenza

| # | Step | Input | Output | Se fallisce |
|---|---|---|---|---|
| 1 | `parser` (codice) | file CSV | `transactions.json` | vedi [Mapping colonne](#mapping-colonne-hitl) |
| 2 | `categorizer` | `transactions.json` a batch di 50 | `analysis.json` | batch fallito → transazioni in `uncategorized`, si prosegue |
| 3 | conferma utente | `needs_human_review[]` | `analysis.json` aggiornato | se l'utente salta, le voci restano `uncategorized` |
| 4 | `concept-mapper` | `analysis.json` senza `transactions` | `concepts.json` | 0 concetti → fallback ai 2 concetti più comuni con evidenza |
| 5 | `completeness` | periodo + descrizioni distinte + checklist | `gaps.json` | fallback a `gaps: []` con la sola `coverage_note` sul periodo |
| 6 | risposte utente | `gaps.json` | importi annuali dichiarati | se l'utente salta, il quadro resta quello osservato |
| 7 | `quadro_annuale` (codice) | totali + importi dichiarati | `quadro.json` | deterministico: fallisce solo su input non validi |
| 8 | `explainer` | `concepts.json` + transazioni citate come evidenza | `explanation.json` | dopo 2 retry → sezione marcata `unavailable`, le altre proseguono |
| 9 | `guardrail` | `explanation.json`, una sezione per volta | `verdict-*.json` | vedi [Ciclo di revisione](#ciclo-di-revisione) |
| 10 | `simulator` | scenario utente + output di `finance.py` | `simulation.json` | errore di calcolo → scenario non mostrato, mai numeri parziali |
| 11 | `guardrail` | `simulation.json` | `verdict-*.json` | come step 9 |
| 12 | `comprehension` | `concepts.json` + numeri approvati | `quiz.json` | quiz non generato → il percorso resta valido senza verifica |

Gli step 4 e 5 leggono entrambi `analysis.json` senza scriverlo, e possono
girare in parallelo; lo stesso vale per 8 e 10. Tutti gli altri sono
sequenziali.

Lo step 6 è un punto di attesa, non un fallimento: `completeness` produce
domande e la pipeline prosegue anche senza risposte. Il quadro corretto è un
arricchimento, non un prerequisito.

## Ciclo di revisione

```
explainer → guardrail
              ├── pass    → artefatto disponibile
              ├── revise  → explainer riscrive con le violations in input
              │             (max 2 cicli, poi block)
              └── block   → l'artefatto non si mostra;
                            la UI espone la risposta di reindirizzamento
```

Il contatore di cicli sta in `run.log`, non nel contesto dell'explainer.
Al secondo `revise` consecutivo sullo stesso `section_index`, l'orchestratore
forza `block`: non esiste un terzo tentativo.

Se il guardrail restituisce `escalate_to_human: true`, l'artefatto va in coda di
revisione e la UI mostra *"questa spiegazione è in verifica"*. Non è un errore:
è il comportamento previsto quando il confine è ambiguo.

## Mapping colonne (HITL)

Il parser riconosce le colonne per alias, coprendo i dialetti `it-standard`,
`en-standard` e `banca-generico` (colonne separate dare/avere). Si ferma e
chiede all'utente di mappare data, descrizione e importo in due casi: le
intestazioni non corrispondono a nessun alias noto, oppure **nessuna** riga
risulta valida. Il dialetto diventa allora `user-mapped`.

Righe singole illeggibili non attivano il mapping: finiscono in `rejected[]` e
la UI dichiara quante ne ha scartate. Sono due condizioni diverse — colonne
sbagliate contro dati sporchi — e vanno trattate diversamente.

## Gestione errori

| Condizione | Azione |
|---|---|
| Output non conforme allo schema | 2 retry con lo schema in prompt, poi fallback dello step |
| Timeout agente (30 s) | 1 retry, poi fallback dello step |
| Wall clock pipeline > 120 s | interruzione: si mostra quanto è già passato dal guardrail |
| Coda di revisione umana piena (20) | nuovi artefatti ambigui vengono bloccati, non accodati |

Un fallback non è mai un'invenzione: una sezione mancante si dichiara mancante.

## Cosa l'orchestratore non fa

- Non categorizza, non spiega, non calcola, non valuta il confine consulenza.
- Non riscrive l'output di un agente: può solo rieseguirlo o fare fallback.
- Non decide cosa insegnare: è compito del `concept-mapper`.
