"""FastAPI application entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import wait_for_database
from app.routers import certificates, equipment, measurements


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Wait for PostgreSQL; schema is created by db/init/*.sql on first start.
    wait_for_database()
    yield


app = FastAPI(
    title="Lab Equipment Calibration Traceability",
    version="1.0.0",
    description=(
        "Register equipment and calibration certificates, record measurements, "
        "revoke certificates, and query the current validity of every record."
    ),
    lifespan=lifespan,
)

app.include_router(equipment.router)
app.include_router(certificates.router)
app.include_router(measurements.router)


@app.get("/health", tags=["system"], summary="Liveness probe")
def health():
    return {"status": "ok"}
