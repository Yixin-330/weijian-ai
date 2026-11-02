import { requestJson } from "../../shared/api/client";
import type { CreatedWorld, ExplorationPayload } from "../../shared/api/types";

export type TickJob = {
  job_id: string;
  status: "queued" | "in_progress" | "completed" | "failed" | "not_found";
  tick?: { id: string; decision_reason?: string } | null;
  error?: string | null;
};

type TickOptions = { signal?: AbortSignal; idempotencyKey?: string };

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  signal?.throwIfAborted();
  return new Promise((resolve, reject) => {
    const finish = () => { signal?.removeEventListener("abort", abort); resolve(); };
    const timer = setTimeout(finish, ms);
    const abort = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      reject(signal?.reason || new DOMException("请求已取消", "AbortError"));
    };
    signal?.addEventListener("abort", abort, { once: true });
  });
}

/** Poll only the existing task; timeout never submits another mutation. */
export async function waitForTick(
  initial: TickJob,
  options: { signal?: AbortSignal; maxAttempts?: number; intervalMs?: number } = {},
): Promise<TickJob> {
  const { signal, maxAttempts = 20, intervalMs = 300 } = options;
  let job = initial;
  for (let attempt = 0; job.status === "queued" || job.status === "in_progress"; attempt++) {
    if (attempt >= maxAttempts) throw new Error("探索仍在进行，请稍后刷新查看；已提交的操作不会重复执行。");
    await delay(intervalMs, signal);
    job = await requestJson<TickJob>(`/world/tick-jobs/${encodeURIComponent(job.job_id)}`, { signal }, "探索状态读取失败");
  }
  signal?.throwIfAborted();
  if (job.status !== "completed") throw new Error(job.error || "探索任务不可用，请稍后刷新查看。");
  if (!job.tick?.id) throw new Error("探索已结束，但没有返回可读取的结果。");
  return job;
}

export async function advanceWorld(userId: string, options: TickOptions = {}): Promise<TickJob> {
  const job = await requestJson<TickJob>(`/users/${userId}/next-action`, {
    method: "POST", signal: options.signal,
    headers: { "Idempotency-Key": options.idempotencyKey || crypto.randomUUID() },
  }, "探索触发失败");
  return waitForTick(job, options);
}

export const readWorld = (userId: string, signal?: AbortSignal) =>
  requestJson<CreatedWorld>(`/users/${userId}/world`, { signal }, "世界状态读取失败");

export const readExploration = (userId: string, signal?: AbortSignal) =>
  requestJson<ExplorationPayload>(`/users/${userId}/exploration`, { signal }, "探索状态读取失败");

export function saveExploration(userId: string, state: ExplorationPayload["state"], signal?: AbortSignal) {
  return requestJson<ExplorationPayload>(`/users/${userId}/exploration`, {
    method: "POST", signal, headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled: state.enabled, allow_cross_island: state.allow_cross_island,
      allow_demo_partners: state.allow_demo_partners, social_pace: state.social_pace,
      excluded_topics: state.excluded_topics }),
  }, "探索设置保存失败");
}
