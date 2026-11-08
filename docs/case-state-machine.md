# A07 — Estado do caso de continuidade

O estado oficial do caso é mantido em `app/services/cases.py`. Este módulo não
cria convites, não altera capacidade nem conclui tarefas: serviços de plano,
aprovação, callbacks e conclusão devem chamar `recalculate_case_status(...)`
**na mesma transação** em que persistem as ações correspondentes.

## Transições

| De | Para |
| --- | --- |
| `open` | `planning` |
| `planning` | `pending_approval`, `awaiting_responses`, `coverage_confirmed`, `closed_with_gaps` |
| `pending_approval` | `planning`, `awaiting_responses`, `coverage_confirmed`, `closed_with_gaps` |
| `awaiting_responses` | `planning`, `pending_approval`, `coverage_confirmed`, `closed_with_gaps` |
| `coverage_confirmed` | `completed` |
| `closed_with_gaps`, `completed` | terminais |

Quando a reconciliação encontra uma mudança a partir de `open`, registra
primeiro `open → planning`. Quando todas as tarefas já estão concluídas, passa
por `coverage_confirmed` antes de `completed`. Mudança repetida é idempotente.

## Regras de segurança

- Aprovação BP exige proposta realmente `pending_approval`; espera de resposta
  exige tentativa `reserved` ou `notified`.
- `coverage_confirmed` exige **cada tarefa vinculada** atribuída ao candidato
  de uma tentativa `accepted` e nenhuma tentativa pendente. Só um convite ou
  aceite sem atualização da fonte não constitui cobertura.
- `completed` exige cobertura já confirmada e **todas** as tarefas `done`.
- `closed_with_gaps` exige ao menos uma tentativa `escalated`, sem proposta
  pendente e sem cobertura completa.
- Caso recém-aberto sem tarefas não conta como cobertura total; permanece
  aberto até início explícito de planejamento.
- Transições inválidas retornam 409; alterações de status registram ator,
  motivo, horário, estado anterior, novo estado e versão imutável da política
  na auditoria. Estado e auditoria fazem parte da transação do chamador.

**Integração:**

```python
recalculate_case_status(session, case, actor="api:attempt-events", reason="offer.accepted")
# Quem chama confirma ou reverte a transação, junto com a transferência da tarefa.
```

**Escopo:** A07 fornece somente o serviço de estado e os testes de regressão;
os endpoints e demais efeitos são responsabilidades das etapas de integração.
As transições entre estados do caso formalizam uma interpretação do contrato:
casos de reabertura após encerramento devem ser definidos antes de implementados.
