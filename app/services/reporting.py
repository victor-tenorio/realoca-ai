"""A17: audit and dashboard read persistent data, never decorative metrics."""

from sqlalchemy import select

from app.enums import AttemptStatus, CaseStatus, TaskStatus
from app.models import Absence, AuditEvent, Case, CoverageAttempt, Task
from app.models.workflow import case_tasks


def audit_timeline(session, *, case_id: str | None = None) -> dict:
    query = select(AuditEvent).order_by(AuditEvent.timestamp, AuditEvent.audit_event_id)
    if case_id is not None:
        query = query.where(AuditEvent.case_id == case_id)
    rows = list(session.scalars(query))
    return {"total": len(rows), "events": [{
        "audit_event_id": event.audit_event_id,
        "case_id": event.case_id,
        "attempt_id": event.attempt_id,
        "actor": event.actor,
        "action": event.action,
        "timestamp": event.timestamp.isoformat(),
        "policy_version": event.policy_version,
        "reason": event.reason,
        "result": event.result,
    } for event in rows]}


def _known_hours(tasks) -> float | None:
    items = list(tasks)
    if any(item.estimated_hours is None for item in items):
        return None
    return float(sum((item.estimated_hours for item in items), start=0))


def dashboard(session) -> dict:
    tasks = list(session.scalars(select(Task).join(case_tasks).distinct()))
    attempts = list(session.scalars(select(CoverageAttempt)))
    cases = list(session.scalars(select(Case)))
    by_task = {task.task_id: task for task in tasks}
    proposed_ids = {attempt.task_id for attempt in attempts
                    if attempt.status in {
                        AttemptStatus.PROPOSED, AttemptStatus.PENDING_APPROVAL,
                        AttemptStatus.RESERVED, AttemptStatus.NOTIFIED,
                        AttemptStatus.ACCEPTED,
                    }}
    accepted_ids = {attempt.task_id for attempt in attempts
                    if attempt.status == AttemptStatus.ACCEPTED
                    and by_task.get(attempt.task_id) is not None
                    and by_task[attempt.task_id].assignee_employee_id ==
                    attempt.candidate_employee_id}
    delivered_ids = {task.task_id for task in tasks if task.status == TaskStatus.DONE}
    return {
        "confirmed_absences": len(list(session.scalars(select(Absence.absence_id).where(
            Absence.confirmed.is_(True),
        )))),
        "cases_total": len(cases),
        "cases_open": sum(case.status not in {CaseStatus.COMPLETED,
                                               CaseStatus.CLOSED_WITH_GAPS}
                          for case in cases),
        "affected_tasks": len(tasks),
        "affected_hours": _known_hours(tasks),
        "planned_hours": _known_hours(by_task[id] for id in proposed_ids if id in by_task),
        "confirmed_hours": _known_hours(by_task[id] for id in accepted_ids),
        "completed_hours": _known_hours(by_task[id] for id in delivered_ids),
        "completed_tasks": len(delivered_ids),
        "in_progress_tasks": sum(task.status == TaskStatus.IN_PROGRESS for task in tasks),
        "without_confirmed_coverage": len(set(by_task) - accepted_ids),
        "affected_teams": len({task.team_id for task in tasks if task.team_id is not None}),
        "refusals": sum(item.status == AttemptStatus.REFUSED for item in attempts),
        "expirations": sum(item.status == AttemptStatus.EXPIRED for item in attempts),
        "escalations": sum(item.status == AttemptStatus.ESCALATED for item in attempts),
        "pending_bp": sum(item.status == AttemptStatus.PENDING_APPROVAL for item in attempts),
    }
