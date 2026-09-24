"""Runtime degli agenti: tiering, retry, validazione, contabilità token.

Le istruzioni non sono duplicate qui: i system prompt sono i file in
`agents/subagents/*.md`, gli stessi che documentano il sistema. Un'istruzione
modificata nella documentazione cambia il comportamento, senza disallineamenti.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from anthropic import Anthropic, APIStatusError, APITimeoutError
from jsonschema import Draft202012Validator, ValidationError

log = logging.getLogger("conti-chiari.runtime")

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"


class AgentFailure(RuntimeError):
    """L'agente non ha prodotto output valido entro i retry consentiti.

    Chi chiama applica il fallback previsto per quello step: mai un'invenzione.
    """

    def __init__(self, agent: str, reason: str) -> None:
        super().__init__(f"[{agent}] {reason}")
        self.agent = agent
        self.reason = reason


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    retries: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.calls += other.calls
        self.retries += other.retries


@dataclass
class RunLog:
    """Contabilità per sessione, persistita su disco.

    Ogni richiesta HTTP costruisce una Pipeline nuova: tenere il conteggio solo
    in memoria lo azzererebbe a ogni chiamata. Il log è append-only su
    `state/<session>/run.log`, una riga JSON per evento.
    """

    path: Path | None = None
    per_agent: dict[str, Usage] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)

    def record(self, agent: str, usage: Usage, duration: float, outcome: str) -> None:
        self.per_agent.setdefault(agent, Usage()).add(usage)
        event = {
            "agent": agent,
            "outcome": outcome,
            "duration_s": round(duration, 2),
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "calls": usage.calls,
            "retries": usage.retries,
        }
        self.events.append(event)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def total(self) -> Usage:
        total = Usage()
        for usage in self.per_agent.values():
            total.add(usage)
        return total


def read_usage(path: Path) -> dict:
    """Aggrega il run.log di una sessione, inclusi gli eventi di richieste precedenti."""
    per_agent: dict[str, Usage] = {}
    events: list[dict] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            events.append(event)
            usage = per_agent.setdefault(event["agent"], Usage())
            usage.input_tokens += event["input_tokens"]
            usage.output_tokens += event["output_tokens"]
            usage.calls += event.get("calls", 0)
            usage.retries += event.get("retries", 0)

    total = Usage()
    for usage in per_agent.values():
        total.add(usage)

    return {
        "total": {
            "input_tokens": total.input_tokens,
            "output_tokens": total.output_tokens,
            "calls": total.calls,
        },
        "per_agent": {
            name: {
                "input_tokens": u.input_tokens,
                "output_tokens": u.output_tokens,
                "calls": u.calls,
                "retries": u.retries,
            }
            for name, u in per_agent.items()
        },
        "events": events,
    }


def _load_config() -> dict:
    with open(AGENTS_DIR / "config" / "models.yaml", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _load_schema(name: str) -> dict:
    with open(AGENTS_DIR / "schemas" / f"{name}.schema.json", encoding="utf-8") as handle:
        return json.load(handle)


def _load_instructions(agent: str) -> str:
    return (AGENTS_DIR / "subagents" / f"{agent}.md").read_text(encoding="utf-8")


def _extract_json(text: str) -> Any:
    """I modelli a volte incorniciano il JSON in un blocco markdown."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return json.loads(cleaned.strip())


class AgentRuntime:
    def __init__(self, run_log: RunLog | None = None) -> None:
        self.config = _load_config()
        self.defaults = self.config["defaults"]
        self.tiers = self.config["tiers"]
        # Costruttore senza argomenti: l'SDK risolve in ordine ANTHROPIC_API_KEY,
        # ANTHROPIC_AUTH_TOKEN e il profilo OAuth su disco. Leggere solo la
        # variabile d'ambiente escluderebbe le altre due strade.
        try:
            self.client = Anthropic(timeout=self.defaults["timeout_seconds"])
        except Exception as exc:
            raise RuntimeError(
                "Nessuna credenziale Anthropic trovata. Impostare ANTHROPIC_API_KEY "
                "in app/.env (vedi .env.example), oppure autenticarsi con `ant auth login`."
            ) from exc
        self.run_log = run_log or RunLog()

    def _settings(self, agent: str) -> dict:
        agent_cfg = self.config["agents"][agent.replace("-", "_")]
        tier = self.tiers[agent_cfg["tier"]]
        return {
            "model": tier["model"],
            "max_tokens": agent_cfg["max_output_tokens"],
            "temperature": agent_cfg.get("temperature", self.defaults["temperature"]),
        }

    def run(self, agent: str, payload: dict, schema_name: str) -> dict:
        """Esegue un agente e restituisce output validato contro il suo schema.

        Al fallimento di validazione il retry include l'errore e lo schema, così
        il modello corregge invece di ritentare alla cieca.
        """
        settings = self._settings(agent)
        schema = _load_schema(schema_name)
        validator = Draft202012Validator(schema)
        system = _load_instructions(agent)

        max_retries = self.defaults["max_retries"]
        backoff = self.defaults["retry_backoff_seconds"]
        usage = Usage()
        started = time.monotonic()
        correction: str | None = None
        last_error = "nessun tentativo eseguito"

        for attempt in range(max_retries + 1):
            user_content = json.dumps(payload, ensure_ascii=False)
            if correction:
                user_content += (
                    f"\n\nIl tentativo precedente non è valido: {correction}\n"
                    f"Schema da rispettare:\n{json.dumps(schema, ensure_ascii=False)}\n"
                    "Rispondi solo con JSON conforme."
                )

            try:
                response = self.client.messages.create(
                    model=settings["model"],
                    max_tokens=settings["max_tokens"],
                    temperature=settings["temperature"],
                    system=system,
                    messages=[{"role": "user", "content": user_content}],
                )
            except APITimeoutError:
                last_error = "timeout"
            except APIStatusError as exc:
                last_error = f"errore API {exc.status_code}"
                if exc.status_code < 500 and exc.status_code != 429:
                    break
            else:
                usage.calls += 1
                usage.input_tokens += response.usage.input_tokens
                usage.output_tokens += response.usage.output_tokens
                try:
                    result = _extract_json(response.content[0].text)
                    validator.validate(result)
                except (json.JSONDecodeError, IndexError) as exc:
                    last_error = f"output non è JSON ({exc})"
                    correction = last_error
                except ValidationError as exc:
                    last_error = f"schema non rispettato in '{'/'.join(str(p) for p in exc.path)}': {exc.message}"
                    correction = last_error
                else:
                    self.run_log.record(agent, usage, time.monotonic() - started, "ok")
                    return result

            if attempt < max_retries:
                usage.retries += 1
                time.sleep(backoff[min(attempt, len(backoff) - 1)])

        self.run_log.record(agent, usage, time.monotonic() - started, f"failed: {last_error}")
        raise AgentFailure(agent, last_error)
