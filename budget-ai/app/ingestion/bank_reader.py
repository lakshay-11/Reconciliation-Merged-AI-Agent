"""
Parse bank statement files into raw row dicts.
Supports: CSV, Excel (.xlsx/.xls), and tab-delimited TXT.
Each returned dict contains original column names — normalizer.py re-keys them.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pandas as pd


class BankStatementReader:
    """
    Read a bank statement file and return a list of raw row dicts.

    Usage:
        reader = BankStatementReader()
        rows = reader.read("uploads/bank_stmt_jan.xlsx")
    """

    def read(self, source: str | Path | bytes, filename: str = "") -> list[dict[str, Any]]:
        """
        Accept a file path, a Path object, or raw bytes (from a FastAPI UploadFile).
        `filename` is only needed when `source` is bytes, to infer file type.
        """
        if isinstance(source, bytes):
            return self._from_bytes(source, filename)
        path = Path(source)
        suffix = path.suffix.lower()
        if suffix in (".xlsx", ".xls"):
            return self._read_excel(path)
        if suffix in (".csv",):
            return self._read_csv(path)
        if suffix in (".txt", ".tsv"):
            return self._read_csv(path, sep="\t")
        raise ValueError(f"Unsupported bank statement format: {suffix!r}")

    # ------------------------------------------------------------------
    # private helpers
    # ------------------------------------------------------------------

    def _read_excel(self, path: Path) -> list[dict[str, Any]]:
        df = pd.read_excel(path, dtype=str)
        return self._clean_df(df)

    def _read_csv(self, path: Path, sep: str = ",") -> list[dict[str, Any]]:
        # Try UTF-8 first, fall back to Windows-1256 (common for Arabic exports)
        for enc in ("utf-8", "windows-1256", "latin-1"):
            try:
                df = pd.read_csv(path, sep=sep, dtype=str, encoding=enc)
                return self._clean_df(df)
            except UnicodeDecodeError:
                continue
        raise ValueError(f"Could not decode {path} with any supported encoding.")

    def _from_bytes(self, data: bytes, filename: str) -> list[dict[str, Any]]:
        suffix = Path(filename).suffix.lower()
        if suffix in (".xlsx", ".xls"):
            df = pd.read_excel(io.BytesIO(data), dtype=str)
        elif suffix in (".csv",):
            for enc in ("utf-8", "windows-1256", "latin-1"):
                try:
                    df = pd.read_csv(io.BytesIO(data), dtype=str, encoding=enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                raise ValueError("Could not decode uploaded file.")
        elif suffix in (".txt", ".tsv"):
            df = pd.read_csv(io.BytesIO(data), sep="\t", dtype=str)
        else:
            raise ValueError(f"Unsupported format: {filename!r}")
        return self._clean_df(df)

    @staticmethod
    def _clean_df(df: pd.DataFrame) -> list[dict[str, Any]]:
        # Drop fully empty rows and columns
        df = df.dropna(how="all").dropna(axis=1, how="all")
        # Strip whitespace from column names
        df.columns = [str(c).strip() for c in df.columns]
        # Replace pandas NA with None
        return df.where(pd.notna(df), None).to_dict(orient="records")
