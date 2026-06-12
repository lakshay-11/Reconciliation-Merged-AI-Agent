from prophet import Prophet
import pandas as pd


def fit_forecast(df: pd.DataFrame, periods: int = 12) -> pd.DataFrame:
    forecast_df = df.rename(columns={"date": "ds", "amount": "y"})[["ds", "y"]]
    model = Prophet()
    model.fit(forecast_df)
    future = model.make_future_dataframe(periods=periods, freq="M")
    forecast = model.predict(future)
    return forecast
