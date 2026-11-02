import { advanceWorld } from "../exploration/api";
import { type EncounterPayload, type CreatedWorld, type LiveEncounterResult, type RelationshipPayload, type LifeformPayload } from "../../shared/api/types";
import { readApiError, apiFetch } from "../../shared/api/client";

export async function readTickEncounter(tickId: string): Promise<EncounterPayload | null> {
  const response = await apiFetch(`/world/ticks/${tickId}/encounter`);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(await readApiError(response, "相遇结果读取失败"));
  return response.json() as Promise<EncounterPayload>;
}

export async function advanceToEncounter(world: CreatedWorld): Promise<LiveEncounterResult> {
  let encounter = world.latest_tick?.id ? await readTickEncounter(world.latest_tick.id) : null;
  if (!encounter) {
    const status = await apiFetch(`/users/${world.user.id}/exploration`);
    if (!status.ok) throw new Error(await readApiError(status, "探索状态读取失败"));
    const own = await status.json() as { last_encounter_id: string | null };
    if (own.last_encounter_id) {
      const response = await apiFetch(`/encounters/${own.last_encounter_id}`);
      if (!response.ok) throw new Error(await readApiError(response, "相遇读取失败"));
      encounter = await response.json() as EncounterPayload;
    }
  }

  if (!encounter) {
    const job = await advanceWorld(world.user.id);
    encounter = await readTickEncounter(job.tick!.id);
  }

  if (!encounter) {
    const response = await apiFetch(`/users/${world.user.id}/world`);
    if (!response.ok) throw new Error(await readApiError(response, "探索状态读取失败"));
    return { world: await response.json() as CreatedWorld, encounter: null, relationship: null, companion: null };
  }

  const companionId = encounter.lifeform_ids.find((id) => id !== world.lifeform.id);
  if (!companionId) throw new Error("相遇结果缺少同行生命体。");
  const [relationshipResponse, worldResponse, companionResponse] = await Promise.all([
    apiFetch(`/relationships/${encounter.relationship_id}`),
    apiFetch(`/users/${world.user.id}/world`),
    apiFetch(`/lifeforms/${companionId}`),
  ]);
  if (!relationshipResponse.ok) throw new Error(await readApiError(relationshipResponse, "关系变化读取失败"));
  if (!worldResponse.ok) throw new Error(await readApiError(worldResponse, "生命体状态刷新失败"));
  if (!companionResponse.ok) throw new Error(await readApiError(companionResponse, "同行生命体读取失败"));
  return {
    encounter,
    relationship: await relationshipResponse.json() as RelationshipPayload,
    world: await worldResponse.json() as CreatedWorld,
    companion: await companionResponse.json() as LifeformPayload,
  };
}
