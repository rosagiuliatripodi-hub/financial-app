"""Comportamento dell'orchestrazione: fallback, revisione, blocco.

Sono le proprietà dichiarate in agents/orchestrator.md e rivendicate in
presentazione. Girano senza chiave API perché il runtime è iniettato.

Limite dichiarato: questi test verificano che la Pipeline reagisca correttamente
agli esiti degli agenti. Non verificano che i prompt reali producano output
conforme agli schemi.
"""

import pytest

import orchestrator
from agents_runtime import AgentFailure
from fakes import (
    FakeRuntime,
    analysis,
    concepts,
    explanation_section,
    seed,
    transactions,
    verdict,
)
from orchestrator import Blocked, Pipeline


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrator, "STATE_ROOT", tmp_path)
    return Pipeline("s1")


def attach(pipeline, responses):
    runtime = FakeRuntime(responses)
    pipeline._runtime = runtime
    return runtime


class TestCicloDiRevisione:
    def test_verdetto_pass_alla_prima(self, pipeline):
        seed(pipeline, **{"concepts.json": concepts()})
        runtime = attach(pipeline, {
            "explainer": explanation_section(),
            "guardrail": verdict("pass"),
        })

        result = pipeline.explain()

        assert len(result["sections"]) == 1
        assert runtime.count("explainer") == 1
        assert runtime.count("guardrail") == 1

    def test_revise_poi_pass_include_la_sezione(self, pipeline):
        seed(pipeline, **{"concepts.json": concepts()})
        runtime = attach(pipeline, {
            "explainer": [explanation_section("ti conviene fare X"), explanation_section("descrizione neutra")],
            "guardrail": [verdict("revise"), verdict("pass")],
        })

        result = pipeline.explain()

        assert len(result["sections"]) == 1
        assert result["sections"][0]["plain_text"] == "descrizione neutra"
        assert runtime.count("explainer") == 2

    def test_le_violations_tornano_allexplainer(self, pipeline):
        """La riscrittura deve ricevere cosa correggere, non ripartire alla cieca."""
        seed(pipeline, **{"concepts.json": concepts()})
        runtime = attach(pipeline, {
            "explainer": [explanation_section("ti conviene"), explanation_section("neutro")],
            "guardrail": [verdict("revise"), verdict("pass")],
        })

        pipeline.explain()

        second_call = [p for a, p in runtime.calls if a == "explainer"][1]
        assert "revision" in second_call
        assert second_call["revision"]["violations"][0]["rule_id"] == "NO_INVESTMENT_ADVICE"

    def test_due_revise_consecutivi_forzano_il_blocco(self, pipeline):
        """Limite a 2 cicli: non esiste un terzo tentativo."""
        seed(pipeline, **{"concepts.json": concepts()})
        runtime = attach(pipeline, {
            "explainer": explanation_section("ti conviene"),
            "guardrail": verdict("revise"),
        })

        result = pipeline.explain()

        assert result["sections"] == []
        assert runtime.count("explainer") == 3  # tentativo + 2 revisioni
        assert pipeline.has("blocked.json")

    def test_block_esclude_la_sezione(self, pipeline):
        seed(pipeline, **{"concepts.json": concepts()})
        attach(pipeline, {
            "explainer": explanation_section("investi in un ETF"),
            "guardrail": verdict("block"),
        })

        result = pipeline.explain()

        assert result["sections"] == []
        blocked = pipeline.read("blocked.json")
        assert blocked[0]["violations"][0]["rule_id"] == "NO_INVESTMENT_ADVICE"

    def test_una_sezione_bloccata_non_ferma_le_altre(self, pipeline):
        seed(pipeline, **{"concepts.json": concepts(n=2)})
        attach(pipeline, {
            "explainer": explanation_section(),
            "guardrail": [verdict("block"), verdict("pass")],
        })

        result = pipeline.explain()

        assert len(result["sections"]) == 1
        assert len(pipeline.read("blocked.json")) == 1


