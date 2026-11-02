import { type TopicId, type OnboardingAnswers, type CreatedWorld, type ExplorationId } from "../shared/api/types";
import { topicToIsland } from "../shared/config/options";

export const standaloneUnderstandings: Record<TopicId, { statement: string; focus: string }> = {
  choice_uncertainty: {
    statement: "你最近可能正在反复衡量：稳定是否值得用一部分可能性去交换。",
    focus: "稳定、选择与可以承担的代价",
  },
  intimacy_and_autonomy: {
    statement: "你可能在亲密关系中重视靠近，也想保留独立判断与边界。",
    focus: "亲密关系中的靠近与自主",
  },
  ai_and_loneliness: {
    statement: "你正在关注：被准确回应与被真实的人努力理解，是否是同一件事。",
    focus: "AI 陪伴与真实关系的差异",
  },
};

export function createStandaloneWorld(answers: OnboardingAnswers): CreatedWorld {
  const primaryTopic = answers.topics[0] || "choice_uncertainty";
  const understanding = standaloneUnderstandings[primaryTopic];
  const explorationLabels: Record<ExplorationId, string> = {
    observe: "安静观察",
    inquire: "温和追问",
    act: "在共同经历中行动",
  };
  const worldId = crypto.randomUUID();
  return {
    user: { id: `experience-user-${worldId}` },
    lifeform: {
      id: `experience-lifeform-${worldId}`,
      name: "露米",
      appearance: "雾蓝半透明翼状生命体",
      exploration_tendency: explorationLabels[answers.exploration || "observe"],
      current_island_id: topicToIsland[primaryTopic],
      current_focus: understanding.focus,
      status: "正在形成初始理解",
    },
    memories: [{
      id: `experience-understanding-${worldId}`,
      statement: understanding.statement,
      status: "candidate",
      confidence: 0.72,
      evidence_ids: [`主动输入：${answers.currentQuestion.trim()}`],
      allow_social_recommendation: answers.allowSocial,
      calibration: null,
    }],
    latest_tick: null,
  };
}
