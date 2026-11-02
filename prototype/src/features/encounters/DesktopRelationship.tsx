import { type EncounterPayload, type RelationshipPayload, type IslandId } from "../../shared/api/types";
import { worldArtworkSrc } from "../../shared/assets/artwork";
import { islandLabels, relationshipStatusLabels } from "../../shared/config/options";
import { ArrowRightIcon, EyeOpenIcon } from "@radix-ui/react-icons";
import { relationshipActs } from "../../demo/content";
import { isStandaloneExperience } from "../../shared/experience/mode";
import { EncounterDecisions } from "../connections/EncounterDecisions";

export function DesktopRelationship({ act, encounter, relationship, actorLifeformId, actorName, actorAppearance, companionName, currentIslandId, allowDemoFallback, userId, onActChange, onInvitation, onBackToWorld }: {
  act: number;
  encounter: EncounterPayload | null;
  relationship: RelationshipPayload | null;
  actorLifeformId?: string;
  userId?: string;
  actorName: string;
  actorAppearance?: string;
  companionName: string;
  currentIslandId: string;
  allowDemoFallback: boolean;
  onActChange: (act: number) => void;
  onInvitation: () => void;
  onBackToWorld: () => void;
}) {
  if (!encounter && !allowDemoFallback) {
    const relationshipIsland = relationship?.island_id || currentIslandId;
    return (
      <section className="desktop-relationship" aria-labelledby="desktop-relationship-title">
        <img className="desktop-world__art" src={worldArtworkSrc(actorAppearance)} alt={`${actorName}尚未形成共同经历`} draggable={false} />
        <div className="desktop-relationship__veil" aria-hidden="true" />
        <header className="desktop-relationship__header"><p className="desktop-kicker">关系幕布 · {islandLabels[relationshipIsland] || "等待相遇"}</p><h1 id="desktop-relationship-title">{relationship?.headline || `${actorName}还没有形成关系记录`}</h1><span>这里只展示真实发生并由后端保存的共同经历</span></header>
        <article className="desktop-act-card">
          <div className="desktop-act-card__copy"><span>{relationship ? relationshipStatusLabels[relationship.status] : "尚未相遇"}</span><h2>{relationship ? `与${companionName}的相处记录` : "先让生命体去探索一次"}</h2><p>{relationship?.shared_experiences.at(-1) || "当两个生命体完成一次共同事件后，双方行动、分歧和带回问题会出现在这里。"}</p></div>
          <button type="button" className="desktop-primary" onClick={onBackToWorld}>回到世界<ArrowRightIcon /></button>
        </article>
      </section>
    );
  }

  const actorTurn = encounter?.turns.find((turn) => turn.actor_lifeform_id === actorLifeformId);
  const companionTurn = encounter?.turns.find((turn) => turn.actor_lifeform_id !== actorLifeformId);
  const liveAct = encounter ? {
    label: "本次相遇",
    title: encounter.title,
    copy: encounter.dilemma,
    lumi: actorTurn?.public_utterance || encounter.outcome_summary,
    ache: companionTurn?.public_utterance || "我愿意说明自己在意的代价。",
    insight: encounter.shared_memory,
  } : null;
  const acts = liveAct ? [liveAct] : relationshipActs;
  const current = acts[Math.min(act, acts.length - 1)];

  return (
    <section className="desktop-relationship" aria-labelledby="desktop-relationship-title">
      <img className="desktop-world__art" src={worldArtworkSrc(actorAppearance)} alt={`${actorName}与${companionName}的共同经历`} draggable={false} />
      <div className="desktop-relationship__veil" aria-hidden="true" />
      <header className="desktop-relationship__header"><p className="desktop-kicker">关系幕布 · {islandLabels[(relationship?.island_id || encounter?.island_id || "stability") as IslandId] || "稳定还是挑战"}</p><h1 id="desktop-relationship-title">{relationship?.headline || "它们从不同答案里，看见了彼此"}</h1><span>{relationship ? `${relationshipStatusLabels[relationship.status]} · ` : ""}这里呈现相处事实，不判断彼此情感</span></header>
      <div className="desktop-acts" role="tablist" aria-label="关系经历幕次">
        {acts.map((item, index) => <button type="button" role="tab" aria-selected={act === index} className={act === index ? "is-active" : ""} key={item.label} onClick={() => onActChange(index)}><span>{item.label}</span><small>{item.title}</small></button>)}
      </div>
      <article className="desktop-act-card" aria-live="polite">
        <div className="desktop-act-card__copy"><span>{current.label}</span><h2>{current.title}</h2><p>{current.copy}</p></div>
        <div className="desktop-act-dialogue"><blockquote><strong>{actorName}</strong>{current.lumi}</blockquote><blockquote><strong>{companionName}</strong>{current.ache}</blockquote></div>
        <div className="desktop-act-insight"><EyeOpenIcon /><div><span>这一幕留下了什么</span><p>{current.insight}</p></div></div>
        {encounter?.match_reason ? <p>{encounter.companion_is_demo ? "演示伙伴 · " : "相遇缘由 · "}{encounter.match_reason}</p> : null}
        {encounter && userId && !isStandaloneExperience() ? <EncounterDecisions userId={userId} encounter={encounter} /> : null}
        {act < acts.length - 1 ? <button type="button" className="desktop-primary" onClick={() => onActChange(act + 1)}>拉开下一幕<ArrowRightIcon /></button> : <button type="button" className="desktop-primary" onClick={onInvitation}>查看真人邀请<ArrowRightIcon /></button>}
      </article>
    </section>
  );
}
