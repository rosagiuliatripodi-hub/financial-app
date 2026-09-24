"""API di Conti Chiari.

Il backend esiste per una ragione precisa: la chiave API non può stare in una
pagina statica. Tutte le chiamate al modello passano da qui.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Prima di qualunque import che costruisca un client: senza questo,
# copiare .env.example in .env non avrebbe alcun effetto.
load_dotenv(Path(__file__).resolve().parent / ".env")

from agents_runtime import read_usage
from finance import SimulationError
from orchestrator import STATE_ROOT, Blocked, Pipeline
from parser import ColumnMappingRequired, parse_csv, to_artifact

logging.basicConfig(level=logging.INFO)

MAX_UPLOAD_BYTES = 2 * 1024 * 1024

app = FastAPI(title="Conti Chiari", version="1.0")
STATIC_DIR = Path(__file__).resolve().parent / "static"
SAMPLE_DIR = Path(__file__).resolve().parent / "sample"


class AnalyzeRequest(BaseModel):
    literacy_level: str = Field(default="base", pattern="^(base|intermedio)$")


class SimulateRequest(BaseModel):
    scenario_type: str
    params: dict[str, float]


class GapAnswers(BaseModel):
    """Importi annuali dichiarati dall'utente. Il sistema non li stima."""

    annual_costs: dict[str, float] = Field(default_factory=dict)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.exception_handler(RuntimeError)
async def missing_configuration(_request, exc: RuntimeError) -> JSONResponse:
    """Configurazione assente (tipicamente la chiave API): errore leggibile, non un 500 muto."""
    logging.error("configurazione non valida: %s", exc)
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(400, "Codifica del file non riconosciuta.")


@app.post("/api/upload")
async def upload(file: UploadFile) -> JSONResponse:
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File troppo grande: massimo 2 MB.")
    if not raw:
        raise HTTPException(400, "File vuoto.")

    session_id = uuid.uuid4().hex[:12]
    content = _decode(raw)

    try:
        result = parse_csv(content)
    except ColumnMappingRequired as exc:
        # HITL: il parser non indovina il mapping, lo chiede.
        pipeline = Pipeline(session_id)
        pipeline.write("raw.json", {"content": content, "filename": file.filename})
        return JSONResponse(
            status_code=409,
            content={
                "session_id": session_id,
                "needs_mapping": True,
                "headers": exc.headers,
                "preview": exc.preview,
            },
        )

    pipeline = Pipeline(session_id)
    artifact = to_artifact(result, session_id, file.filename or "estratto.csv")
    pipeline.write("transactions.json", artifact)
    return JSONResponse({"session_id": session_id, "source": artifact["source"], "period": artifact["period"]})


@app.post("/api/session/{session_id}/mapping")
async def resolve_mapping(session_id: str, mapping: dict[str, int]) -> dict:
    pipeline = Pipeline(session_id)
    if not pipeline.has("raw.json"):
        raise HTTPException(404, "Sessione non trovata.")
    raw = pipeline.read("raw.json")
    try:
        result = parse_csv(raw["content"], mapping=mapping)
    except ColumnMappingRequired:
        raise HTTPException(422, "Il mapping indicato non produce righe valide.")
    artifact = to_artifact(result, session_id, raw["filename"])
    pipeline.write("transactions.json", artifact)
    return {"source": artifact["source"], "period": artifact["period"]}


@app.post("/api/session/{session_id}/analyze")
async def analyze(session_id: str, body: AnalyzeRequest) -> dict:
    pipeline = Pipeline(session_id)
    if not pipeline.has("transactions.json"):
        raise HTTPException(404, "Nessun estratto caricato per questa sessione.")

    analysis = pipeline.categorize()
    concepts = pipeline.map_concepts(body.literacy_level)
    explanation = pipeline.explain()

    return {
        "analysis": analysis,
        "concepts": concepts,
        "explanation": explanation,
        "blocked": pipeline.read("blocked.json") if pipeline.has("blocked.json") else [],
        "usage": _usage(pipeline),
    }


