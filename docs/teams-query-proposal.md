# Proposta de consulta de equipes — pendente de alinhamento

`GET /api/v1/teams` **não está no contrato v1.1 e não foi publicado**. A proposta
abaixo precisa ser acordada com os consumidores antes de alterar o contrato.

Resposta proposta: HTTP 200, array JSON sem envelope, sem paginação ou filtros.
Leitura do turno selecionado por `DEMO_REFERENCE_DATE`, seguindo as demais
listagens. Autenticação das consultas deverá ser alinhada com a política futura
do frontend; as consultas existentes não exigem token interno do n8n.

Schema proposto (Pydantic ilustrativo, não registrado na aplicação):

```python
from datetime import date
from pydantic import BaseModel, ConfigDict

class TeamResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    team_id: str
    name: str
    reference_date: date
    employee_count: int
    shift_hours: float | None
    committed_hours: float | None
    reserved_hours: float
    occupied_hours: float | None
    utilization_pct: float | None
    complete: bool

# Resposta: list[TeamResponse]
```

Exemplo derivável do seed, sem reservas:

```json
[
  {
    "team_id": "demo-atendimento",
    "name": "Atendimento",
    "reference_date": "2026-11-08",
    "employee_count": 10,
    "shift_hours": 80,
    "committed_hours": 47.5,
    "reserved_hours": 0,
    "occupied_hours": 47.5,
    "utilization_pct": 59.375,
    "complete": true
  }
]
```

Regras propostas:

- Equipes e nomes vêm de `teams`; pessoas são agrupadas por equipe atual.
  A carga acompanha o responsável atual, preservando a origem de cada tarefa.
- `shift_hours` soma capacidades dos membros no turno. Compromisso soma tarefas
  abertas; reserva soma registros ativos destinados aos membros no mesmo turno.
- Utilização é `100 × soma da ocupação / soma da capacidade`, com Decimal nos
  cálculos. Não é a média dos percentuais individuais. A capacidade zero entra
  como zero conhecido; denominador total zero produz utilização não aplicável.
- Capacidade ou estimativa desconhecida torna o agregado correspondente `null`
  e `complete=false`; nunca se publica uma soma parcial como total conhecido.
  Equipe sem membros tem capacidade/carga zero e utilização `null`.
- Pessoas sem equipe impediriam a publicação com HTTP 422, para não ocultar
  pessoas e carga sem atribuição organizacional. Não se cria equipe fictícia.
- O percentual pode exceder 90% ou 100% para cargas preexistentes. O limite da
  política controla admissões futuras, não a possibilidade de exibir a carga.

Também dependem de alinhamento filtros futuros por equipe, responsável, status
ou prioridade nas demais listagens. Não estão disponíveis nesta entrega.
