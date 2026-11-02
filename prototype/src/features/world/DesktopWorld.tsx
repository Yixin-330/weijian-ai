import { type IslandId, type DesktopIsland, type CreatedWorld, type EncounterPayload, type RelationshipPayload, type LifeformPayload } from "../../shared/api/types";
import { useState, useEffect } from "react";
import { appearanceThemeKey, worldArtworkSrc } from "../../shared/assets/artwork";
import { ChevronRightIcon, ArrowRightIcon } from "@radix-ui/react-icons";

export function DesktopWorld({ island, islands, catalogLive, world, encounter, relationship, companion, companionName, onIslandChange, onOpenEvent }: {
  island: IslandId;
  islands: Record<IslandId, DesktopIsland>;
  catalogLive: boolean;
  world: CreatedWorld | null;
  encounter: EncounterPayload | null;
  relationship: RelationshipPayload | null;
  companion: LifeformPayload | null;
  companionName: string;
  onIslandChange: (island: IslandId) => void;
  onOpenEvent: () => void;
}) {
  const selected = islands[island];
  const [viewpointIndex, setViewpointIndex] = useState(0);
  const viewpoint = selected.viewpoints[viewpointIndex % Math.max(selected.viewpoints.length, 1)];
  const actorName = world?.lifeform.name || "露米";
  const currentIslandId = world?.lifeform.current_island_id;
  const isCurrentIsland = !currentIslandId || island === currentIslandId;
  const hasEncounterHere = encounter?.island_id === island;
  const hasRelationshipHere = relationship?.island_id === island;
  const hasCompanionHere = hasEncounterHere || hasRelationshipHere;
  const statusTitle = hasCompanionHere
    ? `${actorName}与${companionName}留下了共同经历`
    : isCurrentIsland
      ? `${actorName}正在探索「${selected.name}」`
      : `你可以建议${actorName}关注「${selected.name}」`;
  const statusCopy = isCurrentIsland
    ? world?.lifeform.status || `${actorName}会从你的问题出发，形成自己的下一步。`
    : `${actorName}保留有限自主性，会结合你的校准决定是否前往。`;

  useEffect(() => setViewpointIndex(0), [island]);

  return (
    <section className={`desktop-world desktop-world--${island} desktop-world--appearance-${appearanceThemeKey(world?.lifeform.appearance)}`} aria-labelledby="desktop-world-title">
      <img className="desktop-world__art" src={worldArtworkSrc(world?.lifeform.appearance)} alt={`漂浮在云海上的问题群岛，${actorName}正在探索${selected.name}`} draggable={false} />
      <div className="desktop-world__shade" aria-hidden="true" />

      {(Object.entries(islands) as [IslandId, DesktopIsland][])
        .filter(([id]) => id !== "stability" || island !== "stability")
        .map(([id, item]) => (
        <button
          type="button"
          key={id}
          className={`desktop-island ${item.position} ${island === id ? "is-selected" : ""}`}
          onClick={() => onIslandChange(id)}
          aria-pressed={island === id}
        >
          <span>{item.name}</span>
          <small>{id === currentIslandId ? "正在发生" : item.question.split("，")[0]}</small>
          <ChevronRightIcon />
        </button>
      ))}

      <div className="desktop-creature-label desktop-creature-label--lumi"><span>{actorName}</span><small>{world?.lifeform.appearance || "雾蓝"} · {world?.lifeform.exploration_tendency || "安静观察"}<br />从你的问题出发继续生长</small></div>
      {hasCompanionHere ? <div className="desktop-creature-label desktop-creature-label--ache"><span>{companionName}</span><small>{companion?.appearance || "未知形态"} · {companion?.exploration_tendency || "独立探索"}<br />在共同经历中保留自己的答案</small></div> : null}

      <article className="desktop-world__story" aria-live="polite">
        <p className="desktop-kicker">{isCurrentIsland ? "当前岛屿" : selected.eyebrow}</p>
        <h1 id="desktop-world-title">{selected.name}</h1>
        <p className="desktop-world__question">{selected.question}</p>
        <a className="desktop-world__source" href={selected.questionUrl} target="_blank" rel="noreferrer">知乎真实问题 · 查看原题</a>
        <button type="button" className="desktop-primary" onClick={onOpenEvent}>
          {isCurrentIsland ? "看看这里发生了什么" : `建议${actorName}去看看`}<ArrowRightIcon />
        </button>
      </article>

      <aside className="desktop-world__status">
        <span>{hasCompanionHere ? "最近相遇" : world?.latest_tick?.matching_status === "waiting" ? "等待同行" : isCurrentIsland ? "当前探索" : "新的方向"}</span>
        <strong>{statusTitle}</strong>
        <p>{statusCopy}</p>
        {world?.latest_tick?.match_reason ? <small>{world.latest_tick.match_reason}</small> : null}
        {viewpoint ? (
          <div className="desktop-world__echo">
            <span>岛上回声 · {viewpointIndex + 1}/{selected.viewpointCount}</span>
            <blockquote>{viewpoint.summary}</blockquote>
            <div>
              <a href={viewpoint.sourceUrl} target="_blank" rel="noreferrer">查看原回答</a>
              {selected.viewpoints.length > 1 ? (
                <button type="button" onClick={() => setViewpointIndex((index) => (index + 1) % selected.viewpoints.length)}>换一条</button>
              ) : null}
            </div>
          </div>
        ) : (
          <small className="desktop-world__catalog-state">{catalogLive ? "暂无可展示材料" : "正在连接岛屿资料…"}</small>
        )}
      </aside>
    </section>
  );
}
