"""Transactional confirmed-absence registration. No planning or state transitions."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.enums import CaseStatus
from app.errors import APIError
from app.models import Absence, Case, Employee
from app.models.workflow import case_absences
from app.schemas.absences import AbsenceCreate, AbsenceCreated
from app.services import audit, impact, task_source


def existing_case(session: Session, absence_id: str) -> Case | None:
    return session.scalar(
        select(Case)
        .join(case_absences)
        .where(case_absences.c.absence_id == absence_id)
        .order_by(Case.created_at, Case.case_id)
        .limit(1)
    )


def registration_response(absence: Absence, case: Case) -> AbsenceCreated:
    return AbsenceCreated(
        absence_id=absence.absence_id, case_id=case.case_id, status=case.status
    )


def register_confirmed_absence(
    session: Session, payload: AbsenceCreate
) -> tuple[AbsenceCreated, int]:
    if not payload.confirmed:
        raise APIError(
            422, "ABSENCE_NOT_CONFIRMED", "Esta operação exige ausência confirmada", {}
        )
    # Acquire the SQLite writer lock BEFORE reads. This serializes contenders
    # across processes; a pre-insert SELECT alone would not prevent duplicates.
    with session.begin():
        if session.get_bind().dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        starts_at = payload.starts_at.astimezone(UTC)
        ends_at = payload.ends_at.astimezone(UTC)
        previous = session.scalar(
            select(Absence).where(
                Absence.source_system == payload.source_system,
                Absence.external_id == payload.external_id,
            )
        )
        if previous is not None:
            case = existing_case(session, previous.absence_id)
            details = {"absence_id": previous.absence_id}
            if case is not None:
                details["case_id"] = case.case_id
            if (
                previous.employee_id,
                previous.starts_at,
                previous.ends_at,
                previous.confirmed,
            ) != (payload.employee_id, starts_at, ends_at, payload.confirmed):
                raise APIError(
                    409,
                    "EXTERNAL_ID_CONFLICT",
                    "Identificador externo já possui outro conteúdo",
                    details,
                )
            if case is None:
                raise APIError(
                    409,
                    "ABSENCE_CASE_MISSING",
                    "Ocorrência existente sem caso vinculado",
                    details,
                )
            return registration_response(previous, case), 200
        if session.get(Employee, payload.employee_id) is None:
            raise APIError(
                404,
                "EMPLOYEE_NOT_FOUND",
                "Funcionário não encontrado",
                {"employee_id": payload.employee_id},
            )
        overlap = session.scalar(
            select(Absence)
            .where(
                Absence.employee_id == payload.employee_id,
                Absence.confirmed.is_(True),
                Absence.starts_at < ends_at,
                Absence.ends_at > starts_at,
            )
            .order_by(Absence.starts_at, Absence.absence_id)
            .limit(1)
        )
        if overlap is not None:
            case = existing_case(session, overlap.absence_id)
            details = {"absence_id": overlap.absence_id}
            if case is not None:
                details["case_id"] = case.case_id
            raise APIError(
                409, "ABSENCE_OVERLAP", "Ausência sobreposta já registrada", details
            )
        now = datetime.now(UTC)
        tasks = task_source.open_tasks_for_absence(
            session, payload.employee_id, starts_at, ends_at
        )
        absence = Absence(
            absence_id=f"abs-{uuid4()}",
            employee_id=payload.employee_id,
            starts_at=starts_at,
            ends_at=ends_at,
            confirmed=True,
            source_system=payload.source_system,
            external_id=payload.external_id,
            updated_at=now,
        )
        case = Case(
            case_id=f"case-{uuid4()}",
            status=CaseStatus.OPEN,
            plan_version=0,
            created_at=now,
            absences=[absence],
            tasks=tasks,
        )
        session.add(case)
        session.flush()
        actor = "api:absences"
        context = {
            "absence_id": absence.absence_id,
            "employee_id": payload.employee_id,
            "source_system": payload.source_system,
            "external_id": payload.external_id,
        }
        audit.record(
            session,
            case_id=case.case_id,
            actor=actor,
            action="absence.confirmed",
            timestamp=now,
            result=context,
        )
        audit.record(
            session,
            case_id=case.case_id,
            actor=actor,
            action="case.opened",
            timestamp=now,
            result={"status": "open", "task_count": len(tasks)},
        )
        audit.record(
            session,
            case_id=case.case_id,
            actor=actor,
            action="impact.detected" if tasks else "impact.no_registered_tasks",
            timestamp=now,
            result={
                "absence_id": absence.absence_id,
                **impact.absence_impact(payload.employee_id, tasks),
            },
        )
        session.flush()
        response = registration_response(absence, case)
    return response, 201
