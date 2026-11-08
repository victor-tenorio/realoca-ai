"""A08: persist engine proposals, never invitations, reservations or assignments."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.engine import plan_coverage
from app.enums import ACTIVE_ATTEMPT_STATUSES, AttemptStatus, CaseStatus
from app.errors import APIError
from app.models import Case, CoverageAttempt, CoveragePlan, PolicyVersion
from app.services import audit, cases, dispatch, reservations, snapshot


def _validate_engine_result(result: dict, inputs: dict) -> None:
    """Do not persist a plan with ghost candidates or uncovered tasks omitted."""
    if (not isinstance(result, dict) or result.get("case_id") != inputs["case_id"]
            or result.get("plan_version") != inputs["plan_version"]
            or not isinstance(result.get("assignments"), list)
            or not isinstance(result.get("uncovered"), list)):
        raise APIError(503, "INVALID_ENGINE_RESULT", "Motor retornou plano inválido", {})
    tasks = {task["task_id"]: task for task in inputs["tasks"]}
    employees = {employee["employee_id"]: employee for employee in inputs["employees"]}
    ids = []
    for assignment in result["assignments"]:
        if not isinstance(assignment, dict):
            raise APIError(503, "INVALID_ENGINE_RESULT", "Proposta inválida", {})
        task_id = assignment.get("task_id")
        employee_id = assignment.get("candidate_employee_id")
        if (task_id not in tasks or employee_id not in employees
                or employees[employee_id]["availability"] != "available"
                or employee_id in inputs["absent_employee_ids"]
                or not set(tasks[task_id]["required_skills"]).issubset(employees[employee_id]["skills"])
                or assignment.get("estimated_hours") != tasks[task_id]["estimated_hours"]
                or not isinstance(assignment.get("reason"), str) or not assignment["reason"].strip()):
            raise APIError(503, "INVALID_ENGINE_RESULT", "Proposta inconsistente", {
                "task_id": task_id,
            })
        ids.append(task_id)
    for item in result["uncovered"]:
        if (not isinstance(item, dict) or item.get("task_id") not in tasks
                or not isinstance(item.get("reason_code"), str)
                or not item["reason_code"].strip()):
            raise APIError(503, "INVALID_ENGINE_RESULT", "Lacuna inválida", {})
        ids.append(item["task_id"])
    if len(ids) != len(set(ids)) or set(ids) != set(tasks):
        raise APIError(503, "INVALID_ENGINE_RESULT", "Motor duplicou ou omitiu tarefas", {})


def create_plan(
    session: Session,
    case: Case,
    *,
    actor: str,
    at: datetime | None = None,
) -> dict:
    """Create the *proposal* phase of a plan in the caller's transaction.

    A09/A10/A11 will classify and reserve or request approval; A12 will send
    offers. This function does not change the source task assignee.
    """
    if not actor or not actor.strip():
        raise ValueError("actor must identify the caller")
    if case.status not in {CaseStatus.OPEN, CaseStatus.PLANNING}:
        raise APIError(409, "CASE_NOT_PLANNABLE", "Caso não está aberto para planejamento", {
            "case_id": case.case_id,
        })
    active = session.scalar(select(CoverageAttempt.attempt_id).where(
        CoverageAttempt.case_id == case.case_id,
        CoverageAttempt.status.in_(ACTIVE_ATTEMPT_STATUSES),
    ).limit(1))
    if active is not None:
        raise APIError(409, "PLAN_ALREADY_ACTIVE", "Caso já possui proposta pendente", {
            "case_id": case.case_id,
        })
    policy = session.scalar(select(PolicyVersion).order_by(
        PolicyVersion.policy_version.desc()
    ).limit(1))
    if policy is None:
        raise APIError(409, "POLICY_NOT_CONFIGURED", "Política não configurada", {})
    timestamp = at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None or timestamp < case.created_at:
        raise ValueError("plan time must be aware and follow case creation")

    version = case.plan_version + 1
    inputs = snapshot.build(session, case, policy=policy, plan_version=version)
    result = plan_coverage(inputs)
    _validate_engine_result(result, inputs)

    plan = CoveragePlan(
        plan_id=f"plan-{uuid4()}", case_id=case.case_id,
        plan_version=version, policy_version=policy.policy_version,
        created_at=timestamp,
    )
    session.add(plan)
    case.plan_version = version
    session.flush()
    attempts = []
    for item in result["assignments"]:
        attempt = CoverageAttempt(
            attempt_id=f"att-{uuid4()}", case_id=case.case_id,
            plan_id=plan.plan_id, plan_version=version,
            policy_version=policy.policy_version,
            task_id=item["task_id"], candidate_employee_id=item["candidate_employee_id"],
            status=AttemptStatus.PROPOSED, reason=item["reason"], created_at=timestamp,
        )
        session.add(attempt)
        attempts.append(attempt)
    if case.status == CaseStatus.OPEN:
        cases.transition_case(session, case, CaseStatus.PLANNING, actor=actor,
                              reason="Plano global proposto", at=timestamp)
    audit.record(session, case_id=case.case_id, actor=actor,
                 action="plan.proposed", timestamp=timestamp,
                 policy_version=policy.policy_version,
                 result={"plan_id": plan.plan_id, "plan_version": version,
                         "proposals": len(attempts), "uncovered": result["uncovered"]})
    session.flush()
    return {
        "case_id": case.case_id, "plan_id": plan.plan_id,
        "plan_version": version,
        "proposals": [
            {"attempt_id": attempt.attempt_id, "task_id": attempt.task_id,
             "candidate_employee_id": attempt.candidate_employee_id,
             "status": attempt.status.value, "reason": attempt.reason}
            for attempt in attempts
        ],
        "uncovered": result["uncovered"], "metrics": result["metrics"],
    }


def plan_and_authorize(session: Session, case_id: str, *, actor: str) -> dict:
    """HTTP orchestration: propose, classify, reserve auto or await BP.

    All persisted changes (and the offer outbox) share one writer-locked
    transaction. Delivery is a later side effect from the durable outbox.
    """
    with session.begin():
        if session.get_bind().dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        case = session.get(Case, case_id)
        if case is None:
            raise APIError(404, "CASE_NOT_FOUND", "Caso não encontrado", {})
        if session.scalar(select(PolicyVersion.policy_version).limit(1)) is None:
            # The demo's policy is a real versioned row, not a mutable total.
            session.add(PolicyVersion(policy_version=1, created_at=datetime.now(UTC)))
            session.flush()
        result = create_plan(session, case, actor=actor)
        enriched = []
        for proposal in result["proposals"]:
            attempt = session.get(CoverageAttempt, proposal["attempt_id"])
            try:
                reservations.reserve_locked(session, attempt, actor=actor)
            except APIError as exc:
                if exc.code != "BP_APPROVAL_REQUIRED":
                    raise
                attempt.status = AttemptStatus.PENDING_APPROVAL
                audit.record(session, case_id=case.case_id,
                             attempt_id=attempt.attempt_id, actor=actor,
                             action="proposal.pending_approval",
                             timestamp=datetime.now(UTC),
                             policy_version=attempt.policy_version,
                             result={"reason_code": exc.details["reason_code"]})
                cases.recalculate_case_status(session, case, actor=actor,
                                              reason="Aguardando decisão BP")
                policy_action = "needs_approval"
            else:
                dispatch.queue_offer(session, attempt, actor=actor)
                policy_action = "auto"
            enriched.append({
                "attempt_id": attempt.attempt_id, "task_id": attempt.task_id,
                "candidate_employee_id": attempt.candidate_employee_id,
                "policy_action": policy_action, "status": attempt.status.value,
                "reason": proposal["reason"],
            })
        session.flush()
        return {"case_id": result["case_id"], "plan_id": result["plan_id"],
                "plan_version": result["plan_version"],
                "proposals": enriched, "uncovered": result["uncovered"]}
