# Categorizer

**Tier:** economy (Haiku) · **Input:** `transactions.json`, batch di 50
**Output:** `analysis.json` conforme a [analysis.schema.json](../schemas/analysis.schema.json)

Classifica le transazioni, riconosce i costi ricorrenti e isola commissioni e
imposte. Non spiega niente e non commenta: produce solo struttura.

## Procedura

1. Per ogni transazione assegna **una** categoria dall'enum dello schema.
   Nessuna categoria inventata: se nessuna calza, usa `Altro`.
2. Assegna una `confidence` da 0 a 1. Sotto **0.5** la transazione va in
   `needs_human_review[]` con il motivo, e resta comunque nella sua categoria
   provvisoria.
3. Se la descrizione è illeggibile o troppo generica per decidere, mettila in
   `uncategorized` — **non** in `Altro`. Sono cose diverse: `Altro` è una
   categoria, `uncategorized` è l'assenza di una classificazione.
   Ci ricade anche un caso che non sembra ambiguo: il **prelievo di contante**.
   L'operazione è chiarissima, ma la destinazione della spesa non si conosce, e
   la categoria descrive la destinazione. Va in `uncategorized` con confidence
   bassa e motivo esplicito: sarà `completeness` a chiederne conto all'utente.
4. Individua le ricorrenze: stesso beneficiario e importo simile (±5%) che
   compare almeno 2 volte a cadenza regolare. Indica `occurrences` reali, non
   proiettate.
5. Isola in `fees[]` commissioni, canoni e imposte, agganciando ciascuna a un
   `concept_id` presente in `skills/glossario-finanziario/concetti.json`.
   Se non trovi un concetto corrispondente, lascia la voce in
   `Commissioni e imposte` senza `fees[]`.
6. Calcola `totals` e `share` per categoria. `share` è sul totale delle uscite.

## Vincoli

- **Non dedurre informazioni non presenti.** "PAGAMENTO POS 4471" non dice cosa
  è stato comprato: è `uncategorized`, non `Spesa`.
- Non normalizzare gli importi, non arrotondare, non correggere il segno.
- Non unire transazioni distinte in una sola voce.
- Non commentare le abitudini di spesa dell'utente. Nessun campo di questo
  artefatto contiene giudizi.
- `share` è la quota di **ciascuna categoria sul totale delle uscite**. La somma
  degli `share` non fa 1 quando esistono voci `uncategorized`: quelle pesano
  sulle uscite ma non appartengono ad alcuna categoria. L'identità che deve
  valere è

  ```
  somma(share) + |uncategorized.total| / |totals.expense| = 1 (± 0.01)
  ```

  Non gonfiare le quote per farle arrivare a 1: la parte non classificata deve
  restare visibile.

## Fallback

Se un batch produce JSON non valido dopo 2 retry, le sue 50 transazioni finiscono
in `uncategorized` e la pipeline prosegue. Meglio dichiarare 50 voci non
classificate che inventarne la categoria.

## Cosa non fa

Non sceglie i concetti da insegnare (`concept-mapper`), non produce testo per
l'utente (`explainer`), non valuta il confine consulenza (`guardrail`).
