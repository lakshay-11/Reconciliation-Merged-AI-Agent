"""
Parse ledger / ERP general ledger exports into raw row dicts.
Supports the same file formats as BankStatementReader plus
multi-sheet Excel workbooks (reads the first data sheet by default).
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pandas as pd


class LedgerReader:
    """
    Read a ledger or ERP export and return a list of raw row dicts.

    Multi-sheet Excel: pass `sheet` to target a specific sheet name or index.
    If `sheet` is None the first non-empty sheet is used.

    Usage:
        reader = LedgerReader()
        rows = reader.read("uploads/gl_jan.xlsx", sheet="GL Detail")
    """

    def read(
        self,
        source: str | Path | bytes,
        filename: str = "",
        sheet: str | int | None = None,
    ) -> list[dict[str, Any]]:
        if isinstance(source, bytes):
            return self._from_bytes(source, filename, sheet)
        path = Path(source)
        suffix = path.suffix.lower()
        if suffix in (".xlsx", ".xls"):
            return self._read_excel(path, sheet)
        if suffix in (".csv",):
            return self._read_csv(path)
        if suffix in (".txt", ".tsv"):
            return self._read_csv(path, sep="\t")
        raise ValueError(f"Unsupported ledger format: {suffix!r}")

    # ------------------------------------------------------------------
    # private helpers
    # ------------------------------------------------------------------

    def _read_excel(self, path: Path, sheet: str | int | None) -> list[dict[str, Any]]:
        target = self._resolve_sheet(pd.ExcelFile(path), sheet)
        df = pd.read_excel(path, sheet_name=target, dtype=str)
        return self._clean_df(df)

    def _read_csv(self, path: Path, sep: str = ",") -> list[dict[str, Any]]:
        for enc in ("utf-8", "windows-1256", "latin-1"):
            try:
                df = pd.read_csv(path, sep=sep, dtype=str, encoding=enc)
                return self._clean_df(df)
            except UnicodeDecodeError:
                continue
        raise ValueError(f"Could not decode {path}.")

    def _from_bytes(
        self, data: bytes, filename: str, sheet: str | int | None
    ) -> list[dict[str, Any]]:
        suffix = Path(filename).suffix.lower()
        buf = io.BytesIO(data)
        if suffix in (".xlsx", ".xls"):
            xf = pd.ExcelFile(buf)
            target = self._resolve_sheet(xf, sheet)
            df = pd.read_excel(buf, sheet_name=target, dtype=str)
        elif suffix in (".csv",):
            for enc in ("utf-8", "windows-1256", "latin-1"):
                try:
                    df = pd.read_csv(buf, dtype=str, encoding=enc)
                    break
                except UnicodeDecodeError:
                    buf.seek(0)
            else:
                raise ValueError("Could not decode uploaded ledger file.")
        elif suffix in (".txt", ".tsv"):
            df = pd.read_csv(buf, sep="\t", dtype=str)
        else:
            raise ValueError(f"Unsupported format: {filename!r}")
        return self._clean_df(df)

    @staticmethod
    def _resolve_sheet(xf: pd.ExcelFile, sheet: str | int | None) -> str | int:
        if sheet is not None:
            return sheet
        # Pick the first sheet that has more than just a header row
        for name in xf.sheet_names:
            df = pd.read_excel(xf, sheet_name=name, nrows=2)
            if not df.empty:
                return name
        return xf.sheet_names[0]

    @staticmethod
    def _clean_df(df: pd.DataFrame) -> list[dict[str, Any]]:
        df = df.dropna(how="all").dropna(axis=1, how="all")
        df.columns = [str(c).strip() for c in df.columns]
        return df.where(pd.notna(df), None).to_dict(orient="records")
