import { type CalibrationId, type TopicId, type ExplorationId, type SocialPaceId, type IslandId, type RelationshipStatus } from "../api/types";

export const calibrationLabels: Record<CalibrationId, string> = {
  "like-me": "很像我",
  recent: "只是最近",
  opposing: "我在反对",
  wrong: "理解错了",
};

export const topicOptions: Array<{ id: TopicId; label: string }> = [
  { id: "choice_uncertainty", label: "选择、稳定与冒险" },
  { id: "intimacy_and_autonomy", label: "亲密关系与独立" },
  { id: "ai_and_loneliness", label: "AI、陪伴与真实关系" },
];

export const explorationOptions: Array<{ id: ExplorationId; label: string; note: string }> = [
  { id: "observe", label: "先安静观察", note: "留意差异与不确定性" },
  { id: "inquire", label: "先温和追问", note: "用问题靠近不同答案" },
  { id: "act", label: "先尝试行动", note: "在共同经历里继续理解" },
];

export const socialPaceOptions: Array<{ id: SocialPaceId; label: string }> = [
  { id: "observe_first", label: "先观察，不主动接近" },
  { id: "shared_experiences", label: "共同经历几次后再靠近" },
  { id: "open_to_connection", label: "合适时可以建议连接" },
];

export const islandLabels: Record<string, string> = {
  stability: "稳定还是冒险",
  intimacy: "亲密与自由",
  ai_loneliness: "AI 会让人更孤独吗",
};

export const calibrationDecisions: Record<CalibrationId, "like_me" | "recent" | "opposes" | "wrong"> = {
  "like-me": "like_me",
  recent: "recent",
  opposing: "opposes",
  wrong: "wrong",
};

export const topicToIsland: Record<TopicId, IslandId> = {
  choice_uncertainty: "stability",
  intimacy_and_autonomy: "intimacy",
  ai_and_loneliness: "ai_loneliness",
};

export const islandIds = ["stability", "intimacy", "ai_loneliness"] as const;

export const isIslandId = (value: string): value is IslandId => islandIds.some((id) => id === value);

export const relationshipStatusLabels: Record<RelationshipStatus, string> = {
  active: "可以继续观察",
  ended: "探索已经结束",
  blocked: "不再相遇",
};
