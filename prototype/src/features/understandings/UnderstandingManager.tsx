import { type CreatedWorld, type CalibrationId } from "../../shared/api/types";
import { useState } from "react";
import { KeyboardTextarea } from "../../mobile";
import { calibrationLabels } from "../../shared/config/options";
import { useUnderstandings } from "./useUnderstandings";

export function UnderstandingManager({ world, onWorldChange, returnedQuestion }: {
  world: CreatedWorld; onWorldChange: (world: CreatedWorld) => void; returnedQuestion?: string;
}) {
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [replying, setReplying] = useState(false);
  const { busy, message, details, standalone, change, leaveThought, calibrate, loadDetails, setConsent } = useUnderstandings(world, onWorldChange);
  const active = world.memories.filter((m) => m.status === "candidate" || m.status === "confirmed");
  return <section className="understanding-manager" aria-label="管理生命体的理解">
    <h3>继续让它了解你</h3>
    {returnedQuestion ? <div><blockquote>{returnedQuestion}</blockquote><label><input type="checkbox" checked={replying} onChange={(event) => setReplying(event.target.checked)} />回应这个带回问题</label></div> : null}
    <KeyboardTextarea className="wj-textarea" value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={1000} placeholder="写下最近在思考的问题，或回应生命体带回的问题…" />
    <button type="button" disabled={busy || !draft.trim() || standalone} onClick={async () => { if (await leaveThought(draft, replying)) setDraft(""); }}>留下想法</button>
    <h3>我的理解 · {active.length} 条</h3>
    {active.length === 0 ? <p>目前没有有效理解，你可以从一个最近的问题开始。</p> : null}
    {active.map((memory) => <article className="memory-card" key={memory.id}>
      <span>{memory.status === "candidate" ? "待你校准" : "已经确认"} · 第 {memory.version || 1} 版</span>
      <strong>{memory.statement}</strong>
      <small>{Math.round(memory.confidence * 100)}% 置信度 · {memory.evidence_ids.length} 条来源</small>
      <div className="understanding-actions" role="group" aria-label="校准这条理解">
        {(Object.entries(calibrationLabels) as [CalibrationId, string][]).map(([id, label]) => <button type="button" key={id} disabled={busy || standalone} onClick={() => calibrate(memory, id)}>{label}</button>)}
      </div>
      <div className="understanding-actions">
        <button type="button" disabled={busy || standalone} onClick={() => loadDetails(memory)}>形成依据与修正记录</button>
        <button type="button" disabled={busy || standalone} onClick={() => { setEditing(memory.id); setEditText(memory.statement); }}>修改</button>
        <button type="button" disabled={busy || standalone} onClick={() => change(memory, "permission")}>{memory.allow_social_recommendation ? "停止用于社交" : "允许用于社交"}</button>
        <button type="button" disabled={busy || standalone} onClick={() => change(memory, "delete")}>删除理解</button>
      </div>
      {details[memory.id] ? <p className="understanding-detail">{details[memory.id]}</p> : null}
      {editing === memory.id ? <div><KeyboardTextarea className="wj-textarea" value={editText} onChange={(event) => setEditText(event.target.value)} maxLength={1000} />
        <button type="button" disabled={busy || !editText.trim()} onClick={async () => { if (await change(memory, "edit", editText)) setEditing(null); }}>保存修正</button>
        <button type="button" onClick={() => setEditing(null)}>取消</button></div> : null}
    </article>)}
    <button type="button" disabled={busy || standalone} onClick={() => setConsent(false, false)}>暂停使用我的理解</button>
    <button type="button" disabled={busy || standalone} onClick={() => setConsent(true, false)}>恢复私人探索</button>
    <button type="button" disabled={busy || standalone} onClick={() => setConsent(true, true)}>允许已授权理解参与社交</button>
    {message ? <p role="status">{message}</p> : null}
  </section>;
}