class TestFailClosed:
    def test_guardrail_non_disponibile_blocca(self, pipeline):
        """In dubbio non si passa: un guardrail rotto non apre le porte."""
        seed(pipeline, **{"concepts.json": concepts()})
        attach(pipeline, {
            "explainer": explanation_section(),
            "guardrail": AgentFailure("guardrail", "timeout"),
        })

        result = pipeline.explain()

        assert result["sections"] == []

    def test_explainer_rotto_non_propaga_eccezione(self, pipeline):
        seed(pipeline, **{"concepts.json": concepts()})
        attach(pipeline, {
            "explainer": AgentFailure("explainer", "schema non rispettato"),
            "guardrail": verdict("pass"),
        })

        result = pipeline.explain()

        assert result["sections"] == []
        assert pipeline.read("blocked.json")[0]["unavailable"] is True


class TestFallbackCategorizer:
    def test_batch_fallito_finisce_in_uncategorized(self, pipeline):
        """Meglio 3 voci dichiarate non classificate che 3 categorie inventate."""
        pipeline.write("transactions.json", transactions(count=3))
        attach(pipeline, {"categorizer": AgentFailure("categorizer", "output non valido")})

        result = pipeline.categorize()

        assert result["uncategorized"]["count"] == 3
        assert set(result["uncategorized"]["transaction_ids"]) == {"t001", "t002", "t003"}

    def test_i_totali_non_li_calcola_il_modello(self, pipeline):
        """Anche con un categorizer che sbaglia i totali, l'aritmetica vince."""
        pipeline.write("transactions.json", transactions(count=3))
        bugiardo = dict(analysis())
        bugiardo["totals"] = {"income": 999999.0, "expense": -1.0, "net": 999998.0}
        attach(pipeline, {"categorizer": bugiardo})

        result = pipeline.categorize()

        assert result["totals"]["income"] == 1800.0
        assert result["totals"]["expense"] == -50.0
        assert result["totals"]["net"] == 1750.0


class TestFallbackConcetti:
    def test_concept_mapper_rotto_non_lascia_il_percorso_vuoto(self, pipeline):
        seed(pipeline)
        attach(pipeline, {"concept-mapper": AgentFailure("concept-mapper", "vuoto")})

        result = pipeline.map_concepts("base")

        assert len(result["concepts"]) == 2
        assert {c["id"] for c in result["concepts"]} == {"entrate-uscite", "costo-ricorrente"}
        assert all(c["evidence_transaction_ids"] for c in result["concepts"])


class TestCompleteness:
    def test_fallimento_produce_nota_sul_periodo(self, pipeline):
        seed(pipeline)
        attach(pipeline, {"completeness": AgentFailure("completeness", "timeout")})

        result = pipeline.find_gaps()

        assert result["gaps"] == []
        assert "2.9" in result["coverage_note"]

    def test_al_modello_non_arrivano_le_transazioni_complete(self, pipeline):
        """Efficienza token: solo descrizioni distinte, non le righe intere."""
        seed(pipeline)
        runtime = attach(pipeline, {"completeness": {
            "session_id": "s1", "period_months": 2.9, "gaps": [], "coverage_note": "ok"}})

        pipeline.find_gaps()

        payload = runtime.calls[0][1]
        assert "transactions" not in payload
        assert isinstance(payload["descriptions"][0], str)


class TestQuadroCorretto:
    def test_i_costi_annuali_abbassano_il_saldo(self, pipeline):
        seed(pipeline)
        attach(pipeline, {})

        quadro = pipeline.apply_gap_answers({"tari": 240.0, "canone-rai": 90.0})

        assert quadro["costi_annuali_dichiarati"] == 330.0
        assert quadro["saldo_mensile_corretto"] < quadro["saldo_mensile_osservato"]

    def test_un_gap_opaco_non_viene_conteggiato_due_volte(self, pipeline):
        """Il contante è già dentro totals.expense: sommarlo lo conterebbe due volte."""
        seed(pipeline, **{"gaps.json": {
            "session_id": "s1",
            "period_months": 2.9,
            "gaps": [
                {"id": "contante", "label": "Contante", "cadence": "mensile",
                 "reason": "dato_opaco", "question": "dove va?", "confidence": 0.9},
                {"id": "tari", "label": "TARI", "cadence": "annuale",
                 "reason": "fuori_finestra", "question": "quanto paghi?", "confidence": 0.8},
            ],
            "coverage_note": "2.9 mesi",
        }})
        attach(pipeline, {})

        quadro = pipeline.apply_gap_answers({"contante": 1500.0, "tari": 240.0})

        assert quadro["costi_annuali_dichiarati"] == 240.0
        assert "contante" not in quadro["voci"]


