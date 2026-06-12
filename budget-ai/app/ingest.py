import pandas as pd
from pathlib import Path
from typing import List


def validate_budget_dataframe(df: pd.DataFrame) -> List[str]:
    errors = []
    required_columns = ["department", "category", "amount", "date"]

    for col in required_columns:
        if col not in df.columns:
            errors.append(f"Missing required column: {col}")

    if not pd.api.types.is_numeric_dtype(df.get("amount", [])):
        errors.append("Column 'amount' must be numeric.")

    if not pd.api.types.is_datetime64_any_dtype(df.get("date", [])):
        try:
            pd.to_datetime(df["date"])
        except Exception:
            errors.append("Column 'date' must be parseable as datetime.")

    return errors


def ingest_budget_csv(path: str) -> pd.DataFrame:
    csv_path = Path(path)
    df = pd.read_csv(csv_path)
    errors = validate_budget_dataframe(df)
    if errors:
        raise ValueError("Budget CSV validation failed:\n" + "\n".join(errors))
    df["date"] = pd.to_datetime(df["date"])
    return df
