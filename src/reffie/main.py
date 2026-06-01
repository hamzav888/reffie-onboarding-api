from fastapi import FastAPI

from reffie.routers import health

app = FastAPI(
    title="Reffie Onboarding API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(health.router, tags=["system"])
