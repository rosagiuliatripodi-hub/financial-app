"""Calcoli finanziari deterministici.

Nessun LLM calcola questi valori: il simulator riceve le serie già pronte e si
limita a narrarle. Un errore aritmetico in questo contesto è indistinguibile da
una bugia, per chi legge.

Tutti gli importi sono Decimal internamente e float arrotondati ai centesimi in
uscita. I tassi sono annuali ed effettivi, espressi come frazione (0.02 = 2%).
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, getcontext
from typing import Any, Literal, TypedDict

getcontext().prec = 28

CENT = Decimal("0.01")
MAX_MONTHS = 600

Cadence = Literal["mensile", "bimestrale", "trimestrale", "annuale"]

CADENCE_MONTHS: dict[Cadence, int] = {
    "mensile": 1,
    "bimestrale": 2,
    "trimestrale": 3,
    "annuale": 12,
}


class SeriesPoint(TypedDict):
    month: int
    contributed: float
    value_nominal: float
    value_real: float


class SimulationError(ValueError):
    """Parametri fuori dominio. Lo scenario non viene mostrato affatto."""


def _money(value: Decimal) -> float:
    return float(value.quantize(CENT, rounding=ROUND_HALF_UP))


def _monthly_rate(annual_rate: Decimal) -> Decimal:
    """Tasso mensile equivalente, non annuale/12.

    Dividere per 12 sovrastima la crescita: su 36 mesi al 2% la differenza è
    di pochi centesimi, ma il sistema insegna l'interesse composto e non può
    permettersi di calcolarlo in modo approssimato.
    """
    if annual_rate == 0:
        return Decimal(0)
    return (Decimal(1) + annual_rate) ** (Decimal(1) / Decimal(12)) - Decimal(1)


def _validate(months: int, *rates: Decimal) -> None:
    if months < 1:
        raise SimulationError("Il numero di mesi deve essere almeno 1.")
    if months > MAX_MONTHS:
        raise SimulationError(f"Orizzonte massimo {MAX_MONTHS} mesi.")
    for rate in rates:
        if rate <= Decimal(-1):
            raise SimulationError("Un tasso non può essere pari o inferiore a -100%.")


def accantonamento_mensile(
    monthly: float,
    months: int,
    annual_rate: float = 0.0,
    inflation_rate: float = 0.0,
) -> list[SeriesPoint]:
    """Versamento periodico costante a inizio mese.

    `value_real` deflaziona il montante: mostra il potere d'acquisto, non la
    cifra nominale.
    """
    amount = Decimal(str(monthly))
    rate = Decimal(str(annual_rate))
    infl = Decimal(str(inflation_rate))
    _validate(months, rate, infl)
    if amount <= 0:
        raise SimulationError("L'importo mensile deve essere positivo.")

    r = _monthly_rate(rate)
    i = _monthly_rate(infl)

    balance = Decimal(0)
    contributed = Decimal(0)
    series: list[SeriesPoint] = []

    for month in range(1, months + 1):
        balance = (balance + amount) * (Decimal(1) + r)
        contributed += amount
        deflator = (Decimal(1) + i) ** month
        series.append(
            SeriesPoint(
                month=month,
                contributed=_money(contributed),
                value_nominal=_money(balance),
                value_real=_money(balance / deflator),
            )
        )
    return series


def costo_ricorrente_nel_tempo(
    amount: float,
    cadence: Cadence,
    months: int,
    inflation_rate: float = 0.0,
) -> list[SeriesPoint]:
    """Accumulo di un costo fisso. Gli importi sono negativi: sono uscite.

    Serve a rendere visibile che una spesa piccola e ripetuta ha un peso annuo
    molto diverso dal suo singolo addebito.
    """
    if cadence not in CADENCE_MONTHS:
        raise SimulationError(f"Cadenza non riconosciuta: {cadence}")
    step = CADENCE_MONTHS[cadence]
    unit = abs(Decimal(str(amount)))
    infl = Decimal(str(inflation_rate))
    _validate(months, infl)
    if unit == 0:
        raise SimulationError("L'importo del costo ricorrente non può essere zero.")

    i = _monthly_rate(infl)
    paid = Decimal(0)
    series: list[SeriesPoint] = []

    for month in range(1, months + 1):
        if month % step == 0:
            paid += unit
        deflator = (Decimal(1) + i) ** month
        series.append(
            SeriesPoint(
                month=month,
                contributed=_money(-paid),
                value_nominal=_money(-paid),
                value_real=_money(-paid / deflator),
            )
        )
    return series


def rata_e_costo_totale(
    principal: float,
    monthly_payment: float,
    n_payments: int,
    upfront_fees: float = 0.0,
) -> tuple[list[SeriesPoint], dict[str, float]]:
    """Costo effettivo di un acquisto a rate.

    Restituisce anche il totale, perché è il numero che rende evidente che
    "tasso zero" non significa "costo zero" quando ci sono spese accessorie.
    """
    cap = Decimal(str(principal))
    rata = Decimal(str(monthly_payment))
    fees = Decimal(str(upfront_fees))
    _validate(n_payments)
    if cap <= 0 or rata <= 0:
        raise SimulationError("Capitale e rata devono essere positivi.")
    if fees < 0:
        raise SimulationError("Le spese accessorie non possono essere negative.")

    paid = Decimal(0)
    series: list[SeriesPoint] = []
    for month in range(1, n_payments + 1):
        paid += rata
        series.append(
            SeriesPoint(
                month=month,
                contributed=_money(-(paid + fees)),
                value_nominal=_money(-(paid + fees)),
                value_real=_money(-(paid + fees)),
            )
        )

    total_paid = paid + fees
    summary = {
        "capitale": _money(cap),
        "totale_pagato": _money(total_paid),
        "costo_del_credito": _money(total_paid - cap),
        "spese_accessorie": _money(fees),
    }
    return series, summary


def erosione_inflazione(
    amount: float,
    months: int,
    inflation_rate: float,
) -> list[SeriesPoint]:
    """Capitale fermo: il valore nominale resta, il potere d'acquisto scende."""
    cap = Decimal(str(amount))
    infl = Decimal(str(inflation_rate))
    _validate(months, infl)
    if cap <= 0:
        raise SimulationError("L'importo deve essere positivo.")

    i = _monthly_rate(infl)
    series: list[SeriesPoint] = []
    for month in range(1, months + 1):
        deflator = (Decimal(1) + i) ** month
        series.append(
            SeriesPoint(
                month=month,
                contributed=_money(cap),
                value_nominal=_money(cap),
                value_real=_money(cap / deflator),
            )
        )
    return series


