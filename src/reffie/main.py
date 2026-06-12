from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import reffie.config as config_module
from reffie.hubspot import router as hubspot_router
from reffie.routers import accounts, checklist, health, hubspot_webhook, pocs, upcoming_deals

app = FastAPI(
    title="Reffie Onboarding API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config_module.settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["system"])
app.include_router(accounts.router)
app.include_router(checklist.router)
app.include_router(pocs.router)
app.include_router(hubspot_router.router)
app.include_router(hubspot_webhook.router)
app.include_router(upcoming_deals.router)
