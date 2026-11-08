# Verificação de prontidão da demo (V17)

Com o FastAPI rodando no computador da Amanda (porta 8001), execute na raiz de realoca-ai:

    .\.venv\Scripts\python.exe scripts\inspect_demo.py --base http://127.0.0.1:8001

Este comando **só faz GET** a /api/v1/cases e /api/v1/cases/{case_id}. Não aciona
n8n, Slack, planejamento nem callback, e não consome créditos do n8n.
A saída não inclui nomes, e-mails nem credenciais. Retorna:

- total_cases: total de casos.
- shown_cases: até dez casos, com case_id e tentativas/attempt_id/status.
- ready_offers: quantas ofertas têm status notified e prazo de resposta futuro.

Se ready_offers > 0, há ao menos uma oferta indicada pelo backend como despachada
e dentro do prazo. Isso **não garante** que a mensagem Slack esteja visível ou
que o retorno funciona. Clique no Slack apenas após identificar a oferta certa.
Se ready_offers = 0, **não inventar attempt_id**: verificar se há casos,
se foram planejados, se exigem aprovação BP, e se o envio ao webhook foi
reconhecido. Ação de planejamento é POST /api/v1/cases/{case_id}/plan (não faz
parte deste script de leitura).

Após clique real, verifique:
- GET /api/v1/cases/{case_id} — proposta accepted/refused e atribuição de tarefa;
- GET /api/v1/audit?case_id=... — offer.queued, offer.dispatched,
  offer.accepted / offer.refused, replanejamento ou erro.

HTTP 202 em /api/v1/integrations/attempt-events só confirma inbox; o estado
da tentativa e a auditoria são a prova da execução de negócio. O código já
executa process_event em background após o recebimento e oferece recuperação
manual se ocorrer falha após o 202.

Teste sem servidor:

    .\.venv\Scripts\python.exe -m unittest discover -s scripts/tests -p test_inspect_demo.py -v

Limitação: verifica somente o banco acessível localmente e não prova que o
n8n V2 publicado está processando eventos. Não publicar dados reais
em logs/prints; para o hackathon, utilizar dados fictícios.
