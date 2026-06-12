"""
Validate normalized transaction rows before they are persisted.
Returns (valid_rows, error_rows) so the pipeline can route bad data separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class ValidationError:
    row_index: int
    field: str
    message: str
    raw_value: Any = None


@dataclass
class ValidationResult:
    valid: list[dict[str, Any]] = field(default_factory=list)
    errors: list[ValidationError] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def valid_count(self) -> int:
        return len(self.valid)


_SUPPORTED_CURRENCIES = {
    "AED", "USD", "EUR", "GBP", "SAR", "KWD", "BHD", "QAR", "OMR", "EGP",
}


class TransactionValidator:
    """
    Validates a list of normalized dicts. Each row must have:
    - amount: non-zero float
    - transaction_date: valid ISO date string, not in the future
    - currency: known currency code
    """

    def __init__(self, allow_zero_amount: bool = False):
        self._allow_zero = allow_zero_amount

    def validate(self, rows: list[dict[str, Any]]) -> ValidationResult:
        result = ValidationResult()
        today = date.today().isoformat()

        for idx, row in enumerate(rows):
            row_errors = self._validate_row(idx, row, today)
            if row_errors:
                result.errors.extend(row_errors)
            else:
                result.valid.append(row)

        return result

    def _validate_row(
        self, idx: int, row: dict[str, Any], today: str
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []

        # amount
        amount = row.get("amount")
        if amount is None:
            errors.append(ValidationError(idx, "amount", "Missing amount", amount))
        elif not isinstance(amount, (int, float)):
            errors.append(ValidationError(idx, "amount", "Amount must be numeric", amount))
        elif not self._allow_zero and amount == 0.0:
            errors.append(ValidationError(idx, "amount", "Zero-amount transaction rejected", amount))

        # transaction_date
        txn_date = row.get("transaction_date")
        if not txn_date:
            errors.append(ValidationError(idx, "transaction_date", "Missing transaction date", txn_date))
        else:
            try:
                parsed = date.fromisoformat(txn_date)
                if parsed.isoformat() > today:
                    errors.append(ValidationError(
                        idx, "transaction_date",
                        f"Future date {txn_date} not allowed for reconciliation", txn_date,
                    ))
            except ValueError:
                errors.append(ValidationError(
                    idx, "transaction_date", f"Invalid date format: {txn_date!r}", txn_date,
                ))

        # currency
        currency = row.get("currency", "AED")
        if currency not in _SUPPORTED_CURRENCIES:
            errors.append(ValidationError(
                idx, "currency", f"Unsupported currency: {currency!r}", currency,
            ))

        return errors
