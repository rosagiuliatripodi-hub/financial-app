# Conti Chiari

**Hagenthon · Tema 02 — Inclusione finanziaria · Accenture Application Engineering**

Sistema multi-agente che trasforma un CSV di entrate e uscite in un percorso
educativo di finanza personale.

> **Il sistema non dà consigli finanziari.** Mostra, spiega, chiede e simula.
> Non sceglie mai al posto dell'utente. Il confine è imposto da un agente
> dedicato, non da un filtro di parole chiave.

---

## Il problema

Un estratto conto di tre mesi non contiene i costi annuali. Assicurazione auto,
bollo, IMU, TARI, canone RAI cadono una o due volte l'anno: in una finestra
trimestrale sono invisibili **per costruzione**.

Chi legge quell'estratto e conclude *"avanzo 350 € al mese"* fa un conto
aritmeticamente corretto e arriva a un numero sbagliato. Chi ha bassa
alfabetizzazione finanziaria non ha modo di accorgersene.

```
saldo mensile osservato     350,00 €   ← quello che l'estratto sembra dire
costi annuali dichiarati    900,00 €   ← risposte dell'utente alle domande
incidenza mensile            75,00 €
saldo mensile corretto      275,00 €   ← quello reale
```

Rendere visibile il perimetro dei dati è il contributo educativo più alto che il
sistema può dare, e non richiede di dare un solo consiglio.

## Avvio

```bash
cd app
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt

cp .env.example .env          # incollare la chiave in ANTHROPIC_API_KEY
./.venv/Scripts/python.exe -m uvicorn main:app --port 8000
```

Poi `http://127.0.0.1:8000`. Senza un estratto a portata di mano si può usare
`app/sample/estratto-conto-esempio.csv`.

Test:

```bash
cd app && ./.venv/Scripts/python.exe -m pytest tests/ -q
```

## Struttura

```
/
├── app/              prototipo: FastAPI + pagina statica
│   ├── parser.py         CSV -> transazioni normalizzate (deterministico)
│   ├── finance.py        matematica finanziaria (deterministica, testata)
│   ├── agents_runtime.py tiering, retry, validazione schema, contabilità token
│   ├── orchestrator.py   sequenza, stato su disco, fallback, revisione
│   ├── main.py           API
│   ├── static/           interfaccia
│   └── tests/            45 test sulla parte deterministica
├── agents/           struttura agentica di runtime  →  agents/README.md
├── presentation/     presentazione HTML (5 minuti, con note relatore)
├── .claude/          struttura agentica di sviluppo (subagenti, comandi, hook)
└── CLAUDE.md         contesto operativo per chi lavora sul repo
```

`agents/` e `.claude/` non si sovrappongono: il primo contiene gli agenti che
girano **quando un utente usa l'app**, il secondo quelli che servono **al team
che scrive il codice**.

## Architettura

Sette agenti, otto contratti JSON. Il flusso completo, la motivazione di ogni
nodo e la strategia sui token stanno in **[agents/README.md](agents/README.md)**.

Tre scelte che reggono il resto:

1. **Il CSV non entra mai in un prompt.** Il parser è codice; a valle circola
   l'aggregato. Un estratto da 800 righe pesa ~40k token, il suo aggregato ~1.200.
2. **La matematica non è un prompt.** Interesse composto, ammortamento e
   deflazionamento sono funzioni pure in `finance.py`, testate su valori
   calcolati a mano. L'LLM riceve i risultati e li racconta.
3. **Il guardrail è indipendente da chi genera il testo.** Un modello non è un
   revisore affidabile del proprio output: accorpare `explainer` e `guardrail`
   annullerebbe il controllo.

## Il confine educazione / consulenza

