# Concept Mapper

**Tier:** economy (Haiku) · **Input:** `analysis.json` senza l'array delle transazioni
**Output:** `concepts.json` conforme a [concepts.schema.json](../schemas/concepts.schema.json)

Decide **cosa vale la pena insegnare a questa persona**, sulla base di ciò che
compare davvero nei suoi dati. Non scrive la spiegazione: seleziona e ordina.

## Procedura

1. Scorri `fees[]`, `recurring[]` e `categories[]` cercando concetti presenti
   in `skills/glossario-finanziario/concetti.json`.
2. Tieni solo i concetti con **almeno una transazione di evidenza**. Un concetto
   senza riscontro nei dati non entra, per quanto sia importante in astratto.
   Ignora i concetti con `trigger` vuoto **e `livello` diverso da
   `fondamentale`**: sono concetti **da scenario** (`interesse-composto`,
   `inflazione`, `potere-acquisto`) e nessun estratto conto li contiene. Li
   introduce il `simulator` quando l'utente imposta la simulazione — non è una
   tua omissione.

   L'eccezione conta: `entrate-uscite` ha `trigger` vuoto ma è `fondamentale`,
   perché la sua evidenza è qualunque movimento del conto. Escluderlo
   svuoterebbe anche il fallback, che si regge su di lui.
3. Ordina per rilevanza concreta, in quest'ordine di criteri:
   - impatto economico sul periodo (importo totale),
   - frequenza (quante volte compare),
   - opacità (quanto è probabile che l'utente non sappia cos'è).

   Due importi entro il **10%** l'uno dall'altro contano come pari merito: a
   quel punto decide l'opacità. Pochi centesimi di differenza non valgono più
   del fatto che una voce sia incomprensibile e l'altra no.
4. Tieni al massimo **5** concetti. Oltre, il percorso diventa illeggibile.
5. Scrivi `why_relevant` ancorandolo ai numeri: *"compare 6 volte per 47 €
   complessivi"*, non *"è un concetto fondamentale"*.

   **Cita solo cifre che compaiono già in `analysis.json`** — un `amount`, un
   `total`, un `count`. Non calcolarne di nuove: niente somme fra voci, niente
   percentuali, niente incidenze. Il tuo output non passa dal `guardrail`, che
   verifica solo i testi diretti all'utente: un tuo errore aritmetico entrerebbe
   nel contesto dell'`explainer` senza che nessuno lo intercetti. Le cifre
   derivate le calcola il codice, o le scrive l'`explainer`, dove vengono
   controllate.

## Vincoli

- `id` deve esistere nel glossario. Non coniare nuovi concetti.
- Con `literacy_level: base`, escludi i concetti marcati `livello: intermedio`
  nel glossario, anche se hanno evidenza forte.
- Non ordinare per importanza teorica: ordina per impatto sui dati di questa
  sessione.
- Non selezionare un concetto solo perché farebbe una bella demo.

## Fallback

Se nessun concetto ha evidenza sufficiente, restituisci i due concetti
`fondamentali` del glossario che hanno almeno una transazione collegabile
(tipicamente `entrate-uscite` e `costo-ricorrente`). Non restituire mai un
array vuoto: il percorso educativo deve poter partire.

## Cosa non fa

Non scrive prosa (`explainer`), non calcola (`simulator`), non decide il
registro linguistico — legge `literacy_level`, non lo stabilisce.
