---
description: Propaga la modifica di un contratto dati su schema, system prompt, codice e configurazione, poi verifica l'allineamento.
argument-hint: <artefatto.json> — il campo o il vincolo che cambia
allowed-tools: Read, Edit, Grep, Glob, Task, Bash(app/.venv/Scripts/python.exe -m pytest:*), Bash(./.venv/Scripts/python.exe -m pytest:*)
---

Contratto da aggiornare: **$ARGUMENTS**

Lo stesso contratto è descritto in quattro punti. Cambiarne uno solo produce un
`AgentFailure` dopo due retry: token spesi, fallback silenzioso, nessun errore
visibile in test.

## Ordine di modifica

1. **Schema** — `agents/schemas/<artefatto>.schema.json`. È la fonte di verità.
   Un campo che il codice legge con `[...]` va in `required`; un campo
   opzionale si legge con `.get()`. Decidi qui, non dopo.
2. **System prompt** — `agents/subagents/<agente>.md`. Aggiorna la riga
   `Output:` e le sezioni che descrivono i campi. Quel file è letto da
   `_load_instructions()`: è documentazione e prompt insieme, non una copia.
3. **Codice** — `app/orchestrator.py` per la costruzione del payload e la
   lettura del risultato, `app/main.py` se il campo esce dall'API. Se il
   payload cresce, taglia altrove: il contratto in ingresso è anche un budget.
4. **Configurazione** — `agents/config/models.yaml`, `max_output_tokens`
   dell'agente, se il nuovo campo allunga la risposta.

## Verifica

- Invoca il subagente `coerenza-contratti` sull'artefatto toccato.
- Se il campo contiene testo destinato all'utente, invoca `revisore-confine`.
- `app/.venv/Scripts/python.exe -m pytest tests/ -q` dalla cartella `app/`.

## Attenzione

- Un campo aggiunto a `explanation.json` che il guardrail non legge è testo che
  raggiunge l'utente senza verdetto: se è prosa, va dentro ciò che il guardrail
  riceve in `content`.
- `_settings()` normalizza il nome dell'agente con `replace("-", "_")`: in
  `models.yaml` la entry è `concept_mapper`, non `concept-mapper`.
- Rimuovere un campo da `required` è retrocompatibile, aggiungerlo no: gli
  artefatti già scritti in `state/` diventano invalidi.
