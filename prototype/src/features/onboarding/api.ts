import { type OnboardingAnswers, type CreatedWorld } from "../../shared/api/types";
import { isStandaloneExperience } from "../../shared/experience/mode";
import { createStandaloneWorld } from "../../demo/world";
import { apiFetch } from "../../shared/api/client";

export async function createWorldFromOnboarding(answers: OnboardingAnswers, idempotencyKey: string, signal?: AbortSignal): Promise<CreatedWorld> {
  signal?.throwIfAborted();
  if (isStandaloneExperience()) {
    await new Promise((resolve) => window.setTimeout(resolve, 450));
    signal?.throwIfAborted();
    return createStandaloneWorld(answers);
  }

  const response = await apiFetch(`/onboarding`, {
    method: "POST",
    signal,
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify({
      current_question: answers.currentQuestion,
      long_term_topics: answers.topics,
      exploration_style: answers.exploration,
      social_pace: answers.socialPace,
      allow_memory_inference: answers.allowMemory,
      allow_social_recommendation: answers.allowSocial,
    }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(payload?.detail || `创建失败（${response.status}）`);
  }
  return response.json() as Promise<CreatedWorld>;
}
