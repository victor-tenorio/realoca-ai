from fastapi import FastAPI

from app.api.v1.health import router as health_router
from app.api.v1.integrations import router as integrations_router

app = FastAPI(title="Realoca AI API")

app.include_router(health_router)
app.include_router(integrations_router)
