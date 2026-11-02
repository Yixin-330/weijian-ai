import { type CreatedWorld, type RelationshipPayload, type CalibrationId } from "../../shared/api/types";
import { useState, useEffect } from "react";
import { calibrateAndAdvance } from "./api";
import { lifeformPortraitSrc } from "../../shared/assets/artwork";
import { Pencil2Icon, ReaderIcon, ChevronRightIcon, CheckCircledIcon, CrossCircledIcon, EyeOpenIcon, ArrowRightIcon } from "@radix-ui/react-icons";
import { calibrationLabels, relationshipStatusLabels } from "../../shared/config/options";
import { ExplorationPanel } from "../exploration/ExplorationPanel";
import { UnderstandingManager } from "./UnderstandingManager";

export function DesktopLifeform({ onRelationship, world, relationship, companionName, onWorldChange, returnedQuestion }: {
  onRelationship: () => void;
  world: CreatedWorld | null;
  relationship: RelationshipPayload | null;
  companionName: string;
  returnedQuestion?: string;
  onWorldChange: (world: CreatedWorld) => void;
}) {
  const [calibration, setCalibration] = useState<CalibrationId | null>(null);
  const [excluded, setExcluded] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [decisionReason, setDecisionReason] = useState("");
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const [appearance, setAppearance] = useState("雾蓝");
  const [temper, setTemper] = useState("安静观察");
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const candidate = world?.memories.find((memory) => memory.status === "candidate")
    || world?.memories.find((memory) => memory.status === "confirmed");

  useEffect(() => {
    if (candidate) setExcluded(!candidate.allow_social_recommendation);
  }, [candidate?.id]);

  useEffect(() => {
    if (!world) return;
    setAppearance(world.lifeform.appearance);
    setTemper(world.lifeform.exploration_tendency);
  }, [world?.lifeform.id, world?.lifeform.appearance, world?.lifeform.exploration_tendency]);

  const save = async () => {
    if (!calibration) return;
    if (!world) {
      setSaved(true);
      return;
    }
    setSaving(true);
    setSaveError("");
    try {
      const result = await calibrateAndAdvance(world, calibration, excluded);
      onWorldChange(result.world);
      setDecisionReason(result.decisionReason);
      setSaved(true);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "暂时无法保存校准。");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="desktop-lifeform" aria-labelledby="desktop-lifeform-title">
      <div className="desktop-lifeform__portrait">
        <img className="desktop-lifeform__portrait-image" src={lifeformPortraitSrc(appearance)} alt={`${world?.lifeform.name || "露米"}的完整生命体形态`} draggable={false} />
        <div className="desktop-lifeform__identity"><span>共生伙伴</span><h1 id="desktop-lifeform-title">{world?.lifeform.name || "露米"}</h1><p>从你的经历出发，去靠近更多可能。</p></div>
        <button type="button" className="desktop-ghost" aria-expanded={appearanceOpen} onClick={() => setAppearanceOpen((open) => !open)}><Pencil2Icon />调整形态与探索倾向</button>
        {appearanceOpen ? (
          <section className="desktop-appearance-panel" aria-label="生命体形态设置">
            <p>由系统生成基础形态，你来决定它如何表达自己。</p>
            <div><span>光色</span>{["雾蓝", "晨光", "流金"].map((item) => <button type="button" aria-pressed={appearance === item} className={appearance === item ? "is-selected" : ""} key={item} onClick={() => setAppearance(item)}>{item}</button>)}</div>
            <div><span>探索倾向</span>{["安静观察", "温和追问", "主动尝试"].map((item) => <button type="button" aria-pressed={temper === item} className={temper === item ? "is-selected" : ""} key={item} onClick={() => setTemper(item)}>{item}</button>)}</div>
            <small>当前：{appearance}光色 · {temper}</small>
          </section>
        ) : null}
      </div>
      <div className="desktop-lifeform__understanding">
        <p className="desktop-kicker">理解正在迭代</p>
        <h2>{candidate?.statement || "它开始更关注选择中的不确定性"}</h2>
        <p className="desktop-lead">{world ? `当前关注：${world.lifeform.current_focus}。这仍是一条可以纠正的候选理解。` : "这可能与你留下的问题有关，目前仍是候选理解。"}</p>
        <button type="button" className="desktop-evidence" aria-expanded={evidenceOpen} onClick={() => setEvidenceOpen((open) => !open)}><ReaderIcon /><span><strong>候选理解 · {candidate ? `${Math.round(candidate.confidence * 100)}% 置信度` : "中等置信度"}</strong><small>{evidenceOpen ? "收起形成依据" : `查看 ${candidate?.evidence_ids.length || 3} 条形成依据`}</small></span><ChevronRightIcon /></button>
        {evidenceOpen ? (
          <div className="desktop-evidence-list">
            <article><span>主动输入</span><p>{world ? "来自你创建生命体时亲自写下的问题。" : "来自演示场景中的预置问题。"}</p></article>
            <article><span>可解释来源</span><p>{candidate?.evidence_ids.join("、") || "演示证据已保留在审计记录中"}</p></article>
            <article><span>边界</span><p>用户校准前不会把候选理解当成固定人格。</p></article>
          </div>
        ) : null}
        <fieldset className="desktop-calibration">
          <legend>{world?.lifeform.name || "生命体"}理解得对吗？</legend>
          {(Object.entries(calibrationLabels) as [CalibrationId, string][]).map(([id, label]) => (
            <button type="button" key={id} className={calibration === id ? "is-selected" : ""} onClick={() => { setCalibration(id); setSaved(false); }}>
              {id === "like-me" ? <CheckCircledIcon /> : id === "wrong" ? <CrossCircledIcon /> : <EyeOpenIcon />}{label}
            </button>
          ))}
        </fieldset>
        <label className="desktop-check"><input type="checkbox" checked={excluded} onChange={(event) => { setExcluded(event.target.checked); setSaved(false); }} /><span>不要把这条理解用于社交推荐</span></label>
        <button type="button" className="desktop-primary desktop-lifeform__save" disabled={!calibration || saving} onClick={save}>{saving ? "正在计算下一步…" : saved ? "校准已经保存" : "保存并看看下一步"}<ArrowRightIcon /></button>
        {saveError ? <div className="onboarding-error" role="alert">{saveError}</div> : null}
        {saved ? <div className="desktop-save-note" role="status">{excluded ? "这条理解不会进入之后的关系推荐。" : `${world?.lifeform.name || "生命体"}会把你的校准作为新证据，而不是固定标签。`}</div> : null}
        {decisionReason ? <div className="desktop-save-note" role="status"><strong>下一步已经改变：</strong>{decisionReason}</div> : null}
        {world ? <ExplorationPanel world={world} onWorldChange={onWorldChange} /> : null}
        {world ? <UnderstandingManager world={world} onWorldChange={onWorldChange} returnedQuestion={returnedQuestion} /> : null}
        <div className="desktop-recent-relationship"><span>最近的相处记录</span><strong>{relationship ? `与${companionName} · ${relationshipStatusLabels[relationship.status]}` : "尚未形成共同经历"}</strong><button type="button" disabled={!relationship} onClick={onRelationship}>{relationship ? "查看经历" : "等待相遇"}<ChevronRightIcon /></button></div>
      </div>
    </section>
  );
}
