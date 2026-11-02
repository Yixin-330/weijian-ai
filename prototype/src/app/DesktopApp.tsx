import { type DesktopView, type DesktopStage, type IslandId, type CreatedWorld, type EncounterPayload, type RelationshipPayload, type LifeformPayload } from "../shared/api/types";
import { GlobeIcon, ReaderIcon, HeartIcon, PersonIcon, CrossCircledIcon } from "@radix-ui/react-icons";
import { useState, useEffect } from "react";
import { useIslandCatalog } from "../features/world/useIslandCatalog";
import { isStandaloneExperience } from "../shared/experience/mode";

import { bootstrapDemoWorld } from "../demo/api";
import { isIslandId, islandLabels } from "../shared/config/options";
import { apiFetch } from "../shared/api/client";
import { useOnboarding } from "../features/onboarding/useOnboarding";
import { advanceToEncounter } from "../features/encounters/api";
import { createPortal } from "react-dom";
import { OnboardingScreen, BirthScreen } from "../features/onboarding/OnboardingScreen";
import { worldArtworkSrc } from "../shared/assets/artwork";
import { DesktopWorld } from "../features/world/DesktopWorld";
import { DesktopLifeform } from "../features/understandings/DesktopLifeform";
import { DesktopRelationship } from "../features/encounters/DesktopRelationship";
import { DesktopInvitation } from "../features/connections/DesktopInvitation";
import { DesktopEventDialog } from "../features/encounters/DesktopEventDialog";

export function DesktopNav({ view, onNavigate, onProfile }: {
  view: DesktopView;
  onNavigate: (view: DesktopView) => void;
  onProfile: () => void;
}) {
  return (
    <nav className="desktop-nav" aria-label="主要导航">
      <div className="desktop-brand" aria-label="未见">
        <strong>未见</strong>
        <span>在更大的世界里<br />遇见更真的连接</span>
      </div>
      <div className="desktop-nav__items">
        <button type="button" className={view === "world" ? "is-active" : ""} onClick={() => onNavigate("world")}><GlobeIcon /><span>世界</span></button>
        <button type="button" className={view === "lifeform" ? "is-active" : ""} onClick={() => onNavigate("lifeform")}><ReaderIcon /><span>生命体</span></button>
        <button type="button" className={view === "relationship" || view === "invitation" ? "is-active" : ""} onClick={() => onNavigate("relationship")}><HeartIcon /><span>关系</span></button>
        <button type="button" onClick={onProfile}><PersonIcon /><span>我的</span></button>
      </div>
    </nav>
  );
}

export function DesktopProfileDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;
  return (
    <div className="desktop-dialog-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="desktop-profile-dialog" role="dialog" aria-modal="true" aria-labelledby="desktop-profile-title">
        <button type="button" className="desktop-dialog-close" onClick={onClose} aria-label="关闭"><CrossCircledIcon /></button>
        <p className="desktop-kicker">你的边界</p><h2 id="desktop-profile-title">理解、探索与真人连接始终分开授权</h2>
        <div><span>用于生命体成长</span><strong>已开启</strong></div><div><span>用于社交探索</span><strong>逐条决定</strong></div><div><span>真人连接</span><strong>必须双向同意</strong></div>
      </section>
    </div>
  );
}

