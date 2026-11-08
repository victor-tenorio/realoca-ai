from fastapi import FastAPI

from app.api.v1.employees import router as employees_router
from app.api.v1.health import router as health_router
from app.api.v1.tasks import router as tasks_router
from app.errors import register_error_handlers

app = FastAPI(title="Realoca AI API")

app.include_router(health_router)
app.include_router(employees_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
register_error_handlers(app)
