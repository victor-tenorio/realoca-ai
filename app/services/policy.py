"""A09: deterministic, explainable classification of a proposed transfer."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.enums import Priority, TaskStatus
from app.models import Employee, PolicyVersion, Task
from app.services.capacity import Capacity


@dataclass(frozen=True)
class Decision:
    action: Literal["auto", "needs_approval", "inviable"]
    reason_code: str
    reason: str


def classify(
    task: Task,
    employee: Employee,
    policy: PolicyVersion,
    capacity: Capacity,
    *,
    absent_employee_ids: set[str],
) -> Decision:
    """Revalidate a proposal; a language model never grants authorization."""
    def blocked(code: str, reason: str) -> Decision:
        return Decision("inviable", code, reason)

    if task.status == TaskStatus.DONE:
        return blocked("TASK_ALREADY_DONE", "Tarefa já está concluída")
    if task.transfer_allowed is not True:
        return blocked("TRANSFER_NOT_ALLOWED", "Transferência não permitida ou desconhecida")
    if task.estimated_hours is None or task.estimated_hours <= 0:
        return blocked("UNKNOWN_EFFORT", "Esforço da tarefa desconhecido")
    if employee.employee_id in absent_employee_ids:
        return blocked("CANDIDATE_ABSENT", "Funcionário ausente")
    if not task.required_skills_known or not employee.skills_known:
        return blocked("UNKNOWN_SKILLS", "Competências não confirmadas")
    required = {item.skill_id for item in task.required_skills}
    available = {item.skill_id for item in employee.skills}
    if not required.issubset(available):
        return blocked("SKILL_MISMATCH", "Competências obrigatórias insuficientes")
    if not capacity.complete or capacity.reassignment_margin_hours is None:
        return blocked("UNKNOWN_CAPACITY", "Capacidade restante desconhecida")
    # The Capacity passed here must be calculated using *this* policy version.
    occupied = capacity.committed_hours + capacity.reserved_hours
    remaining = max(Decimal(0),
                    capacity.shift_hours * policy.max_utilization_pct / 100 - occupied)
    if remaining < task.estimated_hours:
        return blocked("INSUFFICIENT_CAPACITY", "Horas disponíveis abaixo do esforço")
    if task.priority is None:
        return blocked("UNKNOWN_PRIORITY", "Prioridade da tarefa desconhecida")
    if task.priority == Priority.CRITICAL and policy.critical_requires_bp:
        return Decision("needs_approval", "CRITICAL_TASK", "Tarefa crítica exige aprovação BP")
    same_team = task.team_id is not None and task.team_id == employee.team_id
    if not same_team and policy.cross_team_requires_bp:
        return Decision("needs_approval", "CROSS_TEAM", "Transferência entre equipes exige BP")
    if same_team and not policy.allow_automatic_same_team:
        return Decision("needs_approval", "SAME_TEAM_RESTRICTED", "Política exige BP para mesma equipe")
    return Decision("auto", "POLICY_AUTO", "Transferência elegível para convite automático")
