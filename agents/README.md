# Conti Chiari — Struttura agentica

Sistema multi-agente che trasforma un CSV di entrate e uscite in un percorso
educativo di finanza personale: mostra dove vanno i soldi, spiega i concetti
che compaiono nei dati reali dell'utente, simula scenari che l'utente stesso
imposta e verifica che abbia capito.

**Il sistema non dà consigli finanziari.** Mostra, spiega e simula. Non sceglie
mai al posto dell'utente. Questo confine è imposto da un agente dedicato
(`guardrail`) ed è descritto in [Confine educazione / consulenza](#confine-educazione--consulenza).

---

## Flusso

```
        CSV utente
            │
            ▼
   ┌─────────────────┐
   │  parser (code)  │  deterministico — nessun LLM
   └────────┬────────┘
            │ transactions.json
            ▼
   ┌─────────────────┐
   │   categorizer   │  haiku · categorie, ricorrenze, commissioni
   └────────┬────────┘
            │ analysis.json
            ├────────────────────────┐
            ▼                        ▼
   ┌─────────────────┐    ┌────────────────────┐
   │ concept-mapper  │    │    completeness    │  haiku · cosa manca
   └────────┬────────┘    └─────────┬──────────┘
            │ concepts.json         │ gaps.json
            │                       ▼
            │                risposte utente
            │                       │
            │                       ▼
            │          quadro_annuale() — codice, non prompt
            │          saldo mensile osservato vs reale
            ▼
   ┌────────┴────────┐
   ▼                 ▼
┌───────────┐  ┌─────────────┐
│ explainer │  │  simulator  │  math deterministica + narrazione
│   opus    │  │ code+haiku  │
└─────┬─────┘  └──────┬──────┘
      │ explanation   │ simulation.json
      │     .json     │
      └───────┬───────┘
              ▼
      ┌───────────────┐
      │   guardrail   │  opus · blocca ogni sconfinamento
      └───────┬───────┘
              │ verdict.json      ┌──────────────────┐
              ├──── block/revise ─│  human review    │
              │                   └──────────────────┘
              ▼ pass
      ┌───────────────┐
      │ comprehension │  haiku · quiz sui numeri veri dell'utente
      └───────────────┘
```

## Perché questi agenti e non un prompt solo

Ogni nodo esiste perché ha un **criterio di fallimento diverso**:

| Agente | Fallisce quando | Perché non può stare altrove |
|---|---|---|
| `parser` | il CSV è malformato | è codice: deve essere deterministico e testabile |
| `categorizer` | classifica male una voce | alto volume, task ripetitivo → modello economico |
| `concept-mapper` | seleziona concetti irrilevanti | decide *cosa insegnare*, non *come* |
| `completeness` | non vede un costo assente | ragiona sul **perimetro** dei dati, non sul loro contenuto |
| `explainer` | spiega in modo oscuro | qualità linguistica → modello forte |
| `simulator` | sbaglia i conti | la matematica è codice, l'LLM narra soltanto |
| `guardrail` | lascia passare un consiglio | deve essere **indipendente** da chi ha generato il testo |
| `comprehension` | genera quiz banali | task chiuso e verificabile → modello economico |

Accorpare `explainer` e `guardrail` annullerebbe il controllo: un modello non è
un revisore affidabile del proprio output.

## Contratti dati

Tutti gli scambi passano per file JSON validati contro gli schemi in
[`schemas/`](schemas/). Nessun agente riceve testo libero da un altro agente.

| Artefatto | Prodotto da | Schema |
|---|---|---|
| `transactions.json` | parser | [transactions.schema.json](schemas/transactions.schema.json) |
| `analysis.json` | categorizer | [analysis.schema.json](schemas/analysis.schema.json) |
| `concepts.json` | concept-mapper | [concepts.schema.json](schemas/concepts.schema.json) |
| `gaps.json` | completeness | [gaps.schema.json](schemas/gaps.schema.json) |
| `explanation.json` | explainer | [explanation.schema.json](schemas/explanation.schema.json) |
| `simulation.json` | simulator | [simulation.schema.json](schemas/simulation.schema.json) |
| `verdict.json` | guardrail | [guardrail-verdict.schema.json](schemas/guardrail-verdict.schema.json) |
| `quiz.json` | comprehension | [quiz.schema.json](schemas/quiz.schema.json) |

Lo stato vive su disco in `state/<session_id>/`, non nel contesto. Ogni agente
apre solo gli artefatti che gli servono e scrive solo il proprio.

## Efficienza dei token

Quattro scelte, in ordine di impatto:

1. **Il CSV non entra mai in un prompt.** Il parser è codice; a valle circola
   `analysis.json`, che è un aggregato. Un estratto conto da 800 righe pesa
   ~40k token; il suo aggregato ne pesa ~1.200.
2. **Slicing per agente.** `explainer` riceve `concepts.json` + le sole
   transazioni citate come evidenza, non l'intero `analysis.json`.
3. **Model tiering.** Vedi [`config/models.yaml`](config/models.yaml): i task ad
   alto volume e a output chiuso vanno su Haiku, solo `explainer` e `guardrail`
   usano Opus.
4. **La matematica non è un prompt.** Ammortamenti, interesse composto e
   deflazionamento sono funzioni pure in `app/`. L'LLM riceve i risultati già
   calcolati e li racconta.

## Robustezza

| Rischio | Mitigazione |
|---|---|
| CSV con formato sconosciuto | parser tenta 3 dialetti, poi chiede conferma del mapping colonne all'utente |
| Riga non parsabile | finisce in `rejected[]`, la pipeline prosegue e la demo dichiara quante righe ha scartato |
| Transazione non categorizzabile | bucket `uncategorized`, mai un'ipotesi inventata |
| Bassa confidence (< 0.5) | entra in `needs_human_review[]` e l'utente conferma |
| Agente che non produce JSON valido | 2 retry con lo schema in prompt, poi fallback al passo precedente |
| Loop tra explainer e guardrail | massimo 2 cicli di revisione, poi escalation umana |
| Guardrail incerto | `escalate_to_human: true` — in dubbio non passa |

Limiti di iterazione, timeout e retry sono in [`config/models.yaml`](config/models.yaml).

## Confine educazione / consulenza

Il tema vieta raccomandazioni di investimento, consulenza personalizzata e
indicazioni su cosa comprare, vendere o scegliere. Il sistema rispetta il
confine così:

| Vietato | Ammesso |
|---|---|
| "Investi in un ETF" | "Se accantoni 50 €/mese, in 3 anni sono 1.800 € — questo è interesse composto" |
| "Taglia questo abbonamento" | "Hai 4 costi ricorrenti per 47 €/mese, eccoli" |
| "Questo conto è più conveniente" | "Questa voce è l'imposta di bollo: ecco cos'è" |
| "È buona norma accantonare per gli imprevisti" | "Se hai un'auto, l'assicurazione è annuale e qui non compare: vuoi aggiungerla?" |

L'ultima riga è la regola che governa `completeness`: **una domanda non è mai un
consiglio, una best practice lo è quasi sempre.** Il sistema chiede all'utente di
completare il quadro, non gli dice cosa dovrebbe farne.

L'agente [`guardrail`](subagents/guardrail.md) applica sette regole su ogni
testo diretto all'utente. Quando l'utente chiede esplicitamente un consiglio, il
sistema **riconosce il confine, rifiuta e reindirizza sul concetto** — non
ignora la domanda.

## Struttura

```
agents/
├── README.md              questo file
├── orchestrator.md        sequenza, stato, gestione errori
├── subagents/             un file per agente: scope, input, output, vincoli
├── schemas/               contratti JSON
├── skills/
│   ├── glossario-finanziario/      concetti insegnabili
│   └── spese-ricorrenti-tipiche/   costi tipici e finestra di osservazione
└── config/models.yaml     tiering, budget token, timeout, retry
```
