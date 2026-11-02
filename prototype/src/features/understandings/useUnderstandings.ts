import { useEffect, useRef, useState } from "react";
import type { CalibrationId, CreatedWorld } from "../../shared/api/types";
import { requestJson } from "../../shared/api/client";
import { isStandaloneExperience } from "../../shared/experience/mode";
import { calibrateAndAdvance } from "./api";

type Understanding = CreatedWorld["memories"][number];
const sourceLabels: Record<string, string> = { authored_content: "本人创作摘要", favlist_naming: "收藏夹名称与描述", favorite_item: "收藏条目", followee_headline: "关注对象介绍", in_app_input: "你主动写下的想法", calibration: "你的理解校准", returned_question_reply: "你对带回问题的回应", in_app_browse: "应用内阅读" };
const revisionLabels: Record<string, string> = { like_me: "很像我", recent: "只是最近", opposes: "我在反对", wrong: "理解错了", edit: "修改理解", delete: "删除理解", permission: "修改社交授权" };

export function useUnderstandings(world: CreatedWorld, onWorldChange: (world: CreatedWorld) => void) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [details, setDetails] = useState<Record<string, string>>({});
  const scope = useRef<AbortController | null>(null);
  const inFlight = useRef(false);
  const standalone = isStandaloneExperience();
  const userId = world.user.id;
  useEffect(() => {
    const controller = new AbortController(); scope.current = controller;
    inFlight.current = false; setBusy(false); setMessage(""); setDetails({});
    return () => { controller.abort(); };
  }, [userId]);

  const run = async (task: (signal: AbortSignal) => Promise<string>): Promise<boolean> => {
    const controller = scope.current;
    if (!controller || controller.signal.aborted || inFlight.current) return false;
    if (standalone) { setMessage("完整理解管理需要连接后端，请在本地真实体验模式中使用。"); return false; }
    inFlight.current = true; setBusy(true); setMessage("");
    try {
      const note = await task(controller.signal);
      if (controller.signal.aborted) return false;
      setMessage(note); return true;
    } catch (error) {
      if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : "暂时无法保存");
      return false;
    } finally {
      if (!controller.signal.aborted) { inFlight.current = false; setBusy(false); }
    }
  };
  const request = <T,>(path: string, signal: AbortSignal, body?: unknown) => requestJson<T>(path, {
    signal, ...(body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  }, "暂时无法保存");
  const refresh = async (signal: AbortSignal) => {
    const next = await request<CreatedWorld>(`/users/${userId}/world`, signal);
    signal.throwIfAborted(); onWorldChange(next);
  };
  const change = (memory: Understanding, operation: "edit" | "delete" | "permission", statement?: string) => run(async (signal) => {
    await request(`/understandings/${memory.id}/changes`, signal, {
      user_id: userId, operation, expected_version: memory.version || 1,
      statement: operation === "edit" ? statement : undefined,
      allow_social_recommendation: operation === "permission" ? !memory.allow_social_recommendation : memory.allow_social_recommendation,
    });
    await refresh(signal);
    return operation === "delete" ? "已删除这条理解，之后的行动不再使用它。" : "已保存，下一次探索将使用更新后的理解。";
  });
  const leaveThought = (draft: string, replying: boolean) => run(async (signal) => {
    await request(`/users/${userId}/evidence`, signal, { ingestion_key: `input:${crypto.randomUUID()}`, source: replying ? "returned_question_reply" : "in_app_input", content_text: draft, source_ref: replying && world.latest_tick?.id ? `tick:${world.latest_tick.id}` : undefined, self_reference: true });
    const result = await request<{ items: unknown[] }>(`/users/${userId}/understandings/derive`, signal, {});
    await refresh(signal);
    return result.items.length ? "已经形成新的候选理解，可以查看依据并校准。" : "想法已经留下，目前证据还不足以形成新的理解。";
  });
  const calibrate = (memory: Understanding, decision: CalibrationId) => run(async (signal) => {
    const result = await calibrateAndAdvance(world, decision, !memory.allow_social_recommendation, memory.id, signal);
    signal.throwIfAborted(); onWorldChange(result.world); return result.decisionReason;
  });
  const loadDetails = (memory: Understanding) => run(async (signal) => {
    const [records, history] = await Promise.all([
      Promise.all(memory.evidence_ids.map((id) => request<{ source: string; content_text: string }>(`/users/${userId}/evidence/${id}`, signal))),
      request<{ items: Array<{ decision: string; occurred_at: string }> }>(`/understandings/${memory.id}/history?user_id=${userId}`, signal),
    ]);
    signal.throwIfAborted();
    setDetails((old) => ({ ...old, [memory.id]: records.map((e) => `${sourceLabels[e.source] || "授权材料"}：${e.content_text}`).join("\n") + `\n已记录 ${history.items.length} 次修正` + history.items.map((r) => `\n${new Date(r.occurred_at).toLocaleString()} · ${revisionLabels[r.decision] || "用户修正"}`).join("") }));
    return "";
  });
  const setConsent = (memory: boolean, social: boolean) => run(async (signal) => {
    await request(`/users/${userId}/memory-consent`, signal, { memory_inference: memory, social_recommendation: social });
    return !memory ? "已暂停理解用于探索与社交，下一次行动将立即遵守。" : social ? "已允许社交探索，仅使用你逐条授权且不敏感的理解。" : "已恢复用于私人探索；社交使用仍需单独授权。";
  });
  return { busy, message, details, standalone, change, leaveThought, calibrate, loadDetails, setConsent };
}
