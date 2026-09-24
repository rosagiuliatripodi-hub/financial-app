---
description: Controllo completo prima di presentare o consegnare: test, confine consulenza, contratti, segreti, invarianti dell'orchestratore.
argument-hint: [file o cartella da restringere, vuoto = tutto il repo]
allowed-tools: Read, Grep, Glob, Task, Bash(app/.venv/Scripts/python.exe -m pytest:*), Bash(./.venv/Scripts/python.exe -m pytest:*), Bash(git status:*), Bash(git diff:*)
---

Perimetro: **$ARGUMENTS** (se vuoto, tutto il repo).

Esegui i cinque controlli, nell'ordine. Non fermarti al primo fallimento:
serve il quadro completo.

1. **Test.** Dalla cartella `app/`:
   `./.venv/Scripts/python.exe -m pytest tests/ -q`. Riporta il conteggio.
2. **Confine consulenza.** Invoca il subagente `revisore-confine` sul
   perimetro. Ogni reperto `block` è bloccante per la consegna: il tema vieta
   esplicitamente la consulenza finanziaria.
3. **Contratti.** Invoca il subagente `coerenza-contratti`.
4. **Segreti.** Verifica che `app/.env` non sia tracciato e che nessuna chiave
   compaia nel sorgente: cerca `sk-ant` e `ANTHROPIC_API_KEY\s*=` sotto `app/`
   e `agents/`. In `models.yaml` deve esserci solo il **nome** della variabile.
5. **Invarianti dell'orchestratore.** Rileggi le cinque invarianti in
   `agents/orchestrator.md` e verifica a codice, in `app/orchestrator.py`, che
   ognuna regga. La prima in particolare: nessun artefatto testuale raggiunge
   l'utente senza `verdict: pass` — inclusa la risposta di `ask()`.

## Referto

Una tabella `controllo | esito | dettaglio`, poi una sola riga di giudizio:
`pronto` oppure l'elenco di cosa manca. Non correggere nulla senza che ti venga
chiesto: qui si misura, non si ripara.
