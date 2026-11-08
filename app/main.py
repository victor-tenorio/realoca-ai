from fastapi import FastAPI

from app.api.v1.absences import router as absences_router
from app.api.v1.employees import router as employees_router
from app.api.v1.health import router as health_router
from app.api.v1.tasks import router as tasks_router
from app.api.v1.teams import router as teams_router
from app.errors import register_error_handlers
from app.api.v1.integrations import router as integrations_router
from app.api.v1.proposals import router as proposals_router
from app.api.v1.cases import router as cases_router

app = FastAPI(title="Realoca AI API")

app.include_router(health_router)
app.include_router(absences_router, prefix="/api/v1")
app.include_router(employees_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(teams_router, prefix="/api/v1")
register_error_handlers(app)
app.include_router(integrations_router)
app.include_router(proposals_router, prefix="/api/v1")
app.include_router(cases_router, prefix="/api/v1")
