type StatusEntity = "task" | "case" | "attempt";
type Tone = "positive" | "pending" | "attention" | "neutral";

const presentations: Record<StatusEntity, Record<string, { label: string; description: string; tone: Tone }>> = {
  task: {
    open: { label: "Tarefa aberta", description: "A tarefa aguarda execução.", tone: "neutral" },
    in_progress: { label: "Tarefa em andamento", description: "A execução da tarefa foi iniciada.", tone: "pending" },
    done: { label: "Tarefa concluída", description: "A tarefa foi marcada como concluída.", tone: "positive" },
  },
  case: {
    open: { label: "Caso aberto", description: "O caso foi registrado; cobertura ainda não foi confirmada.", tone: "neutral" },
    planning: { label: "Planejamento iniciado", description: "O caso está em planejamento.", tone: "pending" },
    pending_approval: { label: "Aprovação pendente", description: "Uma decisão do BP ainda é necessária.", tone: "pending" },
    awaiting_responses: { label: "Aguardando respostas", description: "Existem propostas sem resposta final.", tone: "pending" },
    coverage_confirmed: { label: "Cobertura confirmada", description: "O estado do caso indica cobertura confirmada.", tone: "positive" },
    closed_with_gaps: { label: "Encerrado com lacunas", description: "Uma ou mais tarefas permaneceram sem cobertura.", tone: "attention" },
    completed: { label: "Caso concluído", description: "O caso foi concluído conforme o estado do backend.", tone: "positive" },
  },
  attempt: {
    proposed: { label: "Proposta criada", description: "Uma proposta foi criada; ainda não foi aceita.", tone: "pending" },
    pending_approval: { label: "Aprovação pendente", description: "A proposta aguarda decisão do BP.", tone: "pending" },
    reserved: { label: "Capacidade reservada", description: "Há reserva de capacidade; isso não significa aceite.", tone: "pending" },
    notified: { label: "Notificação enviada", description: "A oferta foi enviada e aguarda resposta.", tone: "pending" },
    accepted: { label: "Proposta aceita", description: "O candidato aceitou; isso não equivale ao estado cobertura_confirmed do caso.", tone: "positive" },
    refused: { label: "Proposta recusada", description: "A recusa não conclui a tarefa nem o caso.", tone: "attention" },
    expired: { label: "Proposta expirada", description: "O prazo de resposta terminou sem aceite.", tone: "attention" },
    rejected_by_bp: { label: "Negada pelo BP", description: "A aprovação foi negada; não equivale a recusa do candidato.", tone: "attention" },
    escalated: { label: "Proposta escalonada", description: "O caso requer atenção operacional.", tone: "attention" },
  },
};

export function presentStatus(entity: StatusEntity, value: string) {
  return presentations[entity][value] ?? {
    label: "Estado desconhecido",
    description: `Estado não reconhecido: ${value}`,
    tone: "neutral" as const,
  };
}