def quadro_annuale(
    net_in_period: float,
    period_months: float,
    annual_costs: dict[str, float],
) -> dict[str, Any]:
    """Ricalcola il saldo mensile includendo i costi annuali dichiarati.

    È il calcolo che regge l'evidenza before/after: un estratto trimestrale non
    contiene assicurazione, bollo o TARI, quindi il saldo mensile che mostra è
    sistematicamente più alto di quello reale.

    `annual_costs` arriva dalle risposte dell'utente alle domande di
    `completeness`. Il sistema non stima nulla al posto suo.
    """
    if period_months <= 0:
        raise SimulationError("Il periodo osservato deve essere positivo.")
    for label, value in annual_costs.items():
        if value < 0:
            raise SimulationError(f"Importo annuale negativo per '{label}'.")

    months = Decimal(str(period_months))
    observed = Decimal(str(net_in_period)) / months
    hidden_total = sum((Decimal(str(v)) for v in annual_costs.values()), Decimal(0))
    hidden_monthly = hidden_total / Decimal(12)

    return {
        "saldo_mensile_osservato": _money(observed),
        "costi_annuali_dichiarati": _money(hidden_total),
        "incidenza_mensile": _money(hidden_monthly),
        "saldo_mensile_corretto": _money(observed - hidden_monthly),
        "voci": {label: _money(Decimal(str(v))) for label, v in annual_costs.items()},
        "period_months": float(months),
    }


SCENARIOS = {
    "accantonamento_mensile": accantonamento_mensile,
    "costo_ricorrente_nel_tempo": costo_ricorrente_nel_tempo,
    "rata_e_costo_totale": rata_e_costo_totale,
    "erosione_inflazione": erosione_inflazione,
}
