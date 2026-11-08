"""Record RH/task divergence as an immutable audit result, without repairing it."""

from app.models import Task


def absence_impact(employee_id: str, tasks: list[Task]) -> dict:
    return {
        "employee_id": employee_id,
        "task_ids": [task.task_id for task in tasks],
        "task_count": len(tasks),
        "divergence_detected": bool(tasks),
        "coverage_confirmed": False,
        "source_scope": "registered_tasks_in_reference_shift",
    }
