import { useExploration } from "./useExploration";
import { type CreatedWorld } from "../../shared/api/types";
import { topicOptions } from "../../shared/config/options";

export function ExplorationPanel({ world, onWorldChange }: { world: CreatedWorld; onWorldChange: (world: CreatedWorld) => void }) {
  const { settings, busy, note, standalone, save, explore, refresh } = useExploration(world, onWorldChange);
  return <section className="understanding-manager" aria-label="相遇探索设置"><h3>它如何遇见同行者</h3>
    <p role="status">{busy ? "正在探索…" : settings ? ({ waiting: "正在探索，等待合适的同行者", paused: "相遇已暂停，仍可私人探索", cooldown: "刚完成相遇，稍后继续探索" })[settings.status] : standalone ? "当前是独立演示场景" : "正在读取探索状态…"}</p>
    {settings ? <>
      <label className="desktop-check"><input type="checkbox" checked={settings.state.enabled} disabled={busy} onChange={(e) => save({ enabled: e.target.checked })} />允许生命体参与相遇</label>
      <label className="desktop-check"><input type="checkbox" checked={settings.state.allow_cross_island} disabled={busy} onChange={(e) => save({ allow_cross_island: e.target.checked })} />允许为相关问题跨岛探索</label>
      <label className="desktop-check"><input type="checkbox" checked={settings.state.allow_demo_partners} disabled={busy} onChange={(e) => save({ allow_demo_partners: e.target.checked })} />也可以遇见明确标记的演示伙伴</label>
      <fieldset className="understanding-actions"><legend>相遇节奏</legend>{(["observe_first", "shared_experiences", "open_to_connection"] as const).map((pace) => <button type="button" key={pace} aria-pressed={settings.state.social_pace === pace} disabled={busy} onClick={() => save({ social_pace: pace })}>{{ observe_first: "先独自观察", shared_experiences: "先有共同经历", open_to_connection: "愿意认识同行者" }[pace]}</button>)}</fieldset>
      <fieldset className="understanding-actions"><legend>暂时不想在这些议题中相遇</legend>{topicOptions.map((topic) => <label key={topic.id}><input type="checkbox" checked={settings.state.excluded_topics.includes(topic.id)} disabled={busy} onChange={(e) => save({ excluded_topics: e.target.checked ? [...settings.state.excluded_topics, topic.id] : settings.state.excluded_topics.filter((t) => t !== topic.id) })} />{topic.label}</label>)}</fieldset>
      {!settings.authorized_topics.length ? <p>还没有可用于社交的议题。可在下方理解管理中开启总体授权，并逐条决定是否使用。</p> : null}
      {settings.last_match_reason ? <p>{settings.last_encounter_is_demo ? "演示相遇 · " : "最近的相遇缘由 · "}{settings.last_match_reason}</p> : null}
    </> : null}
    <button type="button" disabled={busy || standalone || !settings} onClick={explore}>让生命体探索一次</button>
    <button type="button" disabled={busy || standalone} onClick={refresh}>刷新相遇状态</button>
    {note ? <p role="status">{note}</p> : null}
  </section>;
}
