"""A18: task-source completion, independent from an accepted coverage offer."""

from datetime import UTC, datetime

from sqlalchemy import select, text

from app.enums import AttemptStatus, TaskStatus
from app.errors import APIError
from app.models import Case, CoverageAttempt, PolicyVersion, Task
from app.models.workflow import case_tasks
from app.services import audit, cases


def complete_task(session, task_id: str, *, actor: str = "source:simulated") -> dict:
    with session.begin():
        if session.get_bind().dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        task = session.get(Task, task_id)
        if task is None:
            raise APIError(404, "TASK_NOT_FOUND", "Tarefa não encontrada", {})
        if task.status == TaskStatus.DONE:
            return {"task_id": task_id, "status": "done", "duplicate": True}
        linked_cases = list(session.scalars(select(Case).join(case_tasks).where(
            case_tasks.c.task_id == task_id,
        )))
        for case in linked_cases:
            accepted = session.scalar(select(CoverageAttempt).where(
                CoverageAttempt.case_id == case.case_id,
                CoverageAttempt.task_id == task_id,
                CoverageAttempt.status == AttemptStatus.ACCEPTED,
                CoverageAttempt.candidate_employee_id == task.assignee_employee_id,
            ).limit(1))
            if accepted is None:
                raise APIError(409, "TASK_NOT_ACCEPTED", "Cobertura ainda não confirmada", {
                    "case_id": case.case_id,
                })
        now = datetime.now(UTC)
        task.status = TaskStatus.DONE
        task.updated_at = now
        policy_version = session.scalar(select(PolicyVersion.policy_version).order_by(
            PolicyVersion.policy_version.desc()).limit(1))
        if policy_version is None:
            policy_version = 1
            session.add(PolicyVersion(policy_version=1, created_at=now))
            session.flush()
        for case in linked_cases:
            accepted = session.scalar(select(CoverageAttempt).where(
                CoverageAttempt.case_id == case.case_id,
                CoverageAttempt.task_id == task_id,
                CoverageAttempt.status == AttemptStatus.ACCEPTED,
            ).limit(1))
            audit.record(session, case_id=case.case_id,
                         attempt_id=accepted.attempt_id,
                         actor=actor, action="task.completed", timestamp=now,
                         policy_version=accepted.policy_version,
                         result={"task_id": task.task_id,
                                 "assignee_employee_id": task.assignee_employee_id,
                                 "released_committed_hours": float(task.estimated_hours or 0)})
            cases.recalculate_case_status(session, case, actor=actor,
                                          reason="Tarefa efetivamente concluída", at=now)
        if not linked_cases:
            audit.record(session, case_id=None, actor=actor,
                         action="task.completed", timestamp=now,
                         policy_version=policy_version,
                         result={"task_id": task.task_id,
                                 "assignee_employee_id": task.assignee_employee_id})
        session.flush()
        return {"task_id": task_id, "status": "done", "duplicate": False}