export function DesktopPrototype() {
  const requestedFlow = new URLSearchParams(window.location.search).get("flow");
  // The product entry starts with the user's question and lifeform creation.
  // Keep an explicit world-only route for quick visual checks and judging setup.
  const liveEntry = window.location.pathname.startsWith("/demo/start")
    || requestedFlow !== "world";
  const [view, setView] = useState<DesktopStage>(liveEntry ? "onboarding" : "world");
  const [island, setIsland] = useState<IslandId>("stability");
  const [eventOpen, setEventOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [relationshipAct, setRelationshipAct] = useState(0);
  const [accepted, setAccepted] = useState(false);
  const { answers: onboarding, setAnswers: setOnboarding, error: onboardingError, submitting: submittingOnboarding, submit: createLifeform } = useOnboarding();
  const [createdWorld, setCreatedWorld] = useState<CreatedWorld | null>(null);
  const [encounter, setEncounter] = useState<EncounterPayload | null>(null);
  const [relationship, setRelationship] = useState<RelationshipPayload | null>(null);
  const [companion, setCompanion] = useState<LifeformPayload | null>(null);
  const [eventLoading, setEventLoading] = useState(false);
  const [eventError, setEventError] = useState("");
  const standalone = isStandaloneExperience();
  const { islands, catalogLive } = useIslandCatalog(standalone);

  useEffect(() => {
    const previousTitle = document.title;
    document.body.classList.add("wj-desktop-mode");
    document.title = "未见 · 问题群岛";
    return () => {
      document.body.classList.remove("wj-desktop-mode");
      document.title = previousTitle;
    };
  }, []);



  useEffect(() => {
    let active = true;
    if (standalone || liveEntry) return () => { active = false; };
    bootstrapDemoWorld()
      .then((world) => {
        if (!active || liveEntry) return;
        setCreatedWorld(world);
        setRelationship(world.relationships?.[0] || null);
        if (isIslandId(world.lifeform.current_island_id)) setIsland(world.lifeform.current_island_id);
        const companionId = world.relationships?.[0]?.lifeform_ids.find((id) => id !== world.lifeform.id);
        if (companionId) {
          apiFetch(`/lifeforms/${companionId}`)
            .then((response) => response.ok ? response.json() as Promise<LifeformPayload> : null)
            .then((lifeform) => { if (active && lifeform) setCompanion(lifeform); })
            .catch(() => undefined);
        }
      })
      .catch(() => undefined);
    return () => { active = false; };
  }, [liveEntry, standalone]);

  const navigate = (next: DesktopView) => {
    setEventOpen(false);
    setView(next);
  };

  const submitOnboarding = async () => {
    const world = await createLifeform();
    if (!world) return;
    setCreatedWorld(world); setEncounter(null); setRelationship(null); setCompanion(null);
    if (isIslandId(world.lifeform.current_island_id)) setIsland(world.lifeform.current_island_id);
    setView("born");
  };
  const updateLiveWorld = (world: CreatedWorld) => {
    setCreatedWorld(world);
    if (world.relationships?.[0]) setRelationship(world.relationships[0]);
    if (isIslandId(world.lifeform.current_island_id)) setIsland(world.lifeform.current_island_id);
  };

  const openEvent = async () => {
    setEventOpen(true);
    setEventError("");
    if (standalone || encounter) return;
    setEventLoading(true);
    try {
      const sourceWorld = createdWorld || await bootstrapDemoWorld();
      const result = await advanceToEncounter(sourceWorld);
      updateLiveWorld(result.world);
      setEncounter(result.encounter);
      setRelationship(result.relationship);
      setCompanion(result.companion);
      setRelationshipAct(0);
    } catch (error) {
      setEventError(error instanceof Error ? error.message : "暂时无法读取这次相遇。");
    } finally {
      setEventLoading(false);
    }
  };

  const allowDemoFallback = !createdWorld || createdWorld.user.id === "user-lumi";
  const rawCompanionName = companion?.name || (allowDemoFallback ? "阿澈" : "同行生命体");
  const companionName = rawCompanionName === createdWorld?.lifeform.name
    ? `${rawCompanionName} · 同行者`
    : rawCompanionName;
  const currentIslandName = islands[island]?.name || islandLabels[island];

  return createPortal(
    <main className={`wj-desktop-app wj-desktop-app--${view}`}>
      {standalone ? <div className="desktop-experience-badge">比赛体验场景 · 数据仅保留在当前会话</div> : null}
      {view === "onboarding" ? (
        <section className="desktop-onboarding-flow">
          <img src="/assets/wj/wj-desktop-world-immersive-v1.png" alt="云海中的问题群岛" draggable={false} />
          <div className="desktop-onboarding-flow__veil" aria-hidden="true" />
          <div className="desktop-onboarding-flow__panel">
            <OnboardingScreen answers={onboarding} onChange={setOnboarding} submitting={submittingOnboarding} error={onboardingError} onSubmit={submitOnboarding} />
          </div>
        </section>
      ) : null}
      {view === "born" && createdWorld ? (
        <section className="desktop-onboarding-flow desktop-onboarding-flow--born">
          <img src={worldArtworkSrc(createdWorld.lifeform.appearance)} alt={`${createdWorld.lifeform.name}诞生于问题群岛`} draggable={false} />
          <div className="desktop-onboarding-flow__veil" aria-hidden="true" />
          <div className="desktop-onboarding-flow__panel"><BirthScreen world={createdWorld} onEnter={() => navigate("world")} /></div>
        </section>
      ) : null}
      {view !== "onboarding" && view !== "born" ? <DesktopNav view={view} onNavigate={navigate} onProfile={() => setProfileOpen(true)} /> : null}
      {view === "world" ? <DesktopWorld island={island} islands={islands} catalogLive={catalogLive} world={createdWorld} encounter={encounter} relationship={relationship} companion={companion} companionName={companionName} onIslandChange={setIsland} onOpenEvent={openEvent} /> : null}
      {view === "lifeform" ? <DesktopLifeform world={createdWorld} relationship={relationship} companionName={companionName} returnedQuestion={encounter?.return_question} onWorldChange={updateLiveWorld} onRelationship={() => navigate("relationship")} /> : null}
      {view === "relationship" ? <DesktopRelationship act={relationshipAct} encounter={encounter} relationship={relationship} userId={createdWorld?.user.id} actorLifeformId={createdWorld?.lifeform.id} actorName={createdWorld?.lifeform.name || "露米"} actorAppearance={createdWorld?.lifeform.appearance} companionName={companionName} currentIslandId={createdWorld?.lifeform.current_island_id || island} allowDemoFallback={allowDemoFallback} onActChange={setRelationshipAct} onInvitation={() => navigate("invitation")} onBackToWorld={() => navigate("world")} /> : null}
      {view === "invitation" ? <DesktopInvitation accepted={accepted} standalone={standalone} actorAppearance={createdWorld?.lifeform.appearance} companionName={companionName} sharedMemory={encounter?.shared_memory} returnQuestion={encounter?.return_question} onAccept={() => setAccepted(true)} onBack={() => navigate("relationship")} /> : null}
      <DesktopEventDialog open={eventOpen} loading={eventLoading} error={eventError} encounter={encounter} actorLifeformId={createdWorld?.lifeform.id} actorName={createdWorld?.lifeform.name || "露米"} companionName={companionName} islandName={currentIslandName} waitingMessage={createdWorld?.latest_tick?.match_reason} allowDemoFallback={allowDemoFallback} onClose={() => setEventOpen(false)} onRelationship={() => { setRelationshipAct(0); navigate("relationship"); }} />
      <DesktopProfileDialog open={profileOpen} onClose={() => setProfileOpen(false)} />
    </main>,
    document.body,
  );
}
