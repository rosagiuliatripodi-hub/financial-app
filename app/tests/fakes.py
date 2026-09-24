"""Runtime finto per testare l'orchestrazione senza chiamare il modello.

Si innesta sul seam che la Pipeline ha già: `runtime` è una property lazy, quindi
basta valorizzare `_runtime` prima del primo uso. Nessuna modifica al codice di
produzione.

Attenzione a cosa questi test dimostrano: verificano che **l'orchestrazione**
reagisca correttamente agli esiti degli agenti (fallback, revisione, blocco).
Non dimostrano che i prompt reali producano output conforme agli schemi: quello
richiede una chiave e una esecuzione vera.
"""

from __future__ import annotations

import json
from pathlib import Path

from agents_runtime import AgentFailure, RunLog

AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "agents"


class FakeRuntime:
    """Restituisce risposte preimpostate e registra le chiamate ricevute.

    Per ogni agente si può impostare:
      - un dict            -> restituito sempre
      - una lista di dict  -> consumata in ordine, una per chiamata
      - un'eccezione       -> sollevata
      - una callable       -> invocata con (payload, n_chiamata)
    """

    def __init__(self, responses: dict, config: dict | None = None) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []
        self.run_log = RunLog()
        self.config = config or {
            "agents": {"categorizer": {"batch_size": 50}},
            "limits": {"revision_cycles_max": 2},
        }

    def count(self, agent: str) -> int:
        return sum(1 for name, _ in self.calls if name == agent)

    def run(self, agent: str, payload: dict, schema_name: str) -> dict:
        self.calls.append((agent, payload))
        if agent not in self.responses:
            raise AssertionError(f"agente non previsto dal test: {agent}")

        spec = self.responses[agent]
        if isinstance(spec, Exception):
            raise spec
        if callable(spec):
            return spec(payload, self.count(agent))
        if isinstance(spec, list):
            index = min(self.count(agent) - 1, len(spec) - 1)
            item = spec[index]
            if isinstance(item, Exception):
                raise item
            return item
        return spec


# ---------- artefatti minimi ma conformi agli schemi ----------


def transactions(session_id: str = "s1", count: int = 3) -> dict:
    rows = [
        {"id": f"t{i:03d}", "date": f"2026-01-{i:02d}", "description": f"MOVIMENTO {i}", "amount": -10.0 * i}
        for i in range(1, count + 1)
    ]
    rows[0]["amount"] = 1800.0
    rows[0]["description"] = "ACCREDITO STIPENDIO"
    return {
        "session_id": session_id,
        "source": {"filename": "x.csv", "rows_total": count, "rows_parsed": count,
                   "rows_rejected": 0, "dialect": "it-standard"},
        "period": {"from": "2026-01-01", "to": "2026-03-31", "months": 2.9},
        "currency": "EUR",
        "transactions": rows,
        "rejected": [],
    }


def analysis(session_id: str = "s1") -> dict:
    return {
        "session_id": session_id,
        "categories": [
            {"name": "Entrate", "total": 1800.0, "count": 1, "share": 0.0, "transaction_ids": ["t001"]},
            {"name": "Casa", "total": -50.0, "count": 2, "share": 1.0, "transaction_ids": ["t002", "t003"]},
        ],
        "recurring": [],
        "fees": [{"label": "Imposta di bollo", "amount": -8.55,
                  "concept_id": "imposta-bollo", "transaction_ids": ["t002"]}],
        "totals": {"income": 1800.0, "expense": -50.0, "net": 1750.0},
        "uncategorized": {"count": 0, "total": 0.0, "transaction_ids": []},
        "needs_human_review": [],
    }


def concepts(session_id: str = "s1", n: int = 1) -> dict:
    return {
        "session_id": session_id,
        "literacy_level": "base",
        "concepts": [
            {"id": "imposta-bollo", "label": "Imposta di bollo", "priority": i + 1,
             "why_relevant": "compare 2 volte", "evidence_transaction_ids": ["t002"]}
            for i in range(n)
        ],
    }


def explanation_section(text: str = "L'imposta di bollo e una tassa dello Stato.") -> dict:
    return {
        "session_id": "s1",
        "literacy_level": "base",
        "sections": [{
            "concept_id": "imposta-bollo",
            "title": "L'imposta di bollo",
            "plain_text": text,
            "user_numbers": [{"label": "Imposta di bollo", "value": -8.55,
                              "source": {"kind": "transaction", "ref": ["t002"]}}],
        }],
    }


def verdict(state: str = "pass", rule: str = "NO_INVESTMENT_ADVICE") -> dict:
    violations = [] if state == "pass" else [{
        "rule_id": rule,
        "severity": "block" if state == "block" else "revise",
        "quote": "ti conviene",
        "reason": "orienta una decisione",
        "suggested_fix": "descrivi il fatto senza suggerire",
    }]
    return {
        "session_id": "s1",
        "target": {"artifact": "explanation.json", "section_index": 0},
        "verdict": state,
        "violations": violations,
        "numeric_integrity": {"checked": 1, "mismatches": []},
        "escalate_to_human": False,
    }


def seed(pipeline, **artifacts) -> None:
    """Scrive gli artefatti di partenza nello stato della sessione."""
    defaults = {"transactions.json": transactions(), "analysis.json": analysis()}
    defaults.update(artifacts)
    for name, data in defaults.items():
        pipeline.write(name, data)


def load_schema(name: str) -> dict:
    return json.loads((AGENTS_DIR / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))
