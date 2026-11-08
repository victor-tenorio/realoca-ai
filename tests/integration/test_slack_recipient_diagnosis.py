"""Read-only diagnosis regression with a migrated synthetic demo database."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.demo.seed import seed_demo
from app.enums import TaskStatus
from app.models import Absence, Case, CoverageAttempt, Employee, Shift, Task
from scripts.inspect_candidate_recipients import diagnose


def test_diagnosis_finds_missing_slack_candidate_without_writes(session):
    seed_demo(session)
    task = session.scalar(select(Task).where(Task.status == TaskStatus.OPEN).limit(1))
    assert task is not None
    shift = session.get(Shift, task.shift_id)
    created = min(shift.starts_at + timedelta(minutes=1),
                  datetime.now(UTC) - timedelta(hours=1))
    absence = Absence(
        absence_id="diagnostic-absence", employee_id=task.assignee_employee_id,
        starts_at=shift.starts_at, ends_at=shift.ends_at, confirmed=True,
        source_system="diagnostic-test", external_id="abs-1", updated_at=created,
    )
    case = Case(case_id="diagnostic-case", created_at=created,
                status="open", plan_version=0, tasks=[task], absences=[absence])
    session.add(case)
    session.commit()

    initial = diagnose(session, case.case_id)
    assert initial["planned_candidates"]
    candidate = initial["planned_candidates"][0]
    assert candidate["recipient_configured"]
    emp = session.get(Employee, candidate["candidate_employee_id"])
    emp.channel_user_id = None
    session.commit()

    missing = diagnose(session, case.case_id)
    assert missing["planned_candidates"][0]["candidate_employee_id"] == emp.employee_id
    assert missing["planned_candidates"][0]["needs_recipient_fix"]
    assert not missing["planned_candidates"][0]["recipient_configured"]
    assert missing["dry_run"] is True
    assert missing["database_modified"] is False
    assert session.scalar(select(func.count()).select_from(CoverageAttempt)) == 0
    assert session.get(Case, case.case_id).plan_version == 0
