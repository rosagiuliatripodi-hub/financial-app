"""Verifica del parsing deterministico.

Copre i due comportamenti che la pipeline dà per scontati: le righe illeggibili
finiscono in `rejected` senza interrompere il flusso, e un formato non
riconosciuto solleva la richiesta di mapping invece di tirare a indovinare.
"""

from pathlib import Path

import pytest

from parser import ColumnMappingRequired, _parse_amount, parse_csv, to_artifact

SAMPLE = Path(__file__).resolve().parent.parent / "sample" / "estratto-conto-esempio.csv"


class TestParseAmount:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("1.780,00", 1780.00),
            ("-620,00", -620.00),
            ("1,234.56", 1234.56),
            ("12,99", 12.99),
            ("-2,50", -2.50),
            ("€ 1.000,00", 1000.00),
            ("(45,00)", -45.00),
        ],
    )
    def test_formati_italiani_e_inglesi(self, raw, expected):
        assert float(_parse_amount(raw)) == expected

    @pytest.mark.parametrize("raw", ["", "   ", "abc", "-"])
    def test_valori_non_numerici(self, raw):
        assert _parse_amount(raw) is None


class TestParseCsv:
    def test_estratto_di_esempio(self):
        result = parse_csv(SAMPLE.read_text(encoding="utf-8"))
        assert result.dialect == "it-standard"
        assert len(result.transactions) == 46
        assert result.rejected == []

    def test_segni_preservati(self):
        result = parse_csv(SAMPLE.read_text(encoding="utf-8"))
        entrate = [t for t in result.transactions if t["amount"] > 0]
        assert len(entrate) == 3
        assert all("STIPENDIO" in t["description"] for t in entrate)

    def test_id_progressivi(self):
        result = parse_csv(SAMPLE.read_text(encoding="utf-8"))
        assert result.transactions[0]["id"] == "t001"
        assert result.transactions[-1]["id"] == "t046"

    def test_riga_malformata_non_interrompe(self):
        csv_text = (
            "Data;Descrizione;Importo\n"
            "02/01/2026;STIPENDIO;1.780,00\n"
            "data-rotta;QUALCOSA;-10,00\n"
            "03/01/2026;AFFITTO;-620,00\n"
            "04/01/2026;;-10,00\n"
        )
        result = parse_csv(csv_text)
        assert len(result.transactions) == 2
        assert {r["reason"] for r in result.rejected} == {
            "data non riconosciuta",
            "descrizione mancante",
        }

    def test_colonne_separate_dare_avere(self):
        csv_text = (
            "Data contabile;Descrizione;Addebiti;Accrediti\n"
            "02/01/2026;STIPENDIO;;1.780,00\n"
            "03/01/2026;AFFITTO;620,00;\n"
        )
        result = parse_csv(csv_text)
        assert result.dialect == "banca-generico"
        assert result.transactions[0]["amount"] == 1780.00
        assert result.transactions[1]["amount"] == -620.00

    def test_nessuna_riga_valida_chiede_mapping(self):
        """Colonne riconosciute ma dati inutilizzabili: il mapping è sbagliato."""
        csv_text = (
            "Data;Descrizione;Importo\n"
            "xx;AAA;non-un-numero\n"
            "yy;BBB;nemmeno\n"
        )
        with pytest.raises(ColumnMappingRequired) as exc:
            parse_csv(csv_text)
        assert len(exc.value.preview) == 2

    def test_formato_sconosciuto_chiede_mapping(self):
        csv_text = "col_a;col_b;col_c\nx;y;z\n"
        with pytest.raises(ColumnMappingRequired) as exc:
            parse_csv(csv_text)
        assert exc.value.headers == ["col_a", "col_b", "col_c"]

    def test_mapping_manuale(self):
        csv_text = "col_a;col_b;col_c\n02/01/2026;STIPENDIO;1.780,00\n"
        result = parse_csv(csv_text, mapping={"date": 0, "description": 1, "amount": 2})
        assert result.dialect == "user-mapped"
        assert result.transactions[0]["amount"] == 1780.00


class TestArtifact:
    def test_conforme_allo_schema_atteso(self):
        result = parse_csv(SAMPLE.read_text(encoding="utf-8"))
        artifact = to_artifact(result, "sess123", "estratto-conto-esempio.csv")
        assert artifact["currency"] == "EUR"
        assert artifact["source"]["rows_parsed"] == 46
        assert artifact["period"]["from"] == "2026-01-02"
        assert artifact["period"]["to"] == "2026-03-31"
