"""
Normalize raw parsed rows into a consistent dict shape before DB insert.
All amounts are coerced to float; dates to ISO strings; strings stripped.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any


# Canonical field names after normalization
CANONICAL_FIELDS = {
    "external_id",
    "amount",
    "currency",
    "transaction_date",
    "value_date",
    "description",
    "reference_no",
    "counterparty",
    "raw_data",
}

# Common column aliases → canonical name
_ALIAS_MAP: dict[str, str] = {
    # amount
    "debit": "amount",
    "credit": "amount",
    "net amount": "amount",
    "net_amount": "amount",
    "transaction amount": "amount",
    "transaction_amount": "amount",
    # date
    "date": "transaction_date",
    "txn date": "transaction_date",
    "txn_date": "transaction_date",
    "booking date": "transaction_date",
    "booking_date": "transaction_date",
    "posting date": "transaction_date",
    "posting_date": "transaction_date",
    # value date
    "val date": "value_date",
    "val_date": "value_date",
    "settlement date": "value_date",
    "settlement_date": "value_date",
    # reference
    "ref": "reference_no",
    "reference": "reference_no",
    "ref no": "reference_no",
    "ref_no": "reference_no",
    "cheque no": "reference_no",
    "cheque_no": "reference_no",
    # description
    "narration": "description",
    "particulars": "description",
    "remarks": "description",
    "details": "description",
    # counterparty
    "beneficiary": "counterparty",
    "payee": "counterparty",
    "payer": "counterparty",
    "party": "counterparty",
    "vendor / customer": "counterparty",
    "vendor/customer": "counterparty",
    "vendor": "counterparty",
    "customer name": "counterparty",
    # id
    "txn id": "external_id",
    "txn_id": "external_id",
    "transaction id": "external_id",
    "transaction_id": "external_id",
    "doc no": "external_id",
    "doc_no": "external_id",
}


def _is_blank(v: Any) -> bool:
    """True for None, empty string, zero, and float NaN (pandas empty cell)."""
    if v is None or v == "":
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return False


def _clean_str(v: Any) -> str | None:
    """Convert to stripped string; return None for blank/NaN values."""
    if _is_blank(v):
        return None
    s = str(v).strip()
    return s if s and s.lower() != "nan" else None


def _parse_amount(value: Any) -> float:
    """Strip commas, parentheses (negatives), currency symbols, then cast to float."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    negative = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[^\d.\-]", "", s.replace("(", "-").replace(")", ""))
    try:
        result = float(s)
        return -abs(result) if negative and result > 0 else result
    except ValueError:
        return 0.0


def _parse_date(value: Any) -> str | None:
    """Return ISO date string or None."""
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    s = str(value).strip()
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d %b %Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _canonical_key(raw_key: str) -> str:
    key = raw_key.strip().lower()
    return _ALIAS_MAP.get(key, key.replace(" ", "_"))


class TransactionNormalizer:
    """
    Accepts a list of raw dicts (from BankStatementReader or LedgerReader)
    and returns a list of normalized dicts ready for TransactionValidator.
    """

    def normalize(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self._normalize_row(row) for row in rows]

    def _normalize_row(self, raw: dict[str, Any]) -> dict[str, Any]:
        # Re-key using alias map
        rekeyed: dict[str, Any] = {}
        for k, v in raw.items():
            key_lower = k.strip().lower()
            # Debit/credit get special handling — skip when value is blank/null
            # so they never overwrite a valid amount already set by the other column.
            if key_lower == "credit":
                if not _is_blank(v) and v != 0:
                    rekeyed["amount"] = _parse_amount(v)
                # else: ignore — debit may have already set amount
            elif key_lower == "debit":
                if not _is_blank(v) and v != 0:
                    rekeyed["amount"] = -abs(_parse_amount(v))
                # else: ignore — credit may have already set amount
            else:
                canonical = _canonical_key(k)
                rekeyed[canonical] = v

        out: dict[str, Any] = {}
        out["external_id"] = _clean_str(rekeyed.get("external_id"))
        out["amount"] = _parse_amount(rekeyed.get("amount", 0))
        currency = _clean_str(rekeyed.get("currency"))
        out["currency"] = (currency.upper() if currency else "AED")
        out["transaction_date"] = _parse_date(rekeyed.get("transaction_date"))
        out["value_date"] = _parse_date(rekeyed.get("value_date"))
        out["description"] = _clean_str(rekeyed.get("description"))
        out["reference_no"] = _clean_str(rekeyed.get("reference_no"))
        out["counterparty"] = _clean_str(rekeyed.get("counterparty"))
        # Store the full original row for traceability
        out["raw_data"] = raw
        return out
