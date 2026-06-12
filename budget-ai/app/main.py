from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import pandas as pd

from app.db import Base, engine
from app.ingest import ingest_budget_csv
from app.forecasting import fit_forecast
from app.anomaly import detect_anomalies
from app.scenario import run_scenario
from app.audit import audit_action

app = FastAPI()
Base.metadata.create_all(bind=engine)


@app.post("/ingest")
async def ingest(file: UploadFile = File(...)):
    content = await file.read()
    try:
        df = pd.read_csv(pd.compat.StringIO(content.decode()))
        df = ingest_budget_csv(df)
        audit_action("ingest", {"filename": file.filename, "records": len(df)})
        return JSONResponse({"status": "success", "records": len(df)})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/forecast")
def forecast():
    raise HTTPException(status_code=501, detail="Forecast endpoint not implemented")


@app.get("/anomalies")
def anomalies():
    raise HTTPException(status_code=501, detail="Anomalies endpoint not implemented")


@app.post("/scenario")
def scenario(changes: dict):
    raise HTTPException(status_code=501, detail="Scenario endpoint not implemented")
