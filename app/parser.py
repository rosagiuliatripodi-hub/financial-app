"""Parsing deterministico del CSV in transactions.json.

Nessun LLM tocca questo passaggio. Il CSV grezzo non entra mai in un prompt:
è la scelta che regge il budget token dell'intera pipeline.

Il parser riconosce le colonne per alias. Se non ci riesce, o se nessuna riga
risulta valida, si ferma e chiede all'utente di mappare le colonne: non indovina
mai. Le singole righe illeggibili finiscono invece in `rejected` e la pipeline
prosegue.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterator

PREVIEW_ROWS = 3

DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y")

COLUMN_ALIASES = {
    "date": ("data", "data contabile", "data operazione", "date", "data valuta"),
    "description": ("descrizione", "causale", "description", "operazione", "dettagli"),
    "amount": ("importo", "amount", "valore"),
    "debit": ("addebiti", "uscite", "dare", "debit"),
    "credit": ("accrediti", "entrate", "avere", "credit"),
}


class ColumnMappingRequired(Exception):
    """Nessun dialetto riconosciuto: serve l'intervento dell'utente (HITL).

    Espone le intestazioni trovate e un'anteprima, così la UI può chiedere di
    mappare data, descrizione e importo.
    """

    def __init__(self, headers: list[str], preview: list[list[str]]) -> None:
        super().__init__("Formato CSV non riconosciuto: richiesto mapping colonne.")
        self.headers = headers
        self.preview = preview


@dataclass
class ParseResult:
    transactions: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    dialect: str = "user-mapped"
    rows_total: int = 0


def _sniff_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        return ";" if sample.count(";") > sample.count(",") else ","


def _parse_date(raw: str) -> date | None:
    raw = raw.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(raw: str) -> Decimal | None:
    """Gestisce sia 1.234,56 (it) sia 1,234.56 (en).

    Il separatore decimale è l'ultimo tra virgola e punto: il precedente, se
    c'è, è separatore di migliaia.
    """
    text = raw.strip().replace(" ", " ").replace(" ", "")
    if not text:
        return None

    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    text = re.sub(r"[^\d.,]", "", text)
    if not text:
        return None

    last_comma = text.rfind(",")
    last_dot = text.rfind(".")
    if last_comma > last_dot:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", "")

    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return -value if negative and value > 0 else value


def _normalize_header(name: str) -> str:
    return name.strip().lower().replace("_", " ")


def _resolve_columns(headers: list[str]) -> dict[str, int]:
    normalized = [_normalize_header(h) for h in headers]
    resolved: dict[str, int] = {}
    for role, aliases in COLUMN_ALIASES.items():
        for idx, header in enumerate(normalized):
            if header in aliases and role not in resolved:
                resolved[role] = idx
                break
    return resolved


def _iter_rows(content: str) -> tuple[list[str], Iterator[list[str]]]:
    delimiter = _sniff_delimiter(content[:4096])
    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    try:
        headers = next(reader)
    except StopIteration:
        return [], iter(())
    return headers, reader


def parse_csv(content: str, mapping: dict[str, int] | None = None) -> ParseResult:
    """Converte il CSV in transazioni normalizzate.

    `mapping` arriva dalla UI quando l'utente ha risolto a mano le colonne.
    Solleva ColumnMappingRequired se il formato non è riconoscibile da solo.
    """
    headers, reader = _iter_rows(content)
    if not headers:
        raise ColumnMappingRequired([], [])

    columns = mapping or _resolve_columns(headers)
    has_amount = "amount" in columns
    has_split = "debit" in columns and "credit" in columns

    if "date" not in columns or "description" not in columns or not (has_amount or has_split):
        preview = [row for _, row in zip(range(3), reader)]
        raise ColumnMappingRequired(headers, preview)

    dialect = "user-mapped" if mapping else ("banca-generico" if has_split else "it-standard")
    result = ParseResult(dialect=dialect)
    first_rows: list[list[str]] = []

    for line_no, row in enumerate(reader, start=2):
        result.rows_total += 1
        if len(first_rows) < PREVIEW_ROWS:
            first_rows.append(row)
        if not any(cell.strip() for cell in row):
            result.rows_total -= 1
            continue

        max_idx = max(columns.values())
        if len(row) <= max_idx:
            result.rejected.append({"row": line_no, "reason": "numero di colonne insufficiente"})
            continue

        parsed_date = _parse_date(row[columns["date"]])
        if parsed_date is None:
            result.rejected.append({"row": line_no, "reason": "data non riconosciuta"})
            continue

        description = row[columns["description"]].strip()
        if not description:
            result.rejected.append({"row": line_no, "reason": "descrizione mancante"})
            continue

        if has_amount:
            amount = _parse_amount(row[columns["amount"]])
        else:
            debit = _parse_amount(row[columns["debit"]]) or Decimal(0)
            credit = _parse_amount(row[columns["credit"]]) or Decimal(0)
            amount = credit - abs(debit)
            if debit == 0 and credit == 0:
                amount = None

        if amount is None or amount == 0:
            result.rejected.append({"row": line_no, "reason": "importo non riconosciuto o nullo"})
            continue

        result.transactions.append(
            {
                "id": f"t{len(result.transactions) + 1:03d}",
                "date": parsed_date.isoformat(),
                "description": description,
                "amount": float(amount),
            }
        )

    # Righe sporche non fermano il flusso: finiscono in `rejected` e la UI le
    # dichiara. Zero righe valide invece significa colonne sbagliate.
    if not mapping and result.rows_total and not result.transactions:
        raise ColumnMappingRequired(headers, first_rows)

    return result


def to_artifact(result: ParseResult, session_id: str, filename: str) -> dict:
    """Costruisce transactions.json conforme allo schema."""
    dates = sorted(t["date"] for t in result.transactions)
    if dates:
        first, last = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
        months = round(((last - first).days / 30.44) or 1, 1)
    else:
        first = last = date.today()
        months = 0.0

    return {
        "session_id": session_id,
        "source": {
            "filename": filename,
            "rows_total": result.rows_total,
            "rows_parsed": len(result.transactions),
            "rows_rejected": len(result.rejected),
            "dialect": result.dialect,
        },
        "period": {"from": first.isoformat(), "to": last.isoformat(), "months": months},
        "currency": "EUR",
        "transactions": result.transactions,
        "rejected": result.rejected,
    }
