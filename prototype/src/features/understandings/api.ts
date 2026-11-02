import { calibrateStandalone } from "../../demo/calibration";
import { advanceWorld } from "../exploration/api";
import { type CreatedWorld, type CalibrationId, type CalibrationResult } from "../../shared/api/types";
import { isStandaloneExperience } from "../../shared/experience/mode";
import { calibrationDecisions } from "../../shared/config/options";
import { apiFetch, requestJson } from "../../shared/api/client";

export async function calibrateAndAdvance(
  world: CreatedWorld,
  calibration: CalibrationId,
  excludeSocial: boolean,
  understandingId?: string,
  signal?: AbortSignal,
): Promise<CalibrationResult> {
  signal?.throwIfAborted();
  const candidate = (understandingId ? world.memories.find((memory) => memory.id === understandingId) : undefined)
    || world.memories.find((memory) => memory.status === "candidate")
    || world.memories.find((memory) => memory.status === "confirmed");
  if (!candidate) throw new Error("当前没有可校准的候选理解。");

  if (isStandaloneExperience()) return calibrateStandalone(world, calibration, excludeSocial, candidate);

  await requestJson(`/understandings/${candidate.id}/calibrations`,
    {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: world.user.id,
        decision: calibrationDecisions[calibration],
        allow_social_recommendation: !excludeSocial,
      }),
    }, "校准保存失败",
  );

  let job;
  try { job = await advanceWorld(world.user.id, { signal }); }
  catch (error) {
    signal?.throwIfAborted();
    throw new Error(`校准已保存，但下一步探索暂未完成：${error instanceof Error ? error.message : "请稍后刷新查看"}`);
  }

  const worldResponse = await apiFetch(`/users/${world.user.id}/world`, { signal });
  if (!worldResponse.ok) throw new Error("校准已保存，但暂时无法刷新生命体状态。");
  return {
    world: await worldResponse.json() as CreatedWorld,
    decisionReason: job.tick?.decision_reason || "校准已生效，生命体已经调整了下一步行动。",
  };
}

export function saveReturnedQuestion(world: CreatedWorld, text: string) {
  return requestJson(`/users/${world.user.id}/evidence`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ingestion_key: `reply:${crypto.randomUUID()}`, source: "returned_question_reply",
      content_text: text, source_ref: world.latest_tick?.id ? `tick:${world.latest_tick.id}` : "island:stability",
      topic_code: "choice_uncertainty", self_reference: true }),
  }, "回应保存失败");
}
