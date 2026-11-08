import { describe, expect, it } from "vitest";
import { presentStatus } from "./status-presentation";

describe("domain status semantics", () => {
  it("keeps reservation, notification, acceptance and case coverage distinct", () => {
    expect(presentStatus("attempt", "reserved").description).toContain("não significa aceite");
    expect(presentStatus("attempt", "notified").label).toBe("Notificação enviada");
    expect(presentStatus("attempt", "accepted").description).toContain("não equivale");
    expect(presentStatus("case", "coverage_confirmed").label).toBe("Cobertura confirmada");
  });

  it("distinguishes candidate refusal from BP rejection and task completion", () => {
    expect(presentStatus("attempt", "refused").label).toBe("Proposta recusada");
    expect(presentStatus("attempt", "rejected_by_bp").description).toContain("não equivale a recusa do candidato");
    expect(presentStatus("task", "done").label).toBe("Tarefa concluída");
  });

  it("does not map an unknown state to a known successful state", () => {
    expect(presentStatus("attempt", "new_status")).toMatchObject({
      label: "Estado desconhecido",
      tone: "neutral",
    });
  });
});
