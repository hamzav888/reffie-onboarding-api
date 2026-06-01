from fastapi import FastAPI

from reffie.routers import accounts, checklist, health, pocs

app = FastAPI(
    title="Reffie Onboarding API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(health.router, tags=["system"])
app.include_router(accounts.router)
app.include_router(checklist.router)
app.include_router(pocs.router)
