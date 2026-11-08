"""Confirmed absences and the authoritative, audited case state machine."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.enums import AttemptStatus, CaseStatus, TaskStatus
from app.errors import APIError
from app.models import Absence, Case, CoverageAttempt, CoveragePlan, Employee, PolicyVersion
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


# A07: lifecycle transitions are deliberately centralized here. The planner,
# approval, callback and task-completion services must call this module within
# their own transaction; none may set Case.status directly.
CASE_TRANSITIONS: dict[CaseStatus, frozenset[CaseStatus]] = {
    CaseStatus.OPEN: frozenset({CaseStatus.PLANNING}),
    CaseStatus.PLANNING: frozenset({
        CaseStatus.PENDING_APPROVAL, CaseStatus.AWAITING_RESPONSES,
        CaseStatus.COVERAGE_CONFIRMED, CaseStatus.CLOSED_WITH_GAPS,
    }),
    CaseStatus.PENDING_APPROVAL: frozenset({
        CaseStatus.PLANNING, CaseStatus.AWAITING_RESPONSES,
        CaseStatus.COVERAGE_CONFIRMED, CaseStatus.CLOSED_WITH_GAPS,
    }),
    CaseStatus.AWAITING_RESPONSES: frozenset({
        CaseStatus.PLANNING, CaseStatus.PENDING_APPROVAL,
        CaseStatus.COVERAGE_CONFIRMED, CaseStatus.CLOSED_WITH_GAPS,
    }),
    CaseStatus.COVERAGE_CONFIRMED: frozenset({CaseStatus.COMPLETED}),
    CaseStatus.CLOSED_WITH_GAPS: frozenset(),
    CaseStatus.COMPLETED: frozenset(),
}

PENDING_ATTEMPTS = frozenset({
    AttemptStatus.PROPOSED, AttemptStatus.PENDING_APPROVAL,
    AttemptStatus.RESERVED, AttemptStatus.NOTIFIED,
})


def _case_facts(session: Session, case: Case) -> tuple[list, list, bool]:
    """Read actual assignments; an accepted offer alone is NOT coverage."""
    tasks = list(case.tasks)
    attempts = list(session.scalars(
        select(CoverageAttempt).where(CoverageAttempt.case_id == case.case_id)
    ))
    accepted = {
        (attempt.task_id, attempt.candidate_employee_id)
        for attempt in attempts if attempt.status == AttemptStatus.ACCEPTED
    }
    fully_covered = bool(tasks) and all(
        (task.task_id, task.assignee_employee_id) in accepted
        for task in tasks
    )
    return tasks, attempts, fully_covered


def derive_case_status(session: Session, case: Case) -> CaseStatus:
    """Calculate lifecycle status from committed tasks and persisted attempts.

    An unplanned empty case remains open; an escalated uncovered task means a
    gap, never 100% coverage. A failed response without a new plan returns to
    planning rather than pretending that re-planning already happened.
    """
    tasks, attempts, fully_covered = _case_facts(session, case)
    active = {attempt.status for attempt in attempts if attempt.status in PENDING_ATTEMPTS}

    if case.status in {CaseStatus.COMPLETED, CaseStatus.CLOSED_WITH_GAPS}:
        return case.status
    if case.plan_version == 0:
        return CaseStatus.PLANNING if case.status != CaseStatus.OPEN else CaseStatus.OPEN
    if AttemptStatus.PENDING_APPROVAL in active:
        return CaseStatus.PENDING_APPROVAL
    if active.intersection({AttemptStatus.RESERVED, AttemptStatus.NOTIFIED}):
        return CaseStatus.AWAITING_RESPONSES
    if AttemptStatus.PROPOSED in active:
        return CaseStatus.PLANNING
    if fully_covered:
        return (CaseStatus.COMPLETED if all(task.status == TaskStatus.DONE for task in tasks)
                else CaseStatus.COVERAGE_CONFIRMED)
    if any(attempt.status == AttemptStatus.ESCALATED for attempt in attempts):
        return CaseStatus.CLOSED_WITH_GAPS
    return CaseStatus.PLANNING


def transition_case(
    session: Session,
    case: Case,
    new_status: CaseStatus,
    *,
    actor: str,
    reason: str | None = None,
    at: datetime | None = None,
) -> bool:
    """Validate, persist and audit one transition in the caller's transaction.

    Returns False for an idempotent no-op. The caller owns commit/rollback so
    the case and the business operation stay atomic.
    """
    if not actor or not actor.strip():
        raise ValueError("actor is required for an auditable transition")
    try:
        target = CaseStatus(new_status)
    except ValueError:
        raise APIError(409, "INVALID_CASE_TRANSITION", "Estado de caso inválido", {
            "case_id": case.case_id,
        }) from None
    tasks, attempts, fully_covered = _case_facts(session, case)
    if case.status == target:
        return False
    if target not in CASE_TRANSITIONS[case.status]:
        raise APIError(409, "INVALID_CASE_TRANSITION", "Transição de caso não permitida", {
            "case_id": case.case_id, "from": case.status.value, "to": target.value,
        })

    active = {attempt.status for attempt in attempts if attempt.status in PENDING_ATTEMPTS}
    if target == CaseStatus.PENDING_APPROVAL and AttemptStatus.PENDING_APPROVAL not in active:
        raise APIError(409, "INVALID_CASE_TRANSITION", "Sem proposta aguardando BP", {
            "case_id": case.case_id,
        })
    if target == CaseStatus.AWAITING_RESPONSES and not active.intersection({
        AttemptStatus.RESERVED, AttemptStatus.NOTIFIED,
    }):
        raise APIError(409, "INVALID_CASE_TRANSITION", "Sem convite pendente", {
            "case_id": case.case_id,
        })
    if target in {CaseStatus.COVERAGE_CONFIRMED, CaseStatus.COMPLETED}:
        if not fully_covered or active:
            raise APIError(409, "CASE_COVERAGE_INCOMPLETE", "Existem tarefas sem cobertura confirmada", {
                "case_id": case.case_id,
            })
    if target == CaseStatus.COMPLETED and not all(task.status == TaskStatus.DONE for task in tasks):
        raise APIError(409, "CASE_TASKS_PENDING", "Existem tarefas não concluídas", {
            "case_id": case.case_id,
        })
    if target == CaseStatus.CLOSED_WITH_GAPS and (
        active or fully_covered or not any(
            attempt.status == AttemptStatus.ESCALATED for attempt in attempts
        )
    ):
        raise APIError(409, "INVALID_CASE_TRANSITION", "Encerramento exige lacuna escalada e nenhuma proposta pendente", {
            "case_id": case.case_id,
        })

    timestamp = at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None or timestamp < case.created_at:
        raise ValueError("transition time must be timezone-aware and after case creation")
    # Audit schema requires the immutable policy version for every lifecycle
    # event. Use the case's plan snapshot; before its first plan, use the
    # latest configured policy (and fail clearly if none has been seeded).
    policy_version = session.scalar(
        select(CoveragePlan.policy_version).where(
            CoveragePlan.case_id == case.case_id,
            CoveragePlan.plan_version == case.plan_version,
        )
    )
    if policy_version is None:
        policy_version = session.scalar(
            select(PolicyVersion.policy_version)
            .order_by(PolicyVersion.policy_version.desc()).limit(1)
        )
    if policy_version is None:
        raise APIError(409, "POLICY_NOT_CONFIGURED", "Política não configurada", {
            "case_id": case.case_id,
        })
    previous = case.status
    case.status = target
    if target in {CaseStatus.COMPLETED, CaseStatus.CLOSED_WITH_GAPS}:
        case.closed_at = timestamp
    audit.record(
        session,
        case_id=case.case_id,
        actor=actor,
        action="case.status_changed",
        timestamp=timestamp,
        policy_version=policy_version,
        reason=reason,
        result={"previous_status": previous.value, "status": target.value},
    )
    session.flush()
    return True


def recalculate_case_status(
    session: Session, case: Case, *, actor: str, reason: str | None = None,
    at: datetime | None = None,
) -> CaseStatus:
    """Reconcile persisted status after planning, decision or task completion."""
    target = derive_case_status(session, case)
    if target == CaseStatus.COMPLETED and case.status != CaseStatus.COVERAGE_CONFIRMED:
        # Completion never skips confirmation even if a test/source already
        # marked the underlying tasks done.
        target = CaseStatus.COVERAGE_CONFIRMED
    if case.status == CaseStatus.OPEN and target not in {
        CaseStatus.OPEN, CaseStatus.PLANNING,
    }:
        # Preserve the observable start-of-planning transition rather than
        # jumping directly from an open case to a later state.
        transition_case(session, case, CaseStatus.PLANNING,
                        actor=actor, reason=reason, at=at)
    if target != case.status:
        transition_case(session, case, target, actor=actor, reason=reason, at=at)
    return case.status
