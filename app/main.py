from fastapi import FastAPI

from app.api.v1.health import router as health_router

app = FastAPI(title="Realoca AI API")

app.include_router(health_router)