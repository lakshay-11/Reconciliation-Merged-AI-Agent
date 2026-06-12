import pandas as pd


def run_scenario(df: pd.DataFrame, changes: dict) -> pd.DataFrame:
    scenario_df = df.copy()
    for key, multiplier in changes.items():
        if key in scenario_df.columns and pd.api.types.is_numeric_dtype(scenario_df[key]):
            scenario_df[key] = scenario_df[key] * multiplier
    return scenario_df
