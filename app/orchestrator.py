"""Pipeline di Conti Chiari.

Implementa la sequenza descritta in agents/orchestrator.md. Non interpreta dati
e non produce testo: decide chi gira, con quale fetta di stato, e cosa succede
quando qualcosa fallisce.

Invariante: nessun artefatto testuale esce da qui senza un verdetto `pass` del
guardrail.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from agents_runtime import AGENTS_DIR, AgentFailure, AgentRuntime, RunLog, _load_config
from finance import SCENARIOS, SimulationError, quadro_annuale

log = logging.getLogger("conti-chiari.pipeline")

STATE_ROOT = Path(__file__).resolve().parent.parent / "state"


class Blocked(Exception):
    """Il guardrail ha bloccato l'artefatto. Non è un errore tecnico."""

    def __init__(self, violations: list[dict]) -> None:
        super().__init__("Contenuto bloccato dal guardrail.")
        self.violations = violations


class Pipeline:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.dir = STATE_ROOT / session_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.run_log = RunLog(path=self.dir / "run.log")
        self.limits = _load_config()["limits"]
        self._runtime: AgentRuntime | None = None

    @property
    def runtime(self) -> AgentRuntime:
        """Costruito al primo uso.

        Il parsing del CSV e la lettura dello stato non richiedono il modello:
        senza questa pigrizia una chiave mancante farebbe fallire anche il
        semplice caricamento del file.
        """
        if self._runtime is None:
            self._runtime = AgentRuntime(self.run_log)
        return self._runtime

    # ---------- stato su disco ----------

    def write(self, name: str, data: Any) -> None:
        (self.dir / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def read(self, name: str) -> Any:
        return json.loads((self.dir / name).read_text(encoding="utf-8"))

    def has(self, name: str) -> bool:
        return (self.dir / name).exists()

    # ---------- step 2: categorizzazione ----------

    def categorize(self) -> dict:
        transactions = self.read("transactions.json")
        batch_size = self.runtime.config["agents"]["categorizer"]["batch_size"]
        rows = transactions["transactions"]

        merged: dict[str, Any] = {
            "session_id": self.session_id,
            "categories": [],
            "recurring": [],
            "fees": [],
            "totals": {"income": 0.0, "expense": 0.0, "net": 0.0},
            "uncategorized": {"count": 0, "total": 0.0, "transaction_ids": []},
            "needs_human_review": [],
        }

        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            payload = {
                "session_id": self.session_id,
                "period": transactions["period"],
                "transactions": batch,
            }
            try:
                partial = self.runtime.run("categorizer", payload, "analysis")
            except AgentFailure as exc:
                # Fallback documentato: 50 voci non classificate, mai inventate.
                log.warning("categorizer batch fallito (%s), voci in uncategorized", exc.reason)
                merged["uncategorized"]["transaction_ids"].extend(t["id"] for t in batch)
                merged["uncategorized"]["count"] += len(batch)
                merged["uncategorized"]["total"] += sum(t["amount"] for t in batch)
                continue
            _merge_analysis(merged, partial)

        _recompute_totals(merged, rows)
        self.write("analysis.json", merged)
        return merged

    # ---------- step 4: selezione dei concetti ----------

    def map_concepts(self, literacy_level: str) -> dict:
        analysis = self.read("analysis.json")
        payload = {
            "session_id": self.session_id,
            "literacy_level": literacy_level,
            "categories": analysis["categories"],
            "recurring": analysis["recurring"],
            "fees": analysis["fees"],
            "totals": analysis["totals"],
        }
        try:
            concepts = self.runtime.run("concept-mapper", payload, "concepts")
        except AgentFailure:
            concepts = _fallback_concepts(self.session_id, literacy_level, analysis)
        self.write("concepts.json", concepts)
        return concepts

    # ---------- step 5-6: spiegazione con revisione ----------

    def explain(self) -> dict:
        concepts = self.read("concepts.json")
        analysis = self.read("analysis.json")
        transactions = {t["id"]: t for t in self.read("transactions.json")["transactions"]}

        approved: list[dict] = []
        blocked: list[dict] = []

        for index, concept in enumerate(concepts["concepts"]):
            payload = {
                "session_id": self.session_id,
                "literacy_level": concepts["literacy_level"],
                "concept": concept,
                # Token: solo le transazioni di evidenza, non l'intero analysis.
                "evidence": [
                    transactions[tid]
                    for tid in concept["evidence_transaction_ids"]
                    if tid in transactions
                ],
                "aggregates": _relevant_aggregates(analysis, concept),
                "glossario": _glossario_per([concept["id"]]),
            }
            try:
                section = self._explain_section(payload, index)
            except Blocked as exc:
                blocked.append({"concept_id": concept["id"], "violations": exc.violations})
            except AgentFailure:
                blocked.append({"concept_id": concept["id"], "violations": [], "unavailable": True})
            else:
                approved.append(section)

        explanation = {
            "session_id": self.session_id,
            "literacy_level": concepts["literacy_level"],
            "sections": approved,
        }
        self.write("explanation.json", explanation)
        if blocked:
            self.write("blocked.json", blocked)
        return explanation

    def _explain_section(self, payload: dict, index: int) -> dict:
        """Ciclo explainer -> guardrail, massimo 2 revisioni poi block."""
        max_cycles = self.limits["revision_cycles_max"]
        revision: list[dict] | None = None

        for cycle in range(max_cycles + 1):
            request = dict(payload)
            if revision:
                request["revision"] = {"cycle": cycle, "violations": revision}

            result = self.runtime.run("explainer", request, "explanation")
            section = result["sections"][0]
            verdict = self._review("explanation.json", index, section, payload)

            if verdict["verdict"] == "pass":
                return section
            if verdict["verdict"] == "block" or cycle == max_cycles:
                raise Blocked(verdict["violations"])
            revision = verdict["violations"]

        raise Blocked([])

    def _review(self, artifact: str, index: int, content: dict, sources: dict) -> dict:
        payload = {
            "session_id": self.session_id,
            "target": {"artifact": artifact, "section_index": index},
            "content": content,
            "sources": sources,
            # Le cifre con source.kind "riferimento" sono soglie normative: il
            # guardrail le verifica contro il glossario, non contro i dati. Si
            # allegano solo le voci citate, non l'intero glossario.
            "riferimenti": _glossario_per(
                ref
                for number in content.get("user_numbers", [])
                if number["source"]["kind"] == "riferimento"
                for ref in number["source"]["ref"]
            ),
        }
        try:
            verdict = self.runtime.run("guardrail", payload, "guardrail-verdict")
        except AgentFailure:
            # Guardrail non disponibile: in dubbio non si passa.
            return {
                "verdict": "block",
                "violations": [
                    {
                        "rule_id": "NO_PERSONALIZED_ADVICE",
                        "severity": "block",
                        "quote": "",
                        "reason": "Verifica non completata: contenuto non mostrabile.",
                        "suggested_fix": "Ripetere la verifica.",
                    }
                ],
                "escalate_to_human": True,
            }
        self.write(f"verdict-{artifact.replace('.json', '')}-{index}.json", verdict)
        return verdict

    # ---------- step 7-8: simulazione ----------

    def simulate(self, scenario_type: str, params: dict[str, float]) -> dict:
        if scenario_type not in SCENARIOS:
            raise SimulationError(f"Scenario non ammesso: {scenario_type}")

        compute = SCENARIOS[scenario_type]
        outcome = compute(**params)
        series, summary = outcome if isinstance(outcome, tuple) else (outcome, None)

        payload = {
            "session_id": self.session_id,
            "scenario": {"type": scenario_type, "params": params, "set_by": "user"},
            "computed_by": "deterministic",
            "series": _downsample(series),
            "summary": summary,
        }
        simulation = self.runtime.run("simulator", payload, "simulation")
        simulation["series"] = series
        simulation["computed_by"] = "deterministic"
        simulation["scenario"]["set_by"] = "user"

        verdict = self._review("simulation.json", 0, simulation, payload)
        if verdict["verdict"] != "pass":
            raise Blocked(verdict["violations"])

        self.write("simulation.json", simulation)
        return simulation

    # ---------- perimetro dei dati ----------

    def find_gaps(self) -> dict:
        """Cosa l'estratto non può mostrare, data la finestra osservata."""
        transactions = self.read("transactions.json")
        analysis = self.read("analysis.json")
        checklist = json.loads(
            (
                AGENTS_DIR / "skills" / "spese-ricorrenti-tipiche" / "checklist.json"
            ).read_text(encoding="utf-8")
        )

        payload = {
            "session_id": self.session_id,
            "period_months": transactions["period"]["months"],
            # Token: descrizioni distinte, non le transazioni complete.
            "descriptions": sorted({t["description"] for t in transactions["transactions"]}),
            "categories": [c["name"] for c in analysis["categories"]],
            "checklist": checklist["voci"],
        }
        try:
            gaps = self.runtime.run("completeness", payload, "gaps")
        except AgentFailure:
            gaps = {
                "session_id": self.session_id,
                "period_months": transactions["period"]["months"],
                "gaps": [],
                "coverage_note": (
                    f"Il file copre {transactions['period']['months']} mesi. "
                    "Le spese che ricorrono una volta l'anno potrebbero non comparire."
                ),
            }
        self.write("gaps.json", gaps)
        return gaps

    def apply_gap_answers(self, annual_costs: dict[str, float]) -> dict:
        """Ricalcola il quadro mensile con i costi dichiarati dall'utente.

        Calcolo deterministico: nessun modello interviene sui numeri.
        """
        analysis = self.read("analysis.json")
        transactions = self.read("transactions.json")

        # Un gap `dato_opaco` descrive una spesa già presente nei totali di cui
        # non si conosce la destinazione. Sommarla ai costi annuali la
        # conteggerebbe due volte: l'endpoint è pubblico, quindi si filtra qui e
        # non solo nella UI.
        if self.has("gaps.json"):
            opachi = {
                g["id"] for g in self.read("gaps.json")["gaps"]
                if g["reason"] == "dato_opaco"
            }
            ignorati = sorted(set(annual_costs) & opachi)
            if ignorati:
                log.info("ignorati costi su gap dato_opaco: %s", ignorati)
            annual_costs = {k: v for k, v in annual_costs.items() if k not in opachi}

        quadro = quadro_annuale(
            net_in_period=analysis["totals"]["net"],
            period_months=transactions["period"]["months"],
            annual_costs=annual_costs,
        )
        self.write("quadro.json", quadro)
        return quadro

    # ---------- domanda libera ----------

    def ask(self, question: str) -> dict:
        """Domanda aperta dell'utente.

        Passa per lo stesso guardrail delle sezioni: il confine non è un filtro
        di parole chiave applicato all'input, è una valutazione della risposta.
        """
        concepts = self.read("concepts.json")
        analysis = self.read("analysis.json")
        transactions = {t["id"]: t for t in self.read("transactions.json")["transactions"]}
        concept = concepts["concepts"][0]

        payload = {
            "session_id": self.session_id,
            "literacy_level": concepts["literacy_level"],
            "question": question,
            "concept": concept,
            "available_concepts": [c["id"] for c in concepts["concepts"]],
            "glossario": _glossario_per(c["id"] for c in concepts["concepts"]),
            "evidence": [
                transactions[tid]
                for tid in concept["evidence_transaction_ids"]
                if tid in transactions
            ],
            "aggregates": _relevant_aggregates(analysis, concept),
        }

        draft = self.runtime.run("explainer", payload, "explanation")
        section = draft["sections"][0]
        verdict = self._review("chat_reply", 0, section, payload)

        return {
            "verdict": verdict["verdict"],
            "section": section if verdict["verdict"] == "pass" else None,
            "violations": verdict.get("violations", []),
            "escalated": verdict.get("escalate_to_human", False),
        }

    # ---------- step 9: verifica di comprensione ----------

    def quiz(self) -> dict | None:
        concepts = self.read("concepts.json")
        explanation = self.read("explanation.json")
        payload = {
            "session_id": self.session_id,
            "concepts": concepts["concepts"],
            "approved_numbers": [
                number
                for section in explanation["sections"]
                for number in section["user_numbers"]
            ],
        }
        try:
            quiz = self.runtime.run("comprehension", payload, "quiz")
        except AgentFailure:
            # Il percorso resta valido senza verifica; un quiz inventato no.
            return None
        self.write("quiz.json", quiz)
        return quiz


# ---------- helper puri ----------


def _merge_analysis(target: dict, partial: dict) -> None:
    by_name = {c["name"]: c for c in target["categories"]}
    for category in partial.get("categories", []):
        existing = by_name.get(category["name"])
        if existing:
            existing["total"] += category["total"]
            existing["count"] += category["count"]
            existing["transaction_ids"].extend(category["transaction_ids"])
        else:
            by_name[category["name"]] = dict(category)
    target["categories"] = list(by_name.values())

    target["recurring"].extend(partial.get("recurring", []))
    target["fees"].extend(partial.get("fees", []))
    target["needs_human_review"].extend(partial.get("needs_human_review", []))

    unc = partial.get("uncategorized", {})
    target["uncategorized"]["count"] += unc.get("count", 0)
    target["uncategorized"]["total"] += unc.get("total", 0.0)
    target["uncategorized"]["transaction_ids"].extend(unc.get("transaction_ids", []))


def _recompute_totals(analysis: dict, rows: list[dict]) -> None:
    """I totali sono aritmetica: non si delegano al modello."""
    income = sum(t["amount"] for t in rows if t["amount"] > 0)
    expense = sum(t["amount"] for t in rows if t["amount"] < 0)
    analysis["totals"] = {
        "income": round(income, 2),
        "expense": round(expense, 2),
        "net": round(income + expense, 2),
    }
    total_expense = abs(expense) or 1.0
    for category in analysis["categories"]:
        category["total"] = round(category["total"], 2)
        category["share"] = round(min(abs(category["total"]) / total_expense, 1.0), 4)


def _glossario_per(concept_ids) -> list[dict]:
    """Voci di glossario richieste, non tutto il glossario.

    Serve all'explainer per le definizioni e al guardrail per verificare le
    soglie normative citate. Allegarlo intero costerebbe token a ogni sezione.
    """
    wanted = set(concept_ids)
    if not wanted:
        return []
    voci = json.loads(
        (AGENTS_DIR / "skills" / "glossario-finanziario" / "concetti.json").read_text(
            encoding="utf-8"
        )
    )["concetti"]
    return [c for c in voci if c["id"] in wanted]


def _relevant_aggregates(analysis: dict, concept: dict) -> dict:
    ids = set(concept["evidence_transaction_ids"])
    return {
        "fees": [f for f in analysis["fees"] if set(f["transaction_ids"]) & ids],
        "recurring": [r for r in analysis["recurring"] if set(r["transaction_ids"]) & ids],
        "totals": analysis["totals"],
    }


def _fallback_concepts(session_id: str, literacy_level: str, analysis: dict) -> dict:
    """Mai un array vuoto: il percorso educativo deve poter partire."""
    first_ids = next(
        (c["transaction_ids"][:1] for c in analysis["categories"] if c["transaction_ids"]),
        ["t001"],
    )
    base = [
        ("entrate-uscite", "Entrate e uscite", "punto di partenza di ogni lettura del conto"),
        ("costo-ricorrente", "Costo ricorrente", "voce presente in quasi tutti gli estratti"),
    ]
    return {
        "session_id": session_id,
        "literacy_level": literacy_level,
        "concepts": [
            {
                "id": cid,
                "label": label,
                "priority": i + 1,
                "why_relevant": why,
                "evidence_transaction_ids": first_ids,
            }
            for i, (cid, label, why) in enumerate(base)
        ],
    }


def _downsample(series: list[dict], keep: int = 12) -> list[dict]:
    """Il simulator narra la curva: non gli servono 360 punti."""
    if len(series) <= keep:
        return series
    step = len(series) // keep
    sampled = series[::step]
    if sampled[-1] is not series[-1]:
        sampled.append(series[-1])
    return sampled
