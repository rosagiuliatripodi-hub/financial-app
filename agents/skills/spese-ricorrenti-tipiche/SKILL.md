---
name: spese-ricorrenti-tipiche
description: Catalogo delle voci di spesa ricorrenti di una famiglia italiana, con la loro cadenza reale e la finestra di osservazione minima per vederle. Usato dall'agente completeness per capire quali costi mancano dall'estratto perché fuori periodo, e per formulare la domanda giusta all'utente.
---

# Spese ricorrenti tipiche

Serve a rispondere a una domanda precisa: **quali costi questa persona ha
quasi certamente, ma non compaiono nel file che ha caricato?**

I dati stanno in [`checklist.json`](checklist.json).

## Il problema che risolve

Un estratto conto di tre mesi non contiene i costi annuali. Assicurazione auto,
bollo, revisione, IMU, TARI, canone RAI: cadono una o due volte l'anno e in una
finestra trimestrale sono invisibili per costruzione.

Chi legge un estratto trimestrale e conclude *"avanzo 350 € al mese"* commette un
errore sistematico, e non ha modo di accorgersene. Rendere visibile il perimetro
dei dati è il contributo educativo più alto che il sistema può dare — e non
richiede di dare un solo consiglio.

## Struttura di una voce

| Campo | Significato |
|---|---|
| `id` | chiave stabile |
| `label` | nome leggibile |
| `cadenza` | `mensile`, `bimestrale`, `trimestrale`, `semestrale`, `annuale`, `biennale` |
| `finestra_minima_mesi` | mesi di estratto necessari per avere una probabilità ragionevole di vederla |
| `indizi` | stringhe che, se presenti nelle descrizioni, indicano che la voce **c'è già** |
| `presupposto` | condizione che rende la voce pertinente (`auto`, `casa_proprieta`, `casa_affitto`, `sempre`) |
| `rivelatori` | categorie o voci la cui presenza suggerisce il presupposto (es. carburante → possiede un'auto) |
| `domanda` | come chiedere all'utente, in forma neutra |
| `concetto_collegato` | id nel glossario finanziario, se insegnabile |

## Regole d'uso

1. Una voce è **mancante** solo se: il presupposto è plausibile, nessun `indizio`
   compare nelle descrizioni, e `finestra_minima_mesi` supera il periodo coperto
   dall'estratto.
2. Se il periodo è abbastanza lungo e la voce comunque non c'è, **non è
   mancante**: è assente. L'utente semplicemente non ha quel costo. Non
   insistere.
3. I `rivelatori` sono indizi probabilistici, non prove. Servono a formulare una
   domanda condizionale (*"se hai un'auto…"*), mai un'affermazione.
4. Le `domanda` sono già scritte in forma neutra. L'agente le adatta al tono,
   non ne cambia la natura.

## Il vincolo che non si negozia

Questa skill serve a **chiedere**, non a consigliare.

| Ammesso | Vietato |
|---|---|
| "Non vedo costi per un'auto: ne hai una?" | "Dovresti mettere da parte per l'assicurazione" |
| "Il bollo è annuale, in 3 mesi non si vede" | "Conviene pagarlo a rate" |
| "Vuoi aggiungere questa spesa al quadro?" | "È buona pratica tenere un fondo per le spese impreviste" |

Una domanda non è mai un consiglio. Una "best practice" lo è quasi sempre: è una
raccomandazione su cosa fare dei propri soldi, e il tema la vieta
esplicitamente. Se serve trasmettere un principio, lo si fa insegnando il
concetto — non prescrivendo un comportamento.