class TestSimulazione:
    def test_il_modello_non_puo_alterare_i_numeri(self, pipeline):
        """Il simulator narra: la serie resta quella di finance.py."""
        seed(pipeline)
        falsata = {
            "session_id": "s1",
            "scenario": {"type": "accantonamento_mensile", "params": {}, "set_by": "user"},
            "computed_by": "deterministic",
            "series": [{"month": 1, "contributed": 99999.0, "value_nominal": 99999.0, "value_real": 99999.0}],
            "concept_ids": ["interesse-composto"],
            "assumptions": ["i tassi sono ipotesi tue, non previsioni"],
        }
        attach(pipeline, {"simulator": falsata, "guardrail": verdict("pass")})

        result = pipeline.simulate("accantonamento_mensile", {"monthly": 100, "months": 12})

        assert len(result["series"]) == 12
        assert result["series"][-1]["contributed"] == 1200.00
        assert result["computed_by"] == "deterministic"

    def test_scenario_bloccato_solleva(self, pipeline):
        seed(pipeline)
        attach(pipeline, {
            "simulator": {
                "session_id": "s1",
                "scenario": {"type": "accantonamento_mensile", "params": {}, "set_by": "user"},
                "computed_by": "deterministic", "series": [],
                "concept_ids": [], "assumptions": ["avrai sicuramente questo rendimento"],
            },
            "guardrail": verdict("block", "NO_PREDICTION_AS_FACT"),
        })

        with pytest.raises(Blocked):
            pipeline.simulate("accantonamento_mensile", {"monthly": 50, "months": 6})

    def test_scenario_non_ammesso(self, pipeline):
        seed(pipeline)
        attach(pipeline, {})
        with pytest.raises(orchestrator.SimulationError):
            pipeline.simulate("compra_azioni", {})


class TestQuiz:
    def test_fallimento_non_inventa_un_quiz(self, pipeline):
        seed(pipeline, **{"concepts.json": concepts(), "explanation.json": explanation_section()})
        attach(pipeline, {"comprehension": AgentFailure("comprehension", "solo 1 domanda")})

        assert pipeline.quiz() is None
        assert not pipeline.has("quiz.json")


class TestDomandaLibera:
    def test_risposta_approvata(self, pipeline):
        seed(pipeline, **{"concepts.json": concepts()})
        attach(pipeline, {"explainer": explanation_section(), "guardrail": verdict("pass")})

        result = pipeline.ask("cos'e l'imposta di bollo?")

        assert result["verdict"] == "pass"
        assert result["section"]["title"] == "L'imposta di bollo"

    def test_richiesta_di_consiglio_bloccata(self, pipeline):
        """Il confine si valuta sulla risposta, non con un filtro sull'input."""
        seed(pipeline, **{"concepts.json": concepts()})
        attach(pipeline, {
            "explainer": explanation_section("ti conviene investire in un ETF"),
            "guardrail": verdict("block"),
        })

        result = pipeline.ask("dove mi conviene investire?")

        assert result["verdict"] == "block"
        assert result["section"] is None
        assert result["violations"][0]["rule_id"] == "NO_INVESTMENT_ADVICE"


class TestContabilitaToken:
    def test_il_run_log_sopravvive_alla_pipeline(self, pipeline, tmp_path):
        """Ogni richiesta HTTP crea una Pipeline nuova: il conteggio sta su disco."""
        from agents_runtime import RunLog, Usage, read_usage

        log = RunLog(path=pipeline.dir / "run.log")
        log.record("explainer", Usage(input_tokens=120, output_tokens=340, calls=1), 1.2, "ok")
        log.record("guardrail", Usage(input_tokens=80, output_tokens=60, calls=1), 0.4, "ok")

        letto = read_usage(pipeline.dir / "run.log")

        assert letto["total"]["input_tokens"] == 200
        assert letto["total"]["calls"] == 2
        assert letto["per_agent"]["explainer"]["output_tokens"] == 340

    def test_sessione_senza_log_non_esplode(self, pipeline):
        from agents_runtime import read_usage

        letto = read_usage(pipeline.dir / "run.log")
        assert letto["total"]["calls"] == 0
