from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import Base, engine
from app.api.reconciliation import router as reconciliation_router
from app.api.exceptions import router as exceptions_router
from app.api.reports import router as reports_router
from app.api.admin import router as admin_router
from app.api.agent import router as agent_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables on startup if they don't exist yet
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    description="Reconciliation AI Agent — DOF RFP Use Case 5",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(reconciliation_router)
app.include_router(exceptions_router)
app.include_router(reports_router)
app.include_router(admin_router)
app.include_router(agent_router)


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name}
