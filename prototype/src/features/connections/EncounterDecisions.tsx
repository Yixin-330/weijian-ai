import { type EncounterPayload } from "../../shared/api/types";
import { useState } from "react";
import { saveEncounterDecision } from "./api";

export function EncounterDecisions({ userId, encounter }: { userId: string; encounter: EncounterPayload }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  return <section className="understanding-manager" aria-label="本次相遇的私密决定"><h3>你想让这段探索如何继续？</h3>
    <p>这是你的私密选择。真人聊天仍需双方分别同意。</p>
    <div className="understanding-actions">{(["observe_again", "invite", "distance", "end", "block"] as const).map((decision) => <button type="button" key={decision} disabled={busy} onClick={async () => {
      setBusy(true); setNote("");
      try {
        await saveEncounterDecision(userId, encounter.id, decision);
        setNote(({ observe_again: "已记下继续观察的意愿，后续仍遵守双方意愿与相遇间隔。", invite: "已记录邀请意愿，尚未开启真人聊天。", distance: "已暂停这对生命体的相遇48小时。", end: "已结束这段探索，不会再自动配对。", block: "已屏蔽，不会再安排相遇。" })[decision]);
      } catch (error) { setNote(error instanceof Error ? error.message : "选择保存失败"); } finally { setBusy(false); }
    }}>{{ observe_again: "想再看看", invite: "邀请认识", distance: "保持距离", end: "结束探索", block: "屏蔽" }[decision]}</button>)}</div>
    {note ? <p role="status">{note}</p> : null}
  </section>;
}