| Non passa | Passa |
|---|---|
| "Investi in un ETF" | "Se accantoni 50 €/mese, in 3 anni versi 1.800 €" |
| "Taglia questo abbonamento" | "Hai 4 costi ricorrenti per 47 €/mese, eccoli" |
| "Scegli il TAEG più basso" | "Il TAEG include gli oneri accessori, il TAN no" |
| "È buona norma tenere un fondo per gli imprevisti" | "Se hai un'auto, l'assicurazione qui non compare: vuoi aggiungerla?" |

Il criterio: **una frase che descrive un fatto o una conseguenza matematica
passa; una frase che orienta una decisione no** — anche quando il suggerimento
sarebbe sensato, anche quando l'utente l'ha chiesto esplicitamente.

Le sette regole e la procedura stanno in
[agents/subagents/guardrail.md](agents/subagents/guardrail.md). In caso di dubbio
il verdetto è `escalate_to_human`: il sistema fallisce chiuso.

## Validazione

**Verificato**

- 68 test automatici:
  - **45** su parser e matematica finanziaria, con valori calcolati a mano
  - **23** sull'orchestrazione con runtime iniettato — ciclo di revisione e limite a 2 cicli,
    verdetto `block`, fail-closed quando il guardrail non risponde, fallback del categorizer
    e del concept-mapper, invarianti della simulazione, contabilità token su disco
- **Dry-run delle istruzioni** su `state/demo/`: ogni file di `agents/subagents/` è stato
  eseguito sui 46 movimenti reali del CSV di esempio, e ogni artefatto prodotto è stato
  validato contro il suo schema. Il controllo di integrità numerica del guardrail è stato
  automatizzato: 16 cifre nei testi, 0 mismatch. Ha fatto emergere 11 difetti — un'istruzione
  insoddisfacibile, due regole che escludevano sempre i casi più utili, uno schema senza
  casella per le soglie normative e un doppio conteggio nel ricalcolo del quadro — tutti
  corretti.
- Upload end-to-end sul CSV di esempio: 46 movimenti letti, 0 scartati, periodo corretto
- Palette dei grafici validata sui controlli CVD (banda di luminosità, chroma, ΔE, contrasto)
- Configurazione assente: 503 leggibile, non 500 muto
- Hook di test verificato su entrambi i rami (`.py` sotto `app/` e file non Python)

**Limiti noti**

- Il glossario copre 10 concetti e la checklist 14 voci: un estratto atipico trova meno aggancio
- Un solo conto per sessione: carte e conti terzi restano fuori dal quadro
- Il guardrail è un modello, non una garanzia formale: riduce il rischio, non lo azzera
- Gli importi annuali li dichiara l'utente — il sistema non li stima né li verifica
- I test sull'orchestrazione usano un runtime iniettato: dimostrano che la Pipeline reagisce
  correttamente agli esiti degli agenti, **non** che i prompt reali producano output conforme
  agli schemi. Quello richiede una chiave e una esecuzione vera.

## Team

**Fabio Gorini** — architettura agentica, backend Python, orchestrazione,
test automatici, istruzioni degli agenti.

**Rosa Giulia Tripodi** — frontend standalone (`app/static/demo.html`):
design bancario multi-pagina, parsing CSV lato client, modalità inserimento
manuale, accessibilità (ARIA, alto contrasto, font size), presentazione finale.

## Uso dell'AI nel progetto

Il progetto è stato sviluppato interamente con Claude Code. Le istruzioni degli
agenti in `agents/subagents/` **sono** i system prompt caricati a runtime da
`agents_runtime.py`: non esistono due versioni che possono divergere.

Gli interventi umani hanno riguardato le decisioni di perimetro — in
particolare il passaggio da "dare best practice" a "fare domande", che ha
riscritto una funzionalità intera — e la verifica dei fallback, dove un
suggerimento plausibile avrebbe portato il sistema a inventare dati invece di
dichiararli mancanti. Sul lato frontend, le scelte di UX (multi-pagina,
inserimento manuale, accessibilità) sono state guidate dall'utente iterazione
per iterazione.
