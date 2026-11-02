import { requestJson } from "../../shared/api/client";

export type EncounterDecision = "observe_again" | "invite" | "distance" | "end" | "block";

export function saveEncounterDecision(userId: string, encounterId: string, decision: EncounterDecision) {
  return requestJson(`/encounters/${encounterId}/decisions`, {
    method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({ user_id: userId, decision }),
  }, "选择保存失败");
}
