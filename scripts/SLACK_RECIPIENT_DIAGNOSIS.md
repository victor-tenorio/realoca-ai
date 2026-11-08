# Diagnóstico rápido: SLACK_RECIPIENT_MISSING

O erro do backend aparece quando o motor escolhe um funcionário sem
\`preferred_channel=slack\` ou sem \`channel_user_id\`. O POST de planejamento
é transacional: o erro reverte as alterações da tentativa.

Com FastAPI/Cloudflare abertos, no PowerShell da Amanda, na raiz do projeto:

    git pull origin main
    .\.venv\Scripts\python.exe scripts\inspect_candidate_recipients.py --case case-9a9b8667-86ae-447a-be45-d571614144e8

O comando apenas lê o SQLite, aplica o mesmo motor de propostas em memória e
exibe ID/nome do candidato, se o campo destinatário está configurado, se é
sintético e se precisa de correção. Não faz commit, não cria proposta, não chama
n8n ou Slack. **Nunca envia token.**

Se \`needs_recipient_fix=true\`, identificar o funcionário correto e
configurar o \`channel_user_id\` correspondente a uma conta Slack de teste,
com autorização, na fonte de dados de demonstração. Não usar ID do canal no
campo de usuário e não gerar uma identidade fictícia para afirmar DM real.
O workflow atual envia ao canal compartilhado, não à DM individual;
esta etapa não conclui V06. Após corrigir no banco de demonstração e rever
o resultado, repetir POST /plan **uma única vez**.

Se ainda não há funcionários com destinatário, a equipe precisa decidir
quais contas fictícias de teste representarão os candidatos. Nunca desligar
a validação do backend apenas para obter HTTP 200.

O comando não fornece confirmação de que um convite chegou ao Slack;
o teste de ponta a ponta ainda exige o envio real da proposta.