@app.get("/api/session/{session_id}/gaps")
async def gaps(session_id: str) -> dict:
    """Cosa l'estratto non può mostrare. Domande, non raccomandazioni."""
    pipeline = Pipeline(session_id)
    if not pipeline.has("analysis.json"):
        raise HTTPException(409, "Eseguire prima l'analisi.")
    return {"gaps": pipeline.find_gaps(), "usage": _usage(pipeline)}


@app.post("/api/session/{session_id}/gaps")
async def resolve_gaps(session_id: str, body: GapAnswers) -> dict:
    pipeline = Pipeline(session_id)
    if not pipeline.has("analysis.json"):
        raise HTTPException(409, "Eseguire prima l'analisi.")
    try:
        quadro = pipeline.apply_gap_answers(body.annual_costs)
    except SimulationError as exc:
        raise HTTPException(422, str(exc))
    return {"quadro": quadro}


@app.post("/api/session/{session_id}/simulate")
async def simulate(session_id: str, body: SimulateRequest) -> dict:
    pipeline = Pipeline(session_id)
    try:
        simulation = pipeline.simulate(body.scenario_type, body.params)
    except SimulationError as exc:
        raise HTTPException(422, str(exc))
    except Blocked as exc:
        return {"blocked": True, "violations": exc.violations}
    except TypeError:
        raise HTTPException(422, "Parametri non validi per questo scenario.")
    return {"simulation": simulation, "usage": _usage(pipeline)}


@app.post("/api/session/{session_id}/ask")
async def ask(session_id: str, body: AskRequest) -> dict:
    pipeline = Pipeline(session_id)
    if not pipeline.has("concepts.json"):
        raise HTTPException(409, "Eseguire prima l'analisi.")
    result = pipeline.ask(body.question)
    result["usage"] = _usage(pipeline)
    return result


@app.get("/api/session/{session_id}/quiz")
async def quiz(session_id: str) -> dict:
    pipeline = Pipeline(session_id)
    if not pipeline.has("explanation.json"):
        raise HTTPException(409, "Eseguire prima l'analisi.")
    generated = pipeline.quiz()
    if generated is None:
        return {"available": False, "reason": "Verifica non generata: percorso valido comunque."}
    return {"available": True, "quiz": generated}


@app.get("/api/session/{session_id}/replay")
async def replay(session_id: str) -> dict:
    """Riapre una sessione già salvata su disco, senza chiamare il modello.

    Serve per riprendere un'analisi e come rete di sicurezza in demo. Gli
    artefatti sono output veri di un'esecuzione precedente: il flag `replay`
    permette alla UI di dirlo, invece di far sembrare che sia appena successo.
    """
    directory = STATE_ROOT / session_id
    if not (directory / "transactions.json").exists():
        raise HTTPException(404, "Nessuna sessione salvata con questo identificativo.")

    def load(name: str):
        path = directory / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    transactions = load("transactions.json")
    return {
        "replay": True,
        "session_id": session_id,
        "source": transactions["source"],
        "period": transactions["period"],
        "analysis": load("analysis.json"),
        "concepts": load("concepts.json"),
        "explanation": load("explanation.json"),
        "gaps": load("gaps.json"),
        "quadro": load("quadro.json"),
        "simulation": load("simulation.json"),
        "quiz": load("quiz.json"),
        "blocked": load("blocked.json") or [],
        "usage": read_usage(directory / "run.log"),
    }


@app.get("/api/session/{session_id}/usage")
async def usage(session_id: str) -> dict:
    return _usage(Pipeline(session_id))


def _usage(pipeline: Pipeline) -> dict:
    """Legge dal run.log su disco, così il totale copre tutte le richieste della sessione."""
    return read_usage(pipeline.dir / "run.log")


app.mount("/sample", StaticFiles(directory=SAMPLE_DIR), name="sample")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
