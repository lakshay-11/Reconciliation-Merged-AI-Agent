import pandas as pd
from sklearn.ensemble import IsolationForest
import shap


def detect_anomalies(df: pd.DataFrame, contamination: float = 0.05) -> pd.DataFrame:
    features = df[["amount"]].copy()
    model = IsolationForest(contamination=contamination, random_state=42)
    df["anomaly_score"] = model.fit_predict(features)
    df["anomaly"] = df["anomaly_score"] == -1
    return df


def explain_anomaly(df: pd.DataFrame):
    features = df[["amount"]]
    model = IsolationForest(random_state=42)
    model.fit(features)
    explainer = shap.Explainer(model, features)
    shap_values = explainer(features)
    return shap_values
