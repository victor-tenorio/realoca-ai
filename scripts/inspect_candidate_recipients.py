"""Read-only diagnosis for SLACK_RECIPIENT_MISSING after POST /plan rollback.

From repo root:
    .\.venv\Scripts\python.exe scripts\inspect_candidate_recipients.py --case case-...
Does not commit or dispatch; no secret values or full Slack IDs are printed.
"""
import argparse
import json
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.db import SessionLocal
from app.engine import plan_coverage
from app.models import Case, Employee, PolicyVersion
from app.services.snapshot import build


def demo_policy():
    """Same defaults as PolicyVersion server defaults, used only if absent."""
    return PolicyVersion(
        policy_version=1, max_utilization_pct=Decimal("90"),
        critical_requires_bp=True, cross_team_requires_bp=True,
        response_timeout_minutes=15, allow_automatic_same_team=True,
        reminder_before_expiry_minutes=5, created_at=datetime.now(UTC),
    )


def diagnose(session, case_id):
    case = session.get(Case, case_id)
    if case is None:
        raise ValueError("case_id not found in this database")
    current_policy = session.scalar(
        select(PolicyVersion).order_by(PolicyVersion.policy_version.desc()).limit(1)
    ) or demo_policy()
    snap = build(session, case, policy=current_policy, plan_version=case.plan_version + 1)
    planned = plan_coverage(snap)
    candidates = []
    for item in planned["assignments"]:
        employee = session.get(Employee, item["candidate_employee_id"])
        recipient = (employee.channel_user_id or "").strip()
        channel = employee.preferred_channel.value if employee.preferred_channel else None
        candidates.append({
            "task_id": item["task_id"],
            "candidate_employee_id": employee.employee_id,
            "candidate_name": employee.name,
            "channel": channel,
            "recipient_configured": bool(recipient),
            "recipient_is_synthetic": recipient.startswith("synthetic-"),
            "needs_recipient_fix": channel != "slack" or not recipient,
        })
    eligible = {
        e["employee_id"] for e in snap["employees"] if e["availability"] == "available"
    }
    usable = session.scalars(select(Employee).where(Employee.employee_id.in_(eligible))).all()
    with_slack = sum(
        emp.preferred_channel is not None
        and emp.preferred_channel.value == "slack"
        and bool((emp.channel_user_id or "").strip())
        for emp in usable
    )
    return {
        "case_id": case.case_id,
        "current_case_status": case.status.value,
        "current_plan_version": case.plan_version,
        "planned_candidates": candidates,
        "planned_uncovered": planned["uncovered"],
        "available_employees_with_slack_recipient": with_slack,
        "available_employees_total": len(eligible),
        "dry_run": True,
        "database_modified": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    args = parser.parse_args()
    with SessionLocal() as session:
        result = diagnose(session, args.case)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
