# Demonstração do histórico persistido

Caso: `case-5c3d64a2-c22a-4f92-b2af-25109f4f053c`.

Esta demonstração consulta o histórico existente. Não aciona planejamento,
dispatch, callbacks, aprovações ou processamento de expiração.

## Roteiro para apresentação

1. Abra o Realoca AI em `http://localhost:5173` no computador AMANDA.
2. Em **Casos de Ausência**, selecione o caso acima. Mostre as cinco tarefas
   afetadas e o plano na versão 2, com estado `awaiting_responses`.
3. Na tarefa `demo-operacoes-task-001`, compare as duas tentativas:
   `demo-operacoes-08` recusou na versão 1; `demo-operacoes-04` aparece com
   capacidade reservada na versão 2. Reserva não equivale a aceite ou conclusão.
4. Em **Auditoria**, filtre pelo ID completo do caso. A API possui 21 eventos
   desse caso. Mostre os eventos abaixo, em ordem cronológica.

| Horário em São Paulo (08/11/2026) | Evento | Evidência persistida |
| --- | --- | --- |
| 07:59:36 | `absence.confirmed` / `case.opened` / `impact.detected` | Ausência de `demo-operacoes-01`, cinco tarefas afetadas |
| 07:59:36 | `plan.proposed` | Versão 1, cinco propostas |
| 07:59:38 | `offer.dispatched` | Tentativa `att-13e9869e-b4d5-4364-80da-62bcd3ca62c1` |
| 08:06:10 | `offer.refused` | Ator `integration:n8n`, motivo “Recusa registrada no Slack”, liberação de 1,5h |
| 08:06:10 | `plan.replanned` | Nova tentativa `att-c5b04caf-d081-4a44-a17e-ebb66e65f7ca`, vinculada à tentativa recusada |
| 08:06:10 | `reservation.created` / `offer.queued` | Reserva de 1,5h para a nova tentativa e convite enfileirado |

Fala sugerida: “A recusa recebida pela integração ficou registrada e liberou
a reserva anterior. O motor selecionou outro candidato e gerou a versão 2,
preservando o vínculo com a tentativa recusada. A nova proposta está reservada;
isso ainda não comprova aceite nem cobertura confirmada.”

## Limites da evidência

- O prazo da nova tentativa era `2026-11-08T11:21:10.323472+00:00`, ou
  08:21:10 em São Paulo. Está no passado; o estado persistido ainda é
  `reserved`. Não apresentar esse convite como vigente nem alterar o estado
  apenas para a apresentação.
- O histórico contém `offer.queued` para a nova tentativa, mas não contém
  `offer.dispatched` ou aceite para ela. Não afirmar que o segundo convite foi
  entregue ou aceito.
- Os indicadores globais consultados são 11h planejadas, 1h confirmada e 0h
  concluída; não atribuir a hora confirmada a este caso. Os registros são dados
  persistidos da demonstração, não comprovação de operação em produção.
- Não clicar em ações de geração de plano, aprovação ou envio; não executar
  scripts de recusa, dispatch, seed, migração ou expiração para repetir a cena.

## Consultas de evidência

Ambas retornaram HTTP 200 pelo proxy do Vite:

- [Auditoria do caso](http://localhost:5173/api/v1/audit?case_id=case-5c3d64a2-c22a-4f92-b2af-25109f4f053c)
- [Detalhes do caso](http://localhost:5173/api/v1/cases/case-5c3d64a2-c22a-4f92-b2af-25109f4f053c)

A verificação utilizou somente GETs e uma conexão SQLite `mode=ro`.
O SHA-256 do dump lógico do banco foi comparado antes e depois das consultas,
com resultado idêntico. A validação das seis abas foi concluída em 08/11/2026
com Playwright e Chrome local, conectado ao backend real, sem mocks ou
requisições de escrita. Consulte [o relatório](evidencias/smoke-real.json) e
[a captura da auditoria](evidencias/06-auditoria.png).
