import type { CreatedWorld, CalibrationId, CalibrationResult, IslandId } from "../shared/api/types";
import { calibrationDecisions, isIslandId, islandLabels } from "../shared/config/options";

export async function calibrateStandalone(world: CreatedWorld, calibration: CalibrationId, excludeSocial: boolean, candidate: CreatedWorld["memories"][number]): Promise<CalibrationResult> {
    await new Promise((resolve) => window.setTimeout(resolve, 450));
    const decision = calibrationDecisions[calibration];
    const currentIsland = isIslandId(world.lifeform.current_island_id)
      ? world.lifeform.current_island_id
      : "stability";
    const nextIsland: IslandId = calibration === "opposing"
      ? (currentIsland === "intimacy" ? "stability" : "intimacy")
      : calibration === "recent"
        ? (currentIsland === "ai_loneliness" ? "stability" : "ai_loneliness")
        : currentIsland;
    const action = calibration === "like-me" ? "靠近" : calibration === "opposing" ? "回应" : "观察";
    const effect = calibration === "wrong"
      ? "这条候选理解已被否定，不再影响探索方向"
      : calibration === "recent"
        ? "它被保留为近期状态，生命体转向观察另一种可能"
        : calibration === "opposing"
          ? "反对本身成为新的明确证据，生命体转向探索边界与差异"
          : "这条理解得到确认，生命体愿意沿当前问题继续靠近";
    const updatedWorld: CreatedWorld = {
      ...world,
      lifeform: {
        ...world.lifeform,
        current_island_id: nextIsland,
        status: `下一步动作：${action}`,
      },
      memories: world.memories.map((memory) => memory.id === candidate.id ? {
        ...memory,
        status: calibration === "wrong" ? "rejected" : "confirmed",
        calibration: decision,
        allow_social_recommendation: !excludeSocial,
      } : memory),
      latest_tick: {
        selected_island_id: nextIsland,
        decision_reason: `${effect}；下一步动作是「${action}」，前往「${islandLabels[nextIsland]}」。`,
      },
    };
    return { world: updatedWorld, decisionReason: updatedWorld.latest_tick!.decision_reason };
}
