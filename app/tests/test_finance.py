"""Verifica dei calcoli finanziari contro valori noti.

Questi test sono l'evidenza che il simulator non inventa numeri: la matematica
è isolata, deterministica e controllata su casi calcolabili a mano.
"""

import pytest

from finance import (
    SimulationError,
    accantonamento_mensile,
    costo_ricorrente_nel_tempo,
    erosione_inflazione,
    quadro_annuale,
    rata_e_costo_totale,
)


class TestAccantonamento:
    def test_senza_rendimento_il_montante_e_la_somma_versata(self):
        series = accantonamento_mensile(monthly=100, months=12, annual_rate=0.0)
        assert series[-1]["contributed"] == 1200.00
        assert series[-1]["value_nominal"] == 1200.00

    def test_senza_inflazione_valore_reale_uguale_a_nominale(self):
        series = accantonamento_mensile(monthly=50, months=36, annual_rate=0.02)
        assert series[-1]["value_real"] == series[-1]["value_nominal"]

    def test_con_rendimento_il_montante_supera_i_versamenti(self):
        series = accantonamento_mensile(monthly=100, months=24, annual_rate=0.03)
        assert series[-1]["value_nominal"] > series[-1]["contributed"]

    def test_inflazione_erode_il_valore_reale(self):
        series = accantonamento_mensile(
            monthly=50, months=36, annual_rate=0.0, inflation_rate=0.02
        )
        assert series[-1]["contributed"] == 1800.00
        assert series[-1]["value_real"] < 1800.00

    def test_capitalizzazione_composta_non_lineare(self):
        """Il tasso mensile è (1+r)^(1/12)-1, non r/12.

        Con r/12 il montante risulterebbe più alto: è proprio l'errore che il
        sistema insegna a non fare.
        """
        series = accantonamento_mensile(monthly=1000, months=12, annual_rate=0.12)
        lineare = 1000 * sum((1 + 0.12 / 12) ** (12 - i) for i in range(12))
        assert series[-1]["value_nominal"] < lineare

    def test_serie_ha_un_punto_per_mese(self):
        series = accantonamento_mensile(monthly=10, months=18)
        assert len(series) == 18
        assert [p["month"] for p in series] == list(range(1, 19))

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"monthly": 0, "months": 12},
            {"monthly": -50, "months": 12},
            {"monthly": 50, "months": 0},
            {"monthly": 50, "months": 601},
        ],
    )
    def test_parametri_fuori_dominio(self, kwargs):
        with pytest.raises(SimulationError):
            accantonamento_mensile(**kwargs)


class TestCostoRicorrente:
    def test_mensile_su_tre_anni(self):
        series = costo_ricorrente_nel_tempo(amount=12.99, cadence="mensile", months=36)
        assert series[-1]["value_nominal"] == -467.64

    def test_importo_positivo_o_negativo_danno_lo_stesso_risultato(self):
        positivo = costo_ricorrente_nel_tempo(12.99, "mensile", 12)
        negativo = costo_ricorrente_nel_tempo(-12.99, "mensile", 12)
        assert positivo[-1]["value_nominal"] == negativo[-1]["value_nominal"]

    def test_cadenza_annuale_addebita_una_volta_ogni_dodici_mesi(self):
        series = costo_ricorrente_nel_tempo(amount=100, cadence="annuale", months=24)
        assert series[-1]["value_nominal"] == -200.00
        assert series[10]["value_nominal"] == 0.00

    def test_cadenza_non_riconosciuta(self):
        with pytest.raises(SimulationError):
            costo_ricorrente_nel_tempo(10, "settimanale", 12)


class TestRataECostoTotale:
    def test_costo_del_credito_a_tasso_zero_con_spese(self):
        _, summary = rata_e_costo_totale(
            principal=500, monthly_payment=48.90, n_payments=12, upfront_fees=0
        )
        assert summary["totale_pagato"] == 586.80
        assert summary["costo_del_credito"] == 86.80

    def test_le_spese_accessorie_entrano_nel_costo(self):
        _, senza = rata_e_costo_totale(1000, 100, 10, upfront_fees=0)
        _, con = rata_e_costo_totale(1000, 100, 10, upfront_fees=25)
        assert senza["costo_del_credito"] == 0.00
        assert con["costo_del_credito"] == 25.00

    def test_spese_negative_rifiutate(self):
        with pytest.raises(SimulationError):
            rata_e_costo_totale(1000, 100, 10, upfront_fees=-5)


class TestQuadroAnnuale:
    """L'evidenza before/after: i costi annuali abbassano il saldo mensile reale."""

    def test_senza_costi_dichiarati_il_saldo_non_cambia(self):
        quadro = quadro_annuale(net_in_period=1050, period_months=3, annual_costs={})
        assert quadro["saldo_mensile_osservato"] == 350.00
        assert quadro["saldo_mensile_corretto"] == 350.00

    def test_costi_annuali_riducono_il_saldo_mensile(self):
        quadro = quadro_annuale(
            net_in_period=1050,
            period_months=3,
            annual_costs={"assicurazione-auto": 480, "bollo-auto": 180, "tari": 240},
        )
        assert quadro["saldo_mensile_osservato"] == 350.00
        assert quadro["costi_annuali_dichiarati"] == 900.00
        assert quadro["incidenza_mensile"] == 75.00
        assert quadro["saldo_mensile_corretto"] == 275.00

    def test_il_saldo_puo_diventare_negativo(self):
        """Caso che il sistema deve poter mostrare: l'estratto ingannava."""
        quadro = quadro_annuale(
            net_in_period=300, period_months=3, annual_costs={"spese-varie": 2400}
        )
        assert quadro["saldo_mensile_corretto"] == -100.00

    def test_periodo_non_positivo(self):
        with pytest.raises(SimulationError):
            quadro_annuale(net_in_period=1000, period_months=0, annual_costs={})

    def test_importo_negativo_rifiutato(self):
        with pytest.raises(SimulationError):
            quadro_annuale(1000, 3, {"bollo-auto": -50})


class TestErosioneInflazione:
    def test_valore_nominale_costante(self):
        series = erosione_inflazione(amount=1000, months=24, inflation_rate=0.02)
        assert all(p["value_nominal"] == 1000.00 for p in series)

    def test_valore_reale_decrescente(self):
        series = erosione_inflazione(amount=1000, months=12, inflation_rate=0.02)
        assert series[-1]["value_real"] == pytest.approx(980.39, abs=0.02)
        assert series[-1]["value_real"] < series[0]["value_real"]

    def test_inflazione_zero_non_erode(self):
        series = erosione_inflazione(amount=1000, months=12, inflation_rate=0.0)
        assert series[-1]["value_real"] == 1000.00
