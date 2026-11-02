import { type EncounterPayload } from "../../shared/api/types";
import { CrossCircledIcon, EyeOpenIcon, ArrowRightIcon } from "@radix-ui/react-icons";

export function DesktopEventDialog({ open, loading, error, encounter, actorLifeformId, actorName, companionName, islandName, allowDemoFallback, waitingMessage, onClose, onRelationship }: {
  open: boolean;
  loading: boolean;
  error: string;
  encounter: EncounterPayload | null;
  actorLifeformId?: string;
  actorName: string;
  companionName: string;
  islandName: string;
  allowDemoFallback: boolean;
  waitingMessage?: string;
  onClose: () => void;
  onRelationship: () => void;
}) {
  if (!open) return null;

  const turns = encounter?.turns || [];
  const hasLiveEncounter = Boolean(encounter);
  const showDemoFallback = !encounter && allowDemoFallback;

  return (
    <div className="desktop-dialog-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="desktop-event-dialog" role="dialog" aria-modal="true" aria-labelledby="desktop-event-title">
        <button type="button" className="desktop-dialog-close" onClick={onClose} aria-label="关闭"><CrossCircledIcon /></button>
        <p className="desktop-kicker">{hasLiveEncounter ? `${encounter!.companion_is_demo ? "演示伙伴" : "用户生命体相遇"} · 预设事件回放` : "共同事件"}</p>
        <h2 id="desktop-event-title">{loading ? "生命体正在相遇……" : encounter?.title || (showDemoFallback ? "如果更接近理想，值得暂时失去稳定吗？" : `${actorName}还没有带回相遇记录`)}</h2>
        <p className="desktop-event-dialog__intro">{encounter?.dilemma || (showDemoFallback ? "这不是一道测验。两个生命体会带着各自被允许使用的理解，交换一次真实选择。" : `${actorName}当前位于「${islandName}」。只有实际发生的相遇才会出现在这里。`)}</p>
        {loading ? <div className="desktop-event-dialog__notice" role="status">正在推进世界时间，并等待两个生命体带回结果。</div> : null}
        {error ? <div className="desktop-event-dialog__notice desktop-event-dialog__notice--error" role="alert">{error}</div> : null}
        {!loading && !encounter && waitingMessage ? <div className="desktop-event-dialog__notice" role="status">{waitingMessage}</div> : null}
        {encounter?.match_reason ? <div className="desktop-event-dialog__notice"><strong>为什么相遇</strong><p>{encounter.match_reason}</p></div> : null}
        {!loading && (turns.length > 0 || showDemoFallback) ? (
          <div className="desktop-event-dialog__turns">
            {turns.length ? turns.map((turn) => {
              const isActor = turn.actor_lifeform_id === actorLifeformId;
              return (
                <article key={turn.id}>
                  <span>{isActor ? actorName : companionName} · 第 {turn.turn_number} 步</span>
                  <p>“{turn.public_utterance}”</p>
                  <small>{turn.reason_summary}</small>
                </article>
              );
            }) : showDemoFallback ? (
              <>
                <article><span>露米先问</span><p>“失去的稳定，是否换来了真正的选择权？”</p><small>依据：你最近校准过的「重视自主决定」</small></article>
                <article><span>阿澈回应</span><p>“我更在意，承担风险后还有没有照顾重要之人的余地。”</p><small>它没有否定露米，而是补上了另一种代价</small></article>
              </>
            ) : null}
          </div>
        ) : null}
        {!loading && (encounter || showDemoFallback) ? <div className="desktop-event-dialog__result"><EyeOpenIcon /><div><span>{encounter ? "相遇已经完成" : "一次相遇正在形成"}</span><p>{encounter?.shared_memory || "它们答案不同，却都希望决定不会被他人代替。"}</p></div></div> : null}
        {encounter?.return_question ? <div className="desktop-event-dialog__return"><span>它带回的问题</span><strong>{encounter.return_question}</strong></div> : null}
        {encounter || showDemoFallback ? <button type="button" className="desktop-primary" disabled={loading} onClick={onRelationship}>进入关系幕布<ArrowRightIcon /></button> : <button type="button" className="desktop-secondary" onClick={onClose}>回到世界</button>}
      </section>
    </div>
  );
}
