import { describe, expect, it } from "vitest";
import {
  initialSlackDemoState,
  respondToSlackProposal,
  slackScenarios,
} from "./slack-demo";

const scenario = (id: string) => slackScenarios.find((item) => item.id === id)!;

describe("isolated Slack simulator", () => {
  it("records a local acceptance without claiming backend coverage", () => {
    const selected = scenario("accept");
    const result = respondToSlackProposal(selected, initialSlackDemoState(selected), "accept");

    expect(result.attempts[0].status).toBe("accepted");
    expect(result.outcome).toBe("accepted");
    expect(result.events.at(-1)?.text).toContain("Não há reserva, atribuição nem cobertura confirmada");
  });

  it("shows refusal and the need to replan", () => {
    const selected = scenario("refuse");
    const result = respondToSlackProposal(selected, initialSlackDemoState(selected), "refuse");

    expect(result.attempts).toEqual([{ employeeId: "demo-rafael", status: "refused" }]);
    expect(result.outcome).toBe("replanning-required");
    expect(result.events.at(-1)?.text).toContain("snapshot atualizado");
  });

  it("proposes the next fixture candidate and never reuses the refused one", () => {
    const selected = scenario("replan");
    const result = respondToSlackProposal(selected, initialSlackDemoState(selected), "refuse");

    expect(result.attempts).toEqual([
      { employeeId: "demo-lucas", status: "refused" },
      { employeeId: "demo-beatriz", status: "notified" },
    ]);
    expect(result.outcome).toBe("awaiting-response");
    expect(result.events.at(-1)?.text).toContain("excluído desta tarefa");
  });

  it("keeps the task uncovered when the fixture has no substitute", () => {
    const selected = scenario("no-substitute");
    const result = respondToSlackProposal(selected, initialSlackDemoState(selected), "refuse");

    expect(result.attempts[0].status).toBe("refused");
    expect(result.outcome).toBe("uncovered");
    expect(result.events.at(-1)?.text).toContain("requer escalonamento");
  });

  it("ignores duplicate responses after the local attempt is terminal", () => {
    const selected = scenario("accept");
    const accepted = respondToSlackProposal(selected, initialSlackDemoState(selected), "accept");

    expect(respondToSlackProposal(selected, accepted, "refuse")).toBe(accepted);
  });
});
