# Conti Chiari — istruzioni di lavoro

## Vincolo di dominio

**Il sistema non dà consigli finanziari.** Mostra, spiega e simula. Ogni testo
che raggiunge l'utente descrive un fatto o una conseguenza matematica; nessuno
orienta una decisione — nemmeno quando l'utente lo chiede, nemmeno quando il
suggerimento sarebbe sensato.

Vale anche per il codice che scrivi: messaggi di errore, label della UI,
docstring, commenti, fixture di test e dati di esempio. Una stringa con
"dovresti", "ti conviene", "meglio se" è un bug, non uno stile.

Le sette regole e i casi limite stanno in `agents/subagents/guardrail.md`. Non
riscriverli altrove: quel file è sia documentazione sia system prompt.

## Architettura

@agents/README.md

## Comandi

Dalla cartella `app/`, con il virtualenv già creato in `app/.venv`:

```
./.venv/Scripts/python.exe -m pytest tests/ -q          # 66 test, devono restare verdi
./.venv/Scripts/python.exe -m uvicorn main:app --reload # server su :8000
./.venv/Scripts/pip.exe install -r requirements.txt
```

`ANTHROPIC_API_KEY` va in `app/.env` (vedi `.env.example`): mai nel codice, mai
nel repo. Il frontend statico è in `app/static/`, montato su `/` da `main.py`.

CSV di prova: `app/sample/estratto-conto-esempio.csv`.

## Convenzioni

- **Nessun LLM tocca i numeri.** Aritmetica, ammortamenti, interesse composto e
  deflazionamento sono funzioni pure in `finance.py`, con `Decimal` internamente
  e float ai centesimi in uscita. Il modello riceve i risultati e li racconta.
- **Ogni output di agente è validato** contro il suo schema in `agents/schemas/`
  da `AgentRuntime.run()`. Un artefatto non conforme non esiste.
- **Lo stato sta su disco** in `state/<session_id>/`, non nel contesto.
- **Slicing degli input**: a un agente passa solo la sua fetta di stato. Il CSV
  grezzo non entra mai in un prompt, le transazioni complete quasi mai.
- **Un fallback non inventa**: una sezione mancante si dichiara mancante, una
  voce non classificabile va in `uncategorized`.
- Testi, commenti e docstring in italiano. Niente emoji.

## Due livelli di agenti, non confonderli

- `agents/` — agenti **di runtime del prodotto**. Girano quando un utente usa
  l'app: `categorizer`, `explainer`, `guardrail`, ... Modificarli cambia il
  comportamento del sistema.
- `.claude/` — agenti e comandi **di sviluppo**. Servono a chi scrive il codice
  e non girano mai in produzione. Modificarli non cambia il prodotto.

Un file in `.claude/` non ridescrive un agente di runtime: lo cita per path.

## Limiti

Non modificare `state/`: è output generato. Non toccare `agents/config/models.yaml`
per aggirare un fallimento: timeout, retry e cicli di revisione sono scelte di
progetto, non parametri da tarare finché il test passa.
