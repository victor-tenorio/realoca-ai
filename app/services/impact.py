"""Internal impact analysis and append-only observations; never allocate or repair."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.errors import APIError
from app.models import Absence, AuditEvent, Case, Task
from app.models.workflow import case_absences, case_tasks
from app.services import audit, task_source
from app.services.capacity import ZERO, sum_known_hours

IMPACT_ACTIONS = ("impact.detected", "impact.no_registered_tasks")


@dataclass(frozen=True)
class ImpactAnalysis:
    records: list[Task]
    known_hours_at_risk: Decimal
    hours_at_risk: Decimal | None
    payload: dict


@dataclass(frozen=True)
class ImpactReport:
    original: dict
    current: ImpactAnalysis
    audit_event_id: str
    changed: bool


def task_evidence(task: Task) -> dict:
    return {
        "task_id": task.task_id,
        "title": task.title,
        "team_id": task.team_id,
        "assignee_employee_id": task.assignee_employee_id,
        "assignee_team_id": task.assignee.team_id if task.assignee else None,
        "shift_id": task.shift_id,
        "priority": task.priority.value if task.priority else None,
        "status": task.status.value,
        "required_skills": (
            sorted(skill.skill_id for skill in task.required_skills)
            if task.required_skills_known
            else None
        ),
        "estimated_hours": float(task.estimated_hours)
        if task.estimated_hours is not None
        else None,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "transfer_allowed": task.transfer_allowed,
        "source_system": task.source_system,
        "external_id": task.external_id,
        "updated_at": task.updated_at.isoformat(),
    }


def prepare_analysis(
    session: Session, absence: Absence, historical_ids: list[str] | None = None
) -> ImpactAnalysis:
    if not absence.confirmed:
        raise APIError(
            422, "ABSENCE_NOT_CONFIRMED", "A análise exige ausência confirmada", {}
        )
    records = task_source.open_tasks_for_absence(
        session, absence.employee_id, absence.starts_at, absence.ends_at
    )
    current_ids = [task.task_id for task in records]
    all_ids = sorted(set(historical_ids or []) | set(current_ids))
    historical_records = {task.task_id: task for task in records}
    historical_records.update(
        {
            task.task_id: task
            for task in task_source.tasks_by_ids(
                session,
                [
                    identifier
                    for identifier in all_ids
                    if identifier not in historical_records
                ],
            )
        }
    )
    evidence = [task_evidence(task) for task in records]
    historical = [
        task_evidence(historical_records[identifier])
        for identifier in all_ids
        if identifier in historical_records
    ]
    reference = task_source.reference_shift(session)
    issues = []
    if reference is None:
        issues.append(
            {"task_id": None, "kind": "data_quality", "fields": ["reference_shift"]}
        )
    for entry in historical:
        missing = [
            field
            for field in (
                "estimated_hours",
                "team_id",
                "assignee_employee_id",
                "assignee_team_id",
                "required_skills",
                "priority",
                "due_at",
                "transfer_allowed",
            )
            if entry[field] is None
        ]
        if missing:
            issues.append(
                {"task_id": entry["task_id"], "kind": "data_quality", "fields": missing}
            )
    for identifier in all_ids:
        if identifier not in historical_records:
            issues.append(
                {
                    "task_id": identifier,
                    "kind": "data_quality",
                    "fields": ["task_record"],
                }
            )
    known_hours = sum(
        (task.estimated_hours for task in records if task.estimated_hours is not None),
        ZERO,
    )
    total_hours = sum_known_hours(task.estimated_hours for task in records)
    divergences = [
        {
            "kind": "rh_task_assignment",
            "absence_id": absence.absence_id,
            "task_id": task.task_id,
            "employee_id": absence.employee_id,
            "source_system": task.source_system,
            "external_id": task.external_id,
            "task_updated_at": task.updated_at.isoformat(),
            "correction_confirmed": False,
        }
        for task in records
    ]
    payload = {
        "schema_version": 1,
        "absence_id": absence.absence_id,
        "employee_id": absence.employee_id,
        "absence_source": {
            "source_system": absence.source_system,
            "external_id": absence.external_id,
            "updated_at": absence.updated_at.isoformat(),
        },
        "period": {
            "starts_at": absence.starts_at.isoformat(),
            "ends_at": absence.ends_at.isoformat(),
            "reference_date": task_source.DEMO_REFERENCE_DATE.isoformat(),
            "shift_id": reference.shift_id if reference else None,
            "shift_starts_at": reference.starts_at.isoformat() if reference else None,
            "shift_ends_at": reference.ends_at.isoformat() if reference else None,
        },
        "task_ids": current_ids,
        "task_count": len(records),
        "known_hours_at_risk": float(known_hours),
        "hours_at_risk": float(total_hours) if total_hours is not None else None,
        "estimates_complete": total_hours is not None,
        "data_complete": not issues,
        "data_quality_issues": issues,
        "tasks": evidence,
        "historical_task_ids": all_ids,
        "historical_tasks": historical,
        "divergence_detected": bool(records),
        "divergences": divergences,
        "coverage_confirmed": False,
        "source_scope": "registered_tasks_in_reference_shift",
    }
    return ImpactAnalysis(records, known_hours, total_hours, payload)


def record_analysis(
    session: Session,
    case: Case,
    absence: Absence,
    analysis: ImpactAnalysis,
    observed_at: datetime,
) -> ImpactReport:
    """Caller owns a serialized write transaction; flush but never commit here."""
    events = list(
        session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.case_id == case.case_id,
                AuditEvent.action.in_(IMPACT_ACTIONS),
            )
            .order_by(AuditEvent.timestamp, AuditEvent.audit_event_id)
        )
    )
    events = [
        event
        for event in events
        if event.result.get("absence_id") == absence.absence_id
    ]
    payload = {**analysis.payload, "case_id": case.case_id}
    fingerprint = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()
    if events and events[-1].result.get("fingerprint") == fingerprint:
        return ImpactReport(
            dict(events[0].result), analysis, events[-1].audit_event_id, False
        )
    associated = set(
        session.scalars(
            select(case_tasks.c.task_id).where(case_tasks.c.case_id == case.case_id)
        )
    )
    new_ids = sorted(set(payload["task_ids"]) - associated)
    if new_ids:
        session.execute(
            case_tasks.insert(),
            [
                {"case_id": case.case_id, "task_id": identifier}
                for identifier in new_ids
            ],
        )
    if events:
        observed_at = max(observed_at, events[-1].timestamp + timedelta(microseconds=1))
    stored = {
        **payload,
        "fingerprint": fingerprint,
        "detected_at": observed_at.isoformat(),
        "original_audit_event_id": events[0].audit_event_id if events else None,
    }
    event = audit.record(
        session,
        case_id=case.case_id,
        actor="api:impact",
        action="impact.detected" if analysis.records else "impact.no_registered_tasks",
        timestamp=observed_at,
        result=stored,
    )
    session.flush()
    return ImpactReport(
        dict(events[0].result) if events else stored,
        analysis,
        event.audit_event_id,
        True,
    )


def analyze_case(session: Session, case_id: str, absence_id: str) -> ImpactReport:
    """Explicit internal reanalysis. Creation retries never call this operation."""
    with session.begin():
        if session.get_bind().dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        case = session.get(Case, case_id)
        absence = session.get(Absence, absence_id)
        if case is None or absence is None:
            raise APIError(
                404, "IMPACT_CONTEXT_NOT_FOUND", "Caso ou ausência não encontrado", {}
            )
        linked = session.scalar(
            select(case_absences.c.absence_id).where(
                case_absences.c.case_id == case_id,
                case_absences.c.absence_id == absence_id,
            )
        )
        if linked is None:
            raise APIError(
                409, "ABSENCE_CASE_MISMATCH", "Ausência não pertence ao caso", {}
            )
        historical_ids = list(
            session.scalars(
                select(case_tasks.c.task_id).where(case_tasks.c.case_id == case_id)
            )
        )
        analysis = prepare_analysis(session, absence, historical_ids)
        report = record_analysis(session, case, absence, analysis, datetime.now(UTC))
    return report
