---
description: Aggiunge uno scenario di simulazione deterministico a finance.py, lo registra e lo copre con i test.
argument-hint: <nome_funzione> — cosa deve mostrare all'utente
allowed-tools: Read, Edit, Grep, Glob, Bash(app/.venv/Scripts/python.exe -m pytest:*), Bash(./.venv/Scripts/python.exe -m pytest:*)
---

Scenario da aggiungere: **$ARGUMENTS**

Uno scenario è matematica, non un prompt. L'LLM lo riceve già calcolato e lo
racconta: un errore aritmetico qui è indistinguibile da una bugia, per chi
legge.

## Passi

1. Leggi `app/finance.py` e imita la funzione esistente più vicina. Vincoli non
   negoziabili: `Decimal` internamente, `_money()` in uscita, tasso mensile via
   `_monthly_rate()` (mai `annual_rate / 12`), `_validate()` su mesi e tassi.
2. Scrivi la funzione pura. Firma tipizzata, ritorno `list[SeriesPoint]` oppure
   `tuple[list[SeriesPoint], dict[str, float]]` se c'è un riepilogo. Ogni
   parametro fuori dominio alza `SimulationError` con un messaggio che dice
   cosa è sbagliato, senza suggerire cosa fare.
3. Registra la funzione in `SCENARIOS`. La chiave è ciò che il frontend invia
   come `scenario_type`: `Pipeline.simulate()` rifiuta tutto il resto.
4. Se il ritorno include un riepilogo, verifica che `simulate()` in
   `app/orchestrator.py` lo instradi (`outcome if isinstance(outcome, tuple)`)
   e che `simulation.schema.json` ammetta le chiavi del `summary`.
5. Test in `app/tests/test_finance.py`, quattro casi minimi: valore atteso
   calcolato a mano, orizzonte lungo con inflazione, boundary (`months=1`,
   tasso 0), ogni ramo di `SimulationError`. Confronta con `pytest.approx` sui
   centesimi, non su float grezzi.
6. Esegui `app/.venv/Scripts/python.exe -m pytest tests/ -q` dalla cartella
   `app/` e riporta il conteggio.

## Da non fare

- Non stimare un parametro al posto dell'utente: gli scenari sono impostati da
  lui (`set_by: "user"`), un default nascosto è una scelta fatta per lui.
- Non far calcolare nulla al `simulator`: se il numero non esce da
  `finance.py`, non esiste.
- Niente docstring che spiega quando conviene usare lo scenario.
