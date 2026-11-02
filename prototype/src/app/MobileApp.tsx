import { type ScreenId, type CreatedWorld, type SheetId, type CalibrationId } from "../shared/api/types";
import { Hotspot } from "../shared/ui/Hotspot";
import { useState, useMemo } from "react";
import { useKeyboard, MobileScroll, BottomSheet, KeyboardTextarea } from "../mobile";
import { useOnboarding } from "../features/onboarding/useOnboarding";
import { calibrateAndAdvance, saveReturnedQuestion } from "../features/understandings/api";
import { OnboardingScreen, BirthScreen } from "../features/onboarding/OnboardingScreen";
import { screens } from "../demo/content";
import { UnderstandingManager } from "../features/understandings/UnderstandingManager";
import { isStandaloneExperience } from "../shared/experience/mode";

import { calibrationLabels } from "../shared/config/options";
import { ExplorationPanel } from "../features/exploration/ExplorationPanel";

export function BottomNav({ screen, navigate, openProfile }: { screen: ScreenId; navigate: (screen: ScreenId) => void; openProfile: () => void }) {
  const top = screen === "world" ? 89.6 : 91.4;
  return (
    <>
      <Hotspot label="世界" x={0} y={top} width={25} height={8.6} onClick={() => navigate("world")} selected={screen === "world"} />
      <Hotspot label="生命体" x={25} y={top} width={25} height={8.6} onClick={() => navigate("lifeform")} selected={screen === "lifeform"} />
      <Hotspot label="关系" x={50} y={top} width={25} height={8.6} onClick={() => navigate("relationship")} selected={screen === "relationship"} />
      <Hotspot label="我的" x={75} y={top} width={25} height={8.6} onClick={openProfile} />
    </>
  );
}

