# Exemplos observados nas consultas

Obtidos por `TestClient` com migrações e seed em SQLite descartável, usando a
referência 2026-11-08. As respostas completas tinham 40 funcionários e 187
tarefas. Os arrays abaixo mostram um registro de cada resposta, sem mudar
o formato retornado pelas rotas.

`GET /api/v1/employees` — primeiro registro:

```json
[
  {
    "employee_id": "demo-atendimento-01",
    "name": "Ana Luz",
    "team_id": "demo-atendimento",
    "skills": ["chat", "crm", "ingles", "reclamacoes", "telefone"],
    "shift_hours": 8.0,
    "committed_hours": 5.5,
    "reserved_hours": 0.0,
    "availability": "available",
    "preferred_channel": "slack",
    "channel_user_id": "synthetic-atendimento-01",
    "source_system": "hr_simulator",
    "external_id": "employee-atendimento-01",
    "updated_at": "2026-11-08T11:00:00Z"
  }
]
```

`GET /api/v1/tasks` — segundo registro:

```json
[
  {
    "task_id": "demo-atendimento-task-002",
    "title": "Atendimento internacional",
    "assignee_employee_id": "demo-atendimento-02",
    "team_id": "demo-atendimento",
    "priority": "medium",
    "due_at": "2026-11-08T19:00:00Z",
    "estimated_hours": 1.0,
    "required_skills": ["ingles"],
    "status": "open",
    "transfer_allowed": true,
    "source_system": "task_simulator",
    "external_id": "task-atendimento-002",
    "updated_at": "2026-11-08T11:00:00Z"
  }
]
```
