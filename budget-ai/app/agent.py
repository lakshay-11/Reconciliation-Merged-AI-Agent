import os
from typing import Any, Dict

from app.ingest import ingest_budget_csv
from app.forecasting import fit_forecast
from app.anomaly import detect_anomalies
from app.scenario import run_scenario


class BudgetAgent:
    def __init__(self, llm_client: Any):
        self.llm_client = llm_client

    def decide(self, task: str, data: str, params: Dict[str, Any] = None) -> Any:
        params = params or {}

        if task == "ingest":
            return ingest_budget_csv(data)
        if task == "forecast":
            return fit_forecast(data, **params)
        if task == "anomaly":
            return detect_anomalies(data, **params)
        if task == "scenario":
            return run_scenario(data, params.get("changes", {}))

        return {"error": "Unknown task"}