export function MobilePrototype() {
  const [screen, setScreen] = useState<ScreenId>("create");
  const { answers: onboarding, setAnswers: setOnboarding, error: onboardingError, submitting: submittingOnboarding, submit: createLifeform } = useOnboarding();
  const [createdWorld, setCreatedWorld] = useState<CreatedWorld | null>(null);
  const [sheet, setSheet] = useState<SheetId>(null);
  const [calibration, setCalibration] = useState<CalibrationId | null>(null);
  const [excludeSocial, setExcludeSocial] = useState(false);
  const [savingCalibration, setSavingCalibration] = useState(false);
  const [calibrationError, setCalibrationError] = useState("");
  const [calibrationMessage, setCalibrationMessage] = useState("");
  const [responseChoice, setResponseChoice] = useState("");
  const [responseText, setResponseText] = useState("");
  const [chatText, setChatText] = useState("");
  const [sentMessages, setSentMessages] = useState<string[]>([]);
  const keyboard = useKeyboard();

  const navigate = (next: ScreenId) => {
    keyboard.hide();
    setSheet(null);
    setScreen(next);
  };

  const sheetCopy = useMemo(() => {
    switch (sheet) {
      case "evidence":
        return { title: "这条理解从哪里来", description: "露米只使用你允许用于成长的内容，并保留不确定性。" };
      case "memory":
        return { title: "露米的记忆", description: "记忆不是永久标签，你随时可以校准、隐藏或删除。" };
      case "respond":
        return { title: "回应露米带回的问题", description: "你的回答不会改写已经发生的事件，只会影响它接下来如何理解和探索。" };
      case "saved":
        return { title: "这次校准已经保存", description: "露米会保留你的纠正，而不是把一次关注当成永久特质。" };
      case "response-saved":
        return { title: "回应已经交给露米", description: "事件不会被改写，这次回答会成为它继续理解你的新线索。" };
      case "profile":
        return { title: "你的边界由你决定", description: "成长材料、社交使用与真人连接始终分开授权。" };
      case "intro":
        return { title: "让露米先做一次引荐", description: "它只会说明共同经历，不会替你表达立场。" };
      case "chat":
        return { title: "和阿澈的主人聊聊", description: "你们可以从共同问题开始，也可以完全换一个话题。" };
      default:
        return { title: "", description: "" };
    }
  }, [sheet]);

  const sendMessage = () => {
    const message = chatText.trim();
    if (!message) return;
    keyboard.hide();
    setSentMessages((items) => [...items, message]);
    setChatText("");
  };

  const submitOnboarding = async () => {
    keyboard.hide();
    const world = await createLifeform();
    if (!world) return;
    setCreatedWorld(world);
    const candidate = world.memories.find((memory) => memory.status === "candidate");
    setExcludeSocial(candidate ? !candidate.allow_social_recommendation : false);
    setScreen("born");
  };
  const saveCalibration = async () => {
    if (!createdWorld || !calibration || savingCalibration) return;
    keyboard.hide();
    setSavingCalibration(true);
    setCalibrationError("");
    try {
      const result = await calibrateAndAdvance(createdWorld, calibration, excludeSocial);
      setCreatedWorld(result.world);
      setCalibrationMessage(result.decisionReason);
      setSheet("saved");
    } catch (error) {
      setCalibrationError(error instanceof Error ? error.message : "暂时无法保存校准。");
    } finally {
      setSavingCalibration(false);
    }
  };

  if (screen === "create") {
    return (
      <MobileScroll className="app-screen wj-screen">
        <OnboardingScreen answers={onboarding} onChange={setOnboarding} submitting={submittingOnboarding} error={onboardingError} onSubmit={submitOnboarding} />
      </MobileScroll>
    );
  }

  if (screen === "born") {
    return createdWorld ? (
      <MobileScroll className="app-screen wj-screen">
        <BirthScreen world={createdWorld} onEnter={() => navigate("world")} />
      </MobileScroll>
    ) : null;
  }

  return (
    <>
      <MobileScroll key={screen} className="app-screen wj-screen">
        <main className="screen-artboard" aria-live="polite">
          <img className="screen-image" src={screens[screen].src} alt={screens[screen].alt} draggable={false} />

          {screen === "world" ? (
            <>
              <Hotspot label="查看当前事件：灯塔即将熄灭" x={5} y={47.5} width={80} height={18} onClick={() => navigate("event")} />
              <Hotspot label="看看发生了什么" x={17} y={79.8} width={66} height={7.4} onClick={() => navigate("event")} />
              <BottomNav screen={screen} navigate={navigate} openProfile={() => setSheet("profile")} />
            </>
          ) : null}

          {screen === "lifeform" ? (
            <>
              <Hotspot label="查看露米的记忆" x={75} y={3.4} width={21} height={5.2} onClick={() => setSheet("memory")} />
              <Hotspot label="查看候选理解依据" x={5} y={59.9} width={90} height={5.5} onClick={() => setSheet("evidence")} />
              <Hotspot label="很像我" x={5} y={67.6} width={44} height={4.4} onClick={() => setCalibration("like-me")} selected={calibration === "like-me"} />
              <Hotspot label="只是最近关注" x={51} y={67.6} width={44} height={4.4} onClick={() => setCalibration("recent")} selected={calibration === "recent"} />
              <Hotspot label="我是在反对这个观点" x={5} y={72.4} width={44} height={4.4} onClick={() => setCalibration("opposing")} selected={calibration === "opposing"} />
              <Hotspot label="露米理解错了" x={51} y={72.4} width={44} height={4.4} onClick={() => setCalibration("wrong")} selected={calibration === "wrong"} />
              <Hotspot label="不要用于社交推荐" x={5} y={76.8} width={48} height={3.6} onClick={() => setExcludeSocial((value) => !value)} selected={excludeSocial} className="toggle-hotspot" />
              <Hotspot label="查看与阿澈的关系" x={5} y={80.2} width={90} height={5.7} onClick={() => navigate("relationship")} />
              <Hotspot label="保存这次校准" x={9} y={86.2} width={82} height={5.6} onClick={saveCalibration} />
              <BottomNav screen={screen} navigate={navigate} openProfile={() => setSheet("profile")} />
            </>
          ) : null}

          {screen === "event" ? (
            <>
              <Hotspot label="返回世界" x={2} y={1.3} width={12} height={6.4} onClick={() => navigate("world")} />
              <Hotspot label="回应这个问题" x={7} y={91.2} width={86} height={5.2} onClick={() => setSheet("respond")} />
              <Hotspot label="暂时不回应" x={7} y={96.2} width={86} height={3.5} onClick={() => navigate("world")} />
            </>
          ) : null}

          {screen === "relationship" ? (
            <>
              <Hotspot label="查看连接邀请" x={8} y={80.8} width={84} height={6.2} onClick={() => navigate("connection")} />
              <Hotspot label="继续观察这段关系" x={8} y={86.7} width={84} height={4.7} onClick={() => navigate("world")} />
              <BottomNav screen={screen} navigate={navigate} openProfile={() => setSheet("profile")} />
            </>
          ) : null}

          {screen === "connection" ? (
            <>
              <Hotspot label="返回关系故事" x={2} y={1.4} width={12} height={6} onClick={() => navigate("relationship")} />
              <Hotspot label="我愿意认识阿澈的主人" x={8} y={82.6} width={84} height={6.2} onClick={() => navigate("icebreaker")} />
              <Hotspot label="暂时不了" x={8} y={89.1} width={84} height={5.3} onClick={() => navigate("relationship")} />
            </>
          ) : null}

          {screen === "icebreaker" ? (
            <>
              <Hotspot label="返回真人连接" x={2} y={1.4} width={12} height={6} onClick={() => navigate("connection")} />
              <Hotspot label="使用共同问题开始聊天" x={7} y={76.7} width={86} height={6.2} onClick={() => setSheet("chat")} />
              <Hotspot label="让生命体做一次引荐" x={7} y={83.4} width={86} height={5.6} onClick={() => setSheet("intro")} />
              <Hotspot label="直接进入真人聊天" x={26} y={89.5} width={48} height={4.7} onClick={() => setSheet("chat")} />
            </>
          ) : null}
        </main>
      </MobileScroll>

      <BottomSheet open={sheet !== null} onOpenChange={(open) => !open && setSheet(null)} title={sheetCopy.title} description={sheetCopy.description} snap={sheet === "chat" ? 0.82 : 0.72}>
        {sheet === "evidence" ? (
          <div className="sheet-stack">
            <div className="evidence-row"><span>来源</span><strong>你在创建生命体时主动写下的问题</strong></div>
            <div className="evidence-row"><span>依据编号</span><strong>{createdWorld?.memories.find((memory) => memory.status === "candidate")?.evidence_ids.join("、") || "已保留在审计记录中"}</strong></div>
            <p className="boundary-note">这些材料只形成“候选理解”。在你确认之前，它不会被当成稳定人格，也不会自动用于社交推荐。</p>
          </div>
        ) : null}

        {sheet === "memory" ? (
          <div className="sheet-stack">
            {createdWorld ? <UnderstandingManager world={createdWorld} onWorldChange={setCreatedWorld} /> : null}
            {!createdWorld ? <div className="memory-card"><span>演示理解</span><strong>你在选择中重视自主决定</strong><small>进入真实创建流程后可校准</small></div> : null}
          </div>
        ) : null}

        {sheet === "respond" ? (
          <div className="sheet-stack">
            <blockquote className="returned-question">如果是你，你会留下修复灯塔，还是登船探索未知？</blockquote>
            <div className="choice-grid" role="group" aria-label="快速回应">
              {["留下修复灯塔", "登船探索未知", "我还没有答案"].map((choice) => (
                <button type="button" key={choice} className={`choice-chip ${responseChoice === choice ? "is-active" : ""}`} onClick={() => setResponseChoice(choice)}>{choice}</button>
              ))}
            </div>
            <KeyboardTextarea className="wj-textarea" value={responseText} onChange={(event) => setResponseText(event.target.value)} placeholder="也可以写下一段经历或你在意的原因" maxLength={240} />
            <button type="button" className="sheet-primary" disabled={savingCalibration || (!responseChoice && !responseText.trim())} onClick={async () => {
              keyboard.hide(); setSavingCalibration(true); setCalibrationError("");
              try {
                if (createdWorld && !isStandaloneExperience()) {
                  await saveReturnedQuestion(createdWorld, [responseChoice, responseText].filter(Boolean).join("。"));
                }
                setSheet("response-saved");
              } catch (error) { setCalibrationError(error instanceof Error ? error.message : "回应保存失败"); }
              finally { setSavingCalibration(false); }
            }}>把回应交给露米</button>
            <button type="button" className="sheet-secondary" onClick={() => setSheet(null)}>暂时不回应</button>
          </div>
        ) : null}

        {sheet === "saved" ? (
          <div className="sheet-stack sheet-success">
            <p className="success-kicker">理解已被你校准</p>
            <h3>{calibration ? `“${calibrationLabels[calibration]}”` : "你的回应已经交给露米"}</h3>
            <p>{excludeSocial ? "这条理解不会用于社交推荐。" : "露米会把这次反馈作为有限证据，继续观察而不是替你下结论。"}</p>
            {calibrationMessage ? <p className="boundary-note">下一步：{calibrationMessage}</p> : null}
            <button type="button" className="sheet-primary" onClick={() => navigate("world")}>回到世界，看看接下来发生什么</button>
          </div>
        ) : null}

        {sheet === "response-saved" ? (
          <div className="sheet-stack sheet-success">
            <p className="success-kicker">一次有意义的回应</p>
            <h3>{responseChoice || "你的经历已经被留下"}</h3>
            <p>露米不会用这个答案替你表态，只会带着它继续理解“自主选择”对你意味着什么。</p>
            <button type="button" className="sheet-primary" onClick={() => navigate("relationship")}>看看这段关系如何继续</button>
          </div>
        ) : null}

        {sheet === "profile" ? (
          <div className="sheet-stack">
            {createdWorld ? <ExplorationPanel world={createdWorld} onWorldChange={setCreatedWorld} /> : null}
            <div className="permission-row"><div><strong>用于生命体成长</strong><small>你主动授权的表达与选择</small></div><span>已开启</span></div>
            <div className="permission-row"><div><strong>用于社交探索</strong><small>每条理解都可单独关闭</small></div><span>逐条决定</span></div>
            <div className="permission-row"><div><strong>真人连接</strong><small>只有双方同意后才开放</small></div><span>双向同意</span></div>
          </div>
        ) : null}

        {sheet === "intro" ? (
          <div className="sheet-stack">
            <div className="intro-card"><strong>露米会这样介绍你们</strong><p>“你们在灯塔事件里作出了不同选择，但都不希望由别人替自己决定未来。这段差异也许值得继续聊聊。”</p></div>
            <button type="button" className="sheet-primary" onClick={() => setSheet("chat")}>使用这段引荐</button>
            <button type="button" className="sheet-secondary" onClick={() => setSheet(null)}>我想自己开始</button>
          </div>
        ) : null}

        {sheet === "chat" ? (
          <div className="chat-sheet">
            <div className="starter-message"><span>共同问题</span><p>你们的生命体在灯塔前作出了不同选择。最近一次你自己作出的重要决定是什么？</p></div>
            <div className="chat-stream" aria-live="polite">
              <div className="peer-message">我最后选了继续留在熟悉的城市，但给自己留了三个月重新判断。你呢？</div>
              {sentMessages.map((message, index) => <div className="own-message" key={`${message}-${index}`}>{message}</div>)}
            </div>
            <div className="composer">
              <KeyboardTextarea className="chat-input" value={chatText} onChange={(event) => setChatText(event.target.value)} placeholder="说说你的答案" rows={2} />
              <button type="button" className="send-button" disabled={!chatText.trim()} onClick={sendMessage}>发送</button>
            </div>
          </div>
        ) : null}
      </BottomSheet>
      {calibrationError ? <div className="onboarding-error" role="alert">{calibrationError}</div> : null}
      {savingCalibration ? <div className="desktop-save-note" role="status">正在保存校准并计算下一步行动…</div> : null}
    </>
  );
}
