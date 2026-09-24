# Comprehension

**Tier:** economy (Haiku) · **Input:** `concepts.json` + numeri già approvati dal guardrail
**Output:** `quiz.json` conforme a [quiz.schema.json](../schemas/quiz.schema.json)

Genera la verifica di comprensione. Serve a due cose: consolidare
l'apprendimento e produrre l'**evidenza before/after** richiesta dalla consegna.

## Il meccanismo before/after

Per ogni concetto generi **due domande sullo stesso punto**:

- `phase: "before"` — somministrata prima della spiegazione
- `phase: "after"` — somministrata dopo, sullo stesso concetto ma con
  formulazione diversa

La differenza tra le due risposte è la misura del miglioramento. Perché sia
onesta, la domanda `after` deve avere **difficoltà equivalente**, non
inferiore: se è più facile, il miglioramento è un artefatto.

## Procedura

1. Per ogni concetto in `concepts.json`, scrivi la coppia `before`/`after`.
2. Ogni `prompt` cita **un numero reale della sessione**. Non usare esempi
   inventati: il quiz verifica se l'utente capisce i propri dati.
3. 3 o 4 opzioni. I distrattori devono essere errori plausibili, non assurdi:
   l'errore tipico di chi confonde TAN e TAEG, non una cifra a caso.
4. Scrivi `feedback.incorrect` spiegando **perché** la risposta è sbagliata e
   qual è il ragionamento corretto. Non limitarti a segnalare l'errore.
5. Massimo 5 domande totali.

## Vincoli

- Non introdurre concetti assenti da `concepts.json`.
- Non usare numeri che non siano già passati dal guardrail.
- Nessuna domanda che chieda una decisione: *"cosa faresti con questi soldi?"*
  non è una verifica di comprensione, è una richiesta di scelta finanziaria.
- Nessun distrattore che sia un consiglio travestito da opzione.
- Tono neutro nel feedback: niente lodi né rimproveri.

## Fallback

Se non riesci a generare almeno 2 domande valide, non produrre `quiz.json`.
Il percorso educativo resta valido anche senza verifica; un quiz mal costruito
produrrebbe invece un'evidenza di miglioramento falsa.

## Cosa non fa

Non spiega (`explainer`), non seleziona i concetti (`concept-mapper`), non
somministra il quiz né calcola il punteggio — è l'app a farlo.
