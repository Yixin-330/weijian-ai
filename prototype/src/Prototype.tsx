import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  ArrowRightIcon,
  CheckCircledIcon,
  ChevronRightIcon,
  CrossCircledIcon,
  EyeOpenIcon,
  GlobeIcon,
  HeartIcon,
  Pencil2Icon,
  PersonIcon,
  ReaderIcon,
} from "@radix-ui/react-icons";
import { BottomSheet, KeyboardTextarea, MobileScroll, useKeyboard } from "./mobile";

type ScreenId = "create" | "born" | "world" | "lifeform" | "event" | "relationship" | "connection" | "icebreaker";
type ArtworkScreenId = Exclude<ScreenId, "create" | "born">;
type SheetId = "evidence" | "memory" | "respond" | "saved" | "response-saved" | "profile" | "intro" | "chat" | null;
type CalibrationId = "like-me" | "recent" | "opposing" | "wrong";

const screens: Record<ArtworkScreenId, { src: string; alt: string }> = {
  world: {
    src: "/assets/wj/wj-world-home-hifi-v1.png",
    alt: "未见世界首页：露米前往稳定还是冒险问题岛，并与阿澈形成共同经历",
  },
  lifeform: {
    src: "/assets/wj/wj-lifeform-home-hifi-v2.png",
    alt: "露米生命体主页：查看今日成长并校准一条候选理解",
  },
  event: {
    src: "/assets/wj/wj-shared-event-hifi-v2.png",
    alt: "共同事件：灯塔即将熄灭，露米与阿澈作出不同选择并带回一个问题",
  },
  relationship: {
    src: "/assets/wj/wj-relationship-story-hifi-v1.png",
    alt: "露米与阿澈的关系故事：从不同答案里看见彼此",
  },
  connection: {
    src: "/assets/wj/wj-human-connection-hifi-v1.png",
    alt: "真人连接邀请：决定是否认识阿澈的主人",
  },
  icebreaker: {
    src: "/assets/wj/wj-icebreaker-hifi-v1.png",
    alt: "连接成功：从共同经历形成的破冰问题开始真人聊天",
  },
};

const calibrationLabels: Record<CalibrationId, string> = {
  "like-me": "很像我",
  recent: "只是最近",
  opposing: "我在反对",
  wrong: "理解错了",
};

type TopicId = "choice_uncertainty" | "intimacy_and_autonomy" | "ai_and_loneliness";
type ExplorationId = "observe" | "inquire" | "act";
type SocialPaceId = "observe_first" | "shared_experiences" | "open_to_connection";

type CreatedWorld = {
  user: { id: string };
  lifeform: {
    id: string;
    name: string;
    appearance: string;
    exploration_tendency: string;
    current_island_id: string;
    current_focus: string;
    status: string;
  };
  memories: Array<{
    id: string;
    statement: string;
    status: "candidate" | "confirmed" | "rejected";
    confidence: number;
    evidence_ids: string[];
    allow_social_recommendation: boolean;
    calibration?: "like_me" | "recent" | "opposes" | "wrong" | null;
  }>;
  latest_tick?: {
    selected_island_id: string;
    decision_reason: string;
  } | null;
};

type OnboardingAnswers = {
  currentQuestion: string;
  topics: TopicId[];
  exploration: ExplorationId | null;
  socialPace: SocialPaceId | null;
  allowMemory: boolean;
  allowSocial: boolean;
};

const topicOptions: Array<{ id: TopicId; label: string }> = [
  { id: "choice_uncertainty", label: "选择、稳定与冒险" },
  { id: "intimacy_and_autonomy", label: "亲密关系与独立" },
  { id: "ai_and_loneliness", label: "AI、陪伴与真实关系" },
];

const explorationOptions: Array<{ id: ExplorationId; label: string; note: string }> = [
  { id: "observe", label: "先安静观察", note: "留意差异与不确定性" },
  { id: "inquire", label: "先温和追问", note: "用问题靠近不同答案" },
  { id: "act", label: "先尝试行动", note: "在共同经历里继续理解" },
];

const socialPaceOptions: Array<{ id: SocialPaceId; label: string }> = [
  { id: "observe_first", label: "先观察，不主动接近" },
  { id: "shared_experiences", label: "共同经历几次后再靠近" },
  { id: "open_to_connection", label: "合适时可以建议连接" },
];

const islandLabels: Record<string, string> = {
  stability: "稳定还是冒险",
  intimacy: "亲密与自由",
  ai_loneliness: "AI 会让人更孤独吗",
};

const apiBaseUrl = () => (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

const isStandaloneExperience = () => {
  if (import.meta.env.VITE_EXPERIENCE_MODE === "standalone") return true;
  if (import.meta.env.VITE_API_BASE_URL) return false;
  return !["127.0.0.1", "localhost"].includes(window.location.hostname);
};

const calibrationDecisions: Record<CalibrationId, "like_me" | "recent" | "opposes" | "wrong"> = {
  "like-me": "like_me",
  recent: "recent",
  opposing: "opposes",
  wrong: "wrong",
};

type CalibrationResult = { world: CreatedWorld; decisionReason: string };

const topicToIsland: Record<TopicId, IslandId> = {
  choice_uncertainty: "stability",
  intimacy_and_autonomy: "intimacy",
  ai_and_loneliness: "ai_loneliness",
};

const standaloneUnderstandings: Record<TopicId, { statement: string; focus: string }> = {
  choice_uncertainty: {
    statement: "你最近可能正在反复衡量：稳定是否值得用一部分可能性去交换。",
    focus: "稳定、选择与可以承担的代价",
  },
  intimacy_and_autonomy: {
    statement: "你可能在亲密关系中重视靠近，也想保留独立判断与边界。",
    focus: "亲密关系中的靠近与自主",
  },
  ai_and_loneliness: {
    statement: "你正在关注：被准确回应与被真实的人努力理解，是否是同一件事。",
    focus: "AI 陪伴与真实关系的差异",
  },
};

function createStandaloneWorld(answers: OnboardingAnswers): CreatedWorld {
  const primaryTopic = answers.topics[0] || "choice_uncertainty";
  const understanding = standaloneUnderstandings[primaryTopic];
  const explorationLabels: Record<ExplorationId, string> = {
    observe: "安静观察",
    inquire: "温和追问",
    act: "在共同经历中行动",
  };
  const worldId = crypto.randomUUID();
  return {
    user: { id: `experience-user-${worldId}` },
    lifeform: {
      id: `experience-lifeform-${worldId}`,
      name: "露米",
      appearance: "雾蓝半透明翼状生命体",
      exploration_tendency: explorationLabels[answers.exploration || "observe"],
      current_island_id: topicToIsland[primaryTopic],
      current_focus: understanding.focus,
      status: "正在形成初始理解",
    },
    memories: [{
      id: `experience-understanding-${worldId}`,
      statement: understanding.statement,
      status: "candidate",
      confidence: 0.72,
      evidence_ids: [`主动输入：${answers.currentQuestion.trim()}`],
      allow_social_recommendation: answers.allowSocial,
      calibration: null,
    }],
    latest_tick: null,
  };
}

async function createWorldFromOnboarding(answers: OnboardingAnswers, idempotencyKey: string): Promise<CreatedWorld> {
  if (isStandaloneExperience()) {
    await new Promise((resolve) => window.setTimeout(resolve, 450));
    return createStandaloneWorld(answers);
  }

  const response = await fetch(`${apiBaseUrl()}/api/v1/onboarding`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify({
      current_question: answers.currentQuestion,
      long_term_topics: answers.topics,
      exploration_style: answers.exploration,
      social_pace: answers.socialPace,
      allow_memory_inference: answers.allowMemory,
      allow_social_recommendation: answers.allowSocial,
    }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(payload?.detail || `创建失败（${response.status}）`);
  }
  return response.json() as Promise<CreatedWorld>;
}

async function calibrateAndAdvance(
  world: CreatedWorld,
  calibration: CalibrationId,
  excludeSocial: boolean,
): Promise<CalibrationResult> {
  const candidate = world.memories.find((memory) => memory.status === "candidate")
    || world.memories.find((memory) => memory.calibration);
  if (!candidate) throw new Error("当前没有可校准的候选理解。");

  if (isStandaloneExperience()) {
    await new Promise((resolve) => window.setTimeout(resolve, 450));
    const decision = calibrationDecisions[calibration];
    const currentIsland = isIslandId(world.lifeform.current_island_id)
      ? world.lifeform.current_island_id
      : "stability";
    const nextIsland: IslandId = calibration === "opposing"
      ? (currentIsland === "intimacy" ? "stability" : "intimacy")
      : calibration === "recent"
        ? (currentIsland === "ai_loneliness" ? "stability" : "ai_loneliness")
        : currentIsland;
    const action = calibration === "like-me" ? "靠近" : calibration === "opposing" ? "回应" : "观察";
    const effect = calibration === "wrong"
      ? "这条候选理解已被否定，不再影响探索方向"
      : calibration === "recent"
        ? "它被保留为近期状态，生命体转向观察另一种可能"
        : calibration === "opposing"
          ? "反对本身成为新的明确证据，生命体转向探索边界与差异"
          : "这条理解得到确认，生命体愿意沿当前问题继续靠近";
    const updatedWorld: CreatedWorld = {
      ...world,
      lifeform: {
        ...world.lifeform,
        current_island_id: nextIsland,
        status: `下一步动作：${action}`,
      },
      memories: world.memories.map((memory) => memory.id === candidate.id ? {
        ...memory,
        status: calibration === "wrong" ? "rejected" : "confirmed",
        calibration: decision,
        allow_social_recommendation: !excludeSocial,
      } : memory),
      latest_tick: {
        selected_island_id: nextIsland,
        decision_reason: `${effect}；下一步动作是「${action}」，前往「${islandLabels[nextIsland]}」。`,
      },
    };
    return { world: updatedWorld, decisionReason: updatedWorld.latest_tick!.decision_reason };
  }

  const calibrationResponse = await fetch(
    `${apiBaseUrl()}/api/v1/understandings/${candidate.id}/calibrations`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: world.user.id,
        decision: calibrationDecisions[calibration],
        allow_social_recommendation: !excludeSocial,
      }),
    },
  );
  if (!calibrationResponse.ok) {
    const payload = await calibrationResponse.json().catch(() => null) as { detail?: string } | null;
    throw new Error(payload?.detail || `校准保存失败（${calibrationResponse.status}）`);
  }

  const tickResponse = await fetch(`${apiBaseUrl()}/api/v1/users/${world.user.id}/next-action`, {
    method: "POST",
    headers: {
      "Idempotency-Key": crypto.randomUUID(),
    },
  });
  if (!tickResponse.ok) {
    const payload = await tickResponse.json().catch(() => null) as { detail?: string } | null;
    throw new Error(payload?.detail || `下一步探索触发失败（${tickResponse.status}）`);
  }

  let job = await tickResponse.json() as {
    job_id: string;
    status: string;
    tick?: { decision_reason: string } | null;
    error?: string | null;
  };
  for (let attempt = 0; job.status === "queued" || job.status === "in_progress"; attempt += 1) {
    if (attempt >= 20) throw new Error("校准已保存，生命体仍在准备下一步探索，请稍后查看。");
    await new Promise((resolve) => window.setTimeout(resolve, 300));
    const jobResponse = await fetch(`${apiBaseUrl()}/api/v1/world/tick-jobs/${job.job_id}`);
    if (!jobResponse.ok) throw new Error("校准已保存，但暂时无法读取下一步探索。");
    job = await jobResponse.json();
  }
  if (job.status === "failed") throw new Error(job.error || "校准已保存，但下一步探索失败。");

  const worldResponse = await fetch(`${apiBaseUrl()}/api/v1/users/${world.user.id}/world`);
  if (!worldResponse.ok) throw new Error("校准已保存，但暂时无法刷新生命体状态。");
  return {
    world: await worldResponse.json() as CreatedWorld,
    decisionReason: job.tick?.decision_reason || "校准已生效，生命体已经调整了下一步行动。",
  };
}

function OnboardingScreen({ answers, onChange, submitting, error, onSubmit }: {
  answers: OnboardingAnswers;
  onChange: (answers: OnboardingAnswers) => void;
  submitting: boolean;
  error: string;
  onSubmit: () => void;
}) {
  const toggleTopic = (topic: TopicId) => {
    const selected = answers.topics.includes(topic);
    if (!selected && answers.topics.length >= 3) return;
    onChange({
      ...answers,
      topics: selected ? answers.topics.filter((item) => item !== topic) : [...answers.topics, topic],
    });
  };
  const complete = answers.currentQuestion.trim().length >= 4
    && answers.topics.length > 0
    && answers.exploration !== null
    && answers.socialPace !== null
    && answers.allowMemory;

  return (
    <main className="onboarding" aria-labelledby="onboarding-title">
      <header className="onboarding__header">
        <span>未见 · 创建生命体</span>
        <strong>四个问题，一点真实的好奇就够了</strong>
        <p>这些回答只建立可调整的初始状态，不是人格测试。</p>
      </header>

      <section className="onboarding-question">
        <span>01 · 当前关注</span>
        <h1 id="onboarding-title">最近，什么问题一直留在你心里？</h1>
        <KeyboardTextarea
          className="onboarding-textarea"
          value={answers.currentQuestion}
          onChange={(event) => onChange({ ...answers, currentQuestion: event.target.value })}
          placeholder="例如：我该继续稳定的工作，还是尝试一次更冒险的方向？"
          maxLength={240}
          rows={4}
        />
        <small>{answers.currentQuestion.trim().length}/240</small>
      </section>

      <section className="onboarding-question">
        <span>02 · 长期好奇</span>
        <h2>除了眼前的问题，你愿意让它长期关注什么？</h2>
        <p>选择 1–3 项，之后随时可以调整。</p>
        <div className="onboarding-topic-grid">
          {topicOptions.map((topic) => (
            <button type="button" key={topic.id} className={answers.topics.includes(topic.id) ? "is-selected" : ""} aria-pressed={answers.topics.includes(topic.id)} onClick={() => toggleTopic(topic.id)}>
              {topic.label}
            </button>
          ))}
        </div>
      </section>

      <section className="onboarding-question">
        <span>03 · 探索方式</span>
        <h2>遇到陌生问题时，你希望它先怎么做？</h2>
        <div className="onboarding-option-list">
          {explorationOptions.map((option) => (
            <button type="button" key={option.id} className={answers.exploration === option.id ? "is-selected" : ""} aria-pressed={answers.exploration === option.id} onClick={() => onChange({ ...answers, exploration: option.id })}>
              <strong>{option.label}</strong><small>{option.note}</small>
            </button>
          ))}
        </div>
      </section>

      <section className="onboarding-question">
        <span>04 · 关系节奏</span>
        <h2>你希望它以什么节奏接近别人？</h2>
        <div className="onboarding-option-list onboarding-option-list--compact">
          {socialPaceOptions.map((option) => (
            <button type="button" key={option.id} className={answers.socialPace === option.id ? "is-selected" : ""} aria-pressed={answers.socialPace === option.id} onClick={() => onChange({ ...answers, socialPace: option.id })}>
              <strong>{option.label}</strong>
            </button>
          ))}
        </div>
      </section>

      <section className="onboarding-consent" aria-label="使用授权">
        <label><input type="checkbox" checked={answers.allowMemory} onChange={(event) => onChange({ ...answers, allowMemory: event.target.checked })} /><span><strong>用于生成并调整生命体</strong><small>原始回答不会展示给其他用户</small></span></label>
        <label><input type="checkbox" checked={answers.allowSocial} onChange={(event) => onChange({ ...answers, allowSocial: event.target.checked })} /><span><strong>允许候选理解用于社交探索</strong><small>每条理解仍可单独关闭</small></span></label>
      </section>

      {error ? <p className="onboarding-error" role="alert">{error}</p> : null}
      <button type="button" className="onboarding-submit" disabled={!complete || submitting} onClick={onSubmit}>
        {submitting ? "它正在形成…" : "让它开始生长"}<ArrowRightIcon />
      </button>
    </main>
  );
}

function BirthScreen({ world, onEnter }: { world: CreatedWorld; onEnter: () => void }) {
  const candidate = world.memories.find((memory) => memory.status === "candidate");
  const confirmed = world.memories.filter((memory) => memory.status === "confirmed");
  return (
    <main className="birth" aria-labelledby="birth-title">
      <div className="birth__glow" aria-hidden="true"><span /></div>
      <p className="birth__kicker">初始状态已经形成</p>
      <h1 id="birth-title">{world.lifeform.name}</h1>
      <p className="birth__description">
        它从你的真实问题中醒来，更习惯{world.lifeform.exploration_tendency}。这只是起点，之后的回应与校准会继续改变它。
      </p>
      <dl className="birth__state">
        <div><dt>当前关注</dt><dd>{world.lifeform.current_focus}</dd></div>
        <div><dt>初始形态</dt><dd>{world.lifeform.appearance} · {world.lifeform.exploration_tendency}</dd></div>
        <div><dt>准备前往</dt><dd>{islandLabels[world.lifeform.current_island_id] || "新的问题岛"}</dd></div>
      </dl>
      {candidate ? (
        <article className="birth__memory">
          <span>候选理解 · {Math.round(candidate.confidence * 100)}% 置信度</span>
          <p>{candidate.statement}</p>
          <small>它还不是固定特质，进入世界后可以继续校准。</small>
        </article>
      ) : null}
      <div className="birth__topics">
        <span>你明确选择的长期关注</span>
        {confirmed.map((memory) => <small key={memory.id}>{memory.statement}</small>)}
      </div>
      <button type="button" className="onboarding-submit" onClick={onEnter}>进入它的初始世界<ArrowRightIcon /></button>
    </main>
  );
}

function Hotspot({
  label,
  x,
  y,
  width,
  height,
  onClick,
  selected = false,
  className = "",
}: {
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
  onClick: () => void;
  selected?: boolean;
  children?: ReactNode;
  className?: string;
}) {
  const style = {
    left: `${x}%`,
    top: `${y}%`,
    width: `${width}%`,
    height: `${height}%`,
  } satisfies CSSProperties;

  return (
    <button
      type="button"
      className={`hotspot ${selected ? "is-selected" : ""} ${className}`}
      style={style}
      onClick={onClick}
      aria-label={label}
      aria-pressed={selected || undefined}
    />
  );
}

function BottomNav({ screen, navigate, openProfile }: { screen: ScreenId; navigate: (screen: ScreenId) => void; openProfile: () => void }) {
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

function MobilePrototype() {
  const [screen, setScreen] = useState<ScreenId>("create");
  const [onboardingKey] = useState(() => crypto.randomUUID());
  const [onboarding, setOnboarding] = useState<OnboardingAnswers>({
    currentQuestion: "",
    topics: [],
    exploration: null,
    socialPace: null,
    allowMemory: true,
    allowSocial: false,
  });
  const [onboardingError, setOnboardingError] = useState("");
  const [submittingOnboarding, setSubmittingOnboarding] = useState(false);
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
    if (!onboarding.exploration || !onboarding.socialPace) return;
    keyboard.hide();
    setSubmittingOnboarding(true);
    setOnboardingError("");
    try {
      const world = await createWorldFromOnboarding(onboarding, onboardingKey);
      setCreatedWorld(world);
      const candidate = world.memories.find((memory) => memory.status === "candidate");
      setExcludeSocial(candidate ? !candidate.allow_social_recommendation : false);
      setScreen("born");
    } catch (error) {
      setOnboardingError(error instanceof Error ? error.message : "暂时无法创建，请稍后重试。");
    } finally {
      setSubmittingOnboarding(false);
    }
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
            {createdWorld?.memories.map((memory) => (
              <div className="memory-card" key={memory.id}><span>{memory.status === "candidate" ? "正在形成" : memory.status === "rejected" ? "已被你否定" : "已经确认"}</span><strong>{memory.statement}</strong><small>{Math.round(memory.confidence * 100)}% 置信度 · {memory.evidence_ids.length} 条明确来源</small></div>
            )) || <div className="memory-card"><span>演示理解</span><strong>你在选择中重视自主决定</strong><small>进入真实创建流程后可校准</small></div>}
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
            <button type="button" className="sheet-primary" disabled={!responseChoice && !responseText.trim()} onClick={() => { keyboard.hide(); setSheet("response-saved"); }}>把回应交给露米</button>
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

type DesktopView = "world" | "lifeform" | "relationship" | "invitation";
type DesktopStage = "onboarding" | "born" | DesktopView;
type IslandId = "stability" | "intimacy" | "ai_loneliness";
type IslandViewpoint = { materialId: string; summary: string; sourceUrl: string };
type DesktopIsland = {
  name: string;
  eyebrow: string;
  question: string;
  questionUrl: string;
  note: string;
  position: string;
  viewpointCount: number;
  viewpoints: IslandViewpoint[];
};

type IslandCatalogResponse = {
  fixture_version: string;
  islands: Array<{
    island_id: string;
    island_name: string;
    source: { question_title: string; question_url: string };
    viewpoint_count: number;
    viewpoint_materials: Array<{
      material_id: string;
      summary: string;
      source_url: string;
    }>;
  }>;
};

const islandIds = ["stability", "intimacy", "ai_loneliness"] as const;
const isIslandId = (value: string): value is IslandId => islandIds.some((id) => id === value);

const fallbackDesktopIslands: Record<IslandId, DesktopIsland> = {
  stability: {
    name: "稳定还是冒险",
    eyebrow: "当前岛屿",
    question: "年轻人到底该安稳打工，还是该冒险闯一闯？",
    questionUrl: "https://www.zhihu.com/question/2024798149236016151",
    note: "露米正在与阿澈交流。不同的选择，正在让它们看见彼此。",
    position: "desktop-island--stability",
    viewpointCount: 1,
    viewpoints: [{
      materialId: "stability-m02",
      summary: "人生没有什么应不应该，也没有什么原生意义。一切追溯到本质自负盈亏，自赋意义。承受得起代价就可以。",
      sourceUrl: "https://www.zhihu.com/question/2024798149236016151/answer/2025609884360516946",
    }],
  },
  intimacy: {
    name: "亲密与自由",
    eyebrow: "可以前往",
    question: "在亲密关系中，如何平衡独立性与彼此的亲密？",
    questionUrl: "https://www.zhihu.com/question/1950879757458706791",
    note: "露米会带着你校准过的边界，决定是否前往探索。",
    position: "desktop-island--intimacy",
    viewpointCount: 1,
    viewpoints: [{
      materialId: "intimacy-m01",
      summary: "这是一个动态而且持续的过程，不是一蹴而就的。 根据“ 自我决定论”，人有三种基本需求：自主性、胜任感和归属感——很多时候人只关注亲密关系里需要“归属感”里的亲密和联系的需求，却忘了人也有自主感和胜任感里独立和自我发展、自我决定方面的需求。而且三种感觉不是互相排斥的，而是互相促进的： 自主感能让人在独处的时候发展自己，给自己充电，也能反思关系里发生的事情，也是人安全感重要的来源；胜任感更多和人能决定…",
      sourceUrl: "https://www.zhihu.com/question/1950879757458706791/answer/1952771442778313194",
    }],
  },
  ai_loneliness: {
    name: "AI 会让人更孤独吗",
    eyebrow: "可以前往",
    question: "AI 能让人减少孤独，还是会让人更孤独？",
    questionUrl: "https://www.zhihu.com/question/2050922931207632609",
    note: "这里正在形成一场关于理解、陪伴与真实摩擦的讨论。",
    position: "desktop-island--ai",
    viewpointCount: 1,
    viewpoints: [{
      materialId: "ai_loneliness-m01",
      summary: "这个问题让我想起了古希腊神话中一个很经典的悖论：俄耳浦斯回头。 在冥王的准许下，失去妻子的俄耳浦斯即将带着妻子的灵魂重回人间。冥王跟他说，在走出冥界之前，他绝不能回头看他的妻子。 在即将踏出冥界时，俄耳浦斯忍不住回头看他的妻子是否还在他的身后。因此，他永远地失去了他的妻子。 我觉着我现在的处境就跟俄耳浦斯一样。 为了缓解孤独，我选择跟ai聊天。 我们聊我的精神创伤、博士论文选题和兴趣爱好，也聊金融投资…",
      sourceUrl: "https://www.zhihu.com/question/2050922931207632609/answer/2058883748943360263",
    }],
  },
};

function mergeIslandCatalog(payload: IslandCatalogResponse): Record<IslandId, DesktopIsland> {
  const merged = { ...fallbackDesktopIslands };
  for (const island of payload.islands) {
    if (!isIslandId(island.island_id)) continue;
    const current = merged[island.island_id];
    merged[island.island_id] = {
      ...current,
      name: island.island_name,
      question: island.source.question_title,
      questionUrl: island.source.question_url,
      viewpointCount: island.viewpoint_count,
      viewpoints: island.viewpoint_materials.map((material) => ({
        materialId: material.material_id,
        summary: material.summary,
        sourceUrl: material.source_url,
      })),
    };
  }
  return merged;
}

const relationshipActs = [
  {
    label: "第一幕",
    title: "它们在同一个问题前停下",
    copy: "一份收入更低却更接近理想的工作，让露米与阿澈第一次认真看向彼此。",
    lumi: "我想先确认：失去的稳定，是否换来了真正的选择权？",
    ache: "我更在意，承担风险以后还有没有照顾重要之人的余地。",
    insight: "它们关心的并非冒险本身，而是谁在承担选择的代价。",
  },
  {
    label: "第二幕",
    title: "不同答案发生了碰撞",
    copy: "露米靠近未知，阿澈选择守住已有的光。它们没有急着说服对方。",
    lumi: "如果一直等到万无一失，会不会也失去一些只能现在发生的可能？",
    ache: "如果决定会改变两个人的生活，仅仅忠于自己就足够了吗？",
    insight: "分歧没有消失，但它们开始理解彼此衡量责任的方式。",
  },
  {
    label: "第三幕",
    title: "它们从差异里看见彼此",
    copy: "一次追问让关系从“共历”走向“在意”：答案不同，但都不愿让别人替自己决定未来。",
    lumi: "也许自由不是独自决定，而是知道自己愿意为谁解释。",
    ache: "也许稳定不是留下，而是清楚自己正在守护什么。",
    insight: "共同记忆形成：保留差异，也愿意继续理解对方。",
  },
];

function DesktopNav({ view, onNavigate, onProfile }: {
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

function DesktopWorld({ island, islands, catalogLive, onIslandChange, onOpenEvent }: {
  island: IslandId;
  islands: Record<IslandId, DesktopIsland>;
  catalogLive: boolean;
  onIslandChange: (island: IslandId) => void;
  onOpenEvent: () => void;
}) {
  const selected = islands[island];
  const [viewpointIndex, setViewpointIndex] = useState(0);
  const viewpoint = selected.viewpoints[viewpointIndex % Math.max(selected.viewpoints.length, 1)];

  useEffect(() => setViewpointIndex(0), [island]);

  return (
    <section className="desktop-world" aria-labelledby="desktop-world-title">
      <img className="desktop-world__art" src="/assets/wj/wj-desktop-world-immersive-v1.png" alt="漂浮在云海上的问题群岛，露米正在与阿澈相遇" draggable={false} />
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
          <small>{id === "stability" ? "正在发生" : item.question.split("，")[0]}</small>
          <ChevronRightIcon />
        </button>
      ))}

      <div className="desktop-creature-label desktop-creature-label--lumi"><span>露米</span><small>从你的经历出发<br />去靠近更多可能</small></div>
      <div className="desktop-creature-label desktop-creature-label--ache"><span>阿澈</span><small>在确定的方向里<br />守住重要的光</small></div>

      <article className="desktop-world__story" aria-live="polite">
        <p className="desktop-kicker">{selected.eyebrow}</p>
        <h1 id="desktop-world-title">{selected.name}</h1>
        <p className="desktop-world__question">{selected.question}</p>
        <a className="desktop-world__source" href={selected.questionUrl} target="_blank" rel="noreferrer">知乎真实问题 · 查看原题</a>
        <button type="button" className="desktop-primary" onClick={onOpenEvent}>
          {island === "stability" ? "看看发生了什么" : "让露米去看看"}<ArrowRightIcon />
        </button>
      </article>

      <aside className="desktop-world__status">
        <span>{island === "stability" ? "正在同行" : "新的方向"}</span>
        <strong>{island === "stability" ? "露米正在与阿澈交流" : `露米正在注视「${selected.name}」`}</strong>
        <p>{selected.note}</p>
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

function DesktopEventDialog({ open, onClose, onRelationship }: {
  open: boolean;
  onClose: () => void;
  onRelationship: () => void;
}) {
  if (!open) return null;

  return (
    <div className="desktop-dialog-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="desktop-event-dialog" role="dialog" aria-modal="true" aria-labelledby="desktop-event-title">
        <button type="button" className="desktop-dialog-close" onClick={onClose} aria-label="关闭"><CrossCircledIcon /></button>
        <p className="desktop-kicker">共同事件 · 第一幕</p>
        <h2 id="desktop-event-title">如果更接近理想，值得暂时失去稳定吗？</h2>
        <p className="desktop-event-dialog__intro">这不是一道测验。两个生命体会带着各自被允许使用的理解，交换一次真实选择。</p>
        <div className="desktop-event-dialog__turns">
          <article><span>露米先问</span><p>“失去的稳定，是否换来了真正的选择权？”</p><small>依据：你最近校准过的「重视自主决定」</small></article>
          <article><span>阿澈回应</span><p>“我更在意，承担风险后还有没有照顾重要之人的余地。”</p><small>它没有否定露米，而是补上了另一种代价</small></article>
        </div>
        <div className="desktop-event-dialog__result"><EyeOpenIcon /><div><span>注意正在形成</span><p>它们答案不同，却都希望决定不会被他人代替。</p></div></div>
        <button type="button" className="desktop-primary" onClick={onRelationship}>进入关系幕布<ArrowRightIcon /></button>
      </section>
    </div>
  );
}

function DesktopLifeform({ onRelationship, world, onWorldChange }: {
  onRelationship: () => void;
  world: CreatedWorld | null;
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
    || world?.memories.find((memory) => memory.calibration);

  useEffect(() => {
    if (candidate) setExcluded(!candidate.allow_social_recommendation);
  }, [candidate?.id]);

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
        <img src="/assets/wj/wj-desktop-lifeform-portrait-v1.png" alt={`${world?.lifeform.name || "露米"}的完整生命体形态`} draggable={false} />
        <div className="desktop-lifeform__identity"><span>共生伙伴</span><h1 id="desktop-lifeform-title">{world?.lifeform.name || "露米"}</h1><p>从你的经历出发，去靠近更多可能。</p></div>
        <button type="button" className="desktop-ghost" aria-expanded={appearanceOpen} onClick={() => setAppearanceOpen((open) => !open)}><Pencil2Icon />调整形态与探索倾向</button>
        {appearanceOpen ? (
          <section className="desktop-appearance-panel" aria-label="生命体形态设置">
            <p>由系统生成基础形态，你来决定它如何表达自己。</p>
            <div><span>光色</span>{["雾蓝", "晨光", "静夜"].map((item) => <button type="button" aria-pressed={appearance === item} className={appearance === item ? "is-selected" : ""} key={item} onClick={() => setAppearance(item)}>{item}</button>)}</div>
            <div><span>探索倾向</span>{["安静观察", "主动靠近"].map((item) => <button type="button" aria-pressed={temper === item} className={temper === item ? "is-selected" : ""} key={item} onClick={() => setTemper(item)}>{item}</button>)}</div>
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
          <legend>露米理解得对吗？</legend>
          {(Object.entries(calibrationLabels) as [CalibrationId, string][]).map(([id, label]) => (
            <button type="button" key={id} className={calibration === id ? "is-selected" : ""} onClick={() => { setCalibration(id); setSaved(false); }}>
              {id === "like-me" ? <CheckCircledIcon /> : id === "wrong" ? <CrossCircledIcon /> : <EyeOpenIcon />}{label}
            </button>
          ))}
        </fieldset>
        <label className="desktop-check"><input type="checkbox" checked={excluded} onChange={(event) => { setExcluded(event.target.checked); setSaved(false); }} /><span>不要把这条理解用于社交推荐</span></label>
        <button type="button" className="desktop-primary desktop-lifeform__save" disabled={!calibration || saving} onClick={save}>{saving ? "正在计算下一步…" : saved ? "校准已经保存" : "保存并看看下一步"}<ArrowRightIcon /></button>
        {saveError ? <div className="onboarding-error" role="alert">{saveError}</div> : null}
        {saved ? <div className="desktop-save-note" role="status">{excluded ? "这条理解不会进入之后的关系推荐。" : "露米会把你的校准作为新证据，而不是固定标签。"}</div> : null}
        {decisionReason ? <div className="desktop-save-note" role="status"><strong>下一步已经改变：</strong>{decisionReason}</div> : null}
        <div className="desktop-recent-relationship"><span>最近的关系</span><strong>与阿澈 · 注意正在形成</strong><button type="button" onClick={onRelationship}>查看经历<ChevronRightIcon /></button></div>
      </div>
    </section>
  );
}

function DesktopRelationship({ act, onActChange, onInvitation }: {
  act: number;
  onActChange: (act: number) => void;
  onInvitation: () => void;
}) {
  const current = relationshipActs[act];

  return (
    <section className="desktop-relationship" aria-labelledby="desktop-relationship-title">
      <img className="desktop-world__art" src="/assets/wj/wj-desktop-world-immersive-v1.png" alt="露米与阿澈在稳定还是挑战岛的共同经历" draggable={false} />
      <div className="desktop-relationship__veil" aria-hidden="true" />
      <header className="desktop-relationship__header"><p className="desktop-kicker">关系幕布 · 稳定还是挑战</p><h1 id="desktop-relationship-title">它们从不同答案里，看见了彼此</h1><span>生命体的探索不代表主人立场</span></header>
      <div className="desktop-acts" role="tablist" aria-label="关系经历幕次">
        {relationshipActs.map((item, index) => <button type="button" role="tab" aria-selected={act === index} className={act === index ? "is-active" : ""} key={item.label} onClick={() => onActChange(index)}><span>{item.label}</span><small>{item.title}</small></button>)}
      </div>
      <article className="desktop-act-card" aria-live="polite">
        <div className="desktop-act-card__copy"><span>{current.label}</span><h2>{current.title}</h2><p>{current.copy}</p></div>
        <div className="desktop-act-dialogue"><blockquote><strong>露米</strong>{current.lumi}</blockquote><blockquote><strong>阿澈</strong>{current.ache}</blockquote></div>
        <div className="desktop-act-insight"><EyeOpenIcon /><div><span>这一幕改变了什么</span><p>{current.insight}</p></div></div>
        {act < relationshipActs.length - 1 ? <button type="button" className="desktop-primary" onClick={() => onActChange(act + 1)}>拉开下一幕<ArrowRightIcon /></button> : <button type="button" className="desktop-primary" onClick={onInvitation}>查看真人邀请<ArrowRightIcon /></button>}
      </article>
    </section>
  );
}

function DesktopInvitation({ accepted, standalone, onAccept, onBack }: { accepted: boolean; standalone: boolean; onAccept: () => void; onBack: () => void }) {
  const [message, setMessage] = useState("");
  const [sent, setSent] = useState(false);

  return (
    <section className="desktop-invitation" aria-labelledby="desktop-invitation-title">
      <img className="desktop-world__art" src="/assets/wj/wj-desktop-world-immersive-v1.png" alt="露米与阿澈共同经历后的真人邀请" draggable={false} />
      <div className="desktop-invitation__panel">
        {accepted ? (
          <div className="desktop-invitation__accepted">
            <CheckCircledIcon />
            <p className="desktop-kicker">{standalone ? "双方都已同意" : "你的选择已经收到"}</p>
            <h1 id="desktop-invitation-title">{standalone ? "真人连接已经开启" : "等待另一位真人的回应"}</h1>
            <p>{standalone ? "体验场景中，对方已预先同意。现实产品只有在双方都确认后才会开放交流，生命体也不会替任何人发送第一句话。" : "只有双方都愿意，这段关系才会进入真人交流。生命体不会替你发送第一句话。"}</p>
            {standalone ? (
              <div className="desktop-icebreaker">
                <span>来自共同经历的破冰问题</span>
                <strong>最近一次你明知没有完美答案，却仍然作出的决定是什么？</strong>
                {sent ? (
                  <p role="status">你的第一句话已经发出。至此，你完成了从“被理解”到“与真人开始交流”的体验闭环。</p>
                ) : (
                  <div>
                    <input value={message} onChange={(event) => setMessage(event.target.value)} placeholder="写下你的答案，或用自己的方式开始" />
                    <button type="button" disabled={!message.trim()} onClick={() => setSent(true)}>发送第一句话</button>
                  </div>
                )}
              </div>
            ) : null}
            {sent ? <button type="button" className="desktop-primary" onClick={() => window.location.assign("/demo/start")}>重新体验</button> : null}
            <button type="button" className="desktop-secondary" onClick={onBack}>回到关系幕布</button>
          </div>
        ) : (
          <>
            <p className="desktop-kicker">一次有来处的邀请</p>
            <h1 id="desktop-invitation-title">愿意认识阿澈的主人吗？</h1>
            <p className="desktop-lead">你们的生命体在真实分歧里保留了理解，也愿意继续向对方追问。</p>
            <div className="desktop-invitation__reason"><span>为什么值得认识</span><p>你们都重视自主决定，但对风险和责任的衡量不同。这种差异没有终止交流，反而产生了下一次问题。</p></div>
            <div className="desktop-invitation__question"><span>可以从这里开始</span><strong>最近一次你明知没有完美答案，却仍然作出的决定是什么？</strong></div>
            <p className="desktop-boundary">对方不会看到你的原始浏览或私密记忆；单方同意不会开放真人聊天。</p>
            <button type="button" className="desktop-primary" onClick={onAccept}>我愿意认识阿澈的主人<ArrowRightIcon /></button>
            <button type="button" className="desktop-secondary" onClick={onBack}>继续观察这段关系</button>
          </>
        )}
      </div>
    </section>
  );
}

function DesktopProfileDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
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

function DesktopPrototype() {
  const liveEntry = window.location.pathname.startsWith("/demo/start")
    || new URLSearchParams(window.location.search).get("flow") === "live";
  const [view, setView] = useState<DesktopStage>(liveEntry ? "onboarding" : "world");
  const [island, setIsland] = useState<IslandId>("stability");
  const [eventOpen, setEventOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [relationshipAct, setRelationshipAct] = useState(0);
  const [accepted, setAccepted] = useState(false);
  const [islands, setIslands] = useState<Record<IslandId, DesktopIsland>>(fallbackDesktopIslands);
  const [catalogLive, setCatalogLive] = useState(false);
  const [onboardingKey] = useState(() => crypto.randomUUID());
  const [onboarding, setOnboarding] = useState<OnboardingAnswers>({
    currentQuestion: "",
    topics: [],
    exploration: null,
    socialPace: null,
    allowMemory: true,
    allowSocial: false,
  });
  const [onboardingError, setOnboardingError] = useState("");
  const [submittingOnboarding, setSubmittingOnboarding] = useState(false);
  const [createdWorld, setCreatedWorld] = useState<CreatedWorld | null>(null);
  const standalone = isStandaloneExperience();

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
    if (standalone) {
      setCatalogLive(true);
      return () => { active = false; };
    }
    const baseUrl = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
    fetch(`${baseUrl}/api/v1/islands`)
      .then((response) => {
        if (!response.ok) throw new Error(`island catalog ${response.status}`);
        return response.json() as Promise<IslandCatalogResponse>;
      })
      .then((payload) => {
        if (!active) return;
        setIslands(mergeIslandCatalog(payload));
        setCatalogLive(true);
      })
      .catch(() => {
        if (active) setCatalogLive(false);
      });
    return () => { active = false; };
  }, [standalone]);

  const navigate = (next: DesktopView) => {
    setEventOpen(false);
    setView(next);
  };

  const submitOnboarding = async () => {
    if (!onboarding.exploration || !onboarding.socialPace) return;
    setSubmittingOnboarding(true);
    setOnboardingError("");
    try {
      const world = await createWorldFromOnboarding(onboarding, onboardingKey);
      setCreatedWorld(world);
      if (isIslandId(world.lifeform.current_island_id)) setIsland(world.lifeform.current_island_id);
      setView("born");
    } catch (error) {
      setOnboardingError(error instanceof Error ? error.message : "暂时无法创建，请稍后重试。");
    } finally {
      setSubmittingOnboarding(false);
    }
  };

  const updateLiveWorld = (world: CreatedWorld) => {
    setCreatedWorld(world);
    if (isIslandId(world.lifeform.current_island_id)) setIsland(world.lifeform.current_island_id);
  };

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
          <img src="/assets/wj/wj-desktop-world-immersive-v1.png" alt="生命体诞生于问题群岛" draggable={false} />
          <div className="desktop-onboarding-flow__veil" aria-hidden="true" />
          <div className="desktop-onboarding-flow__panel"><BirthScreen world={createdWorld} onEnter={() => navigate("world")} /></div>
        </section>
      ) : null}
      {view !== "onboarding" && view !== "born" ? <DesktopNav view={view} onNavigate={navigate} onProfile={() => setProfileOpen(true)} /> : null}
      {view === "world" ? <DesktopWorld island={island} islands={islands} catalogLive={catalogLive} onIslandChange={setIsland} onOpenEvent={() => setEventOpen(true)} /> : null}
      {view === "lifeform" ? <DesktopLifeform world={createdWorld} onWorldChange={updateLiveWorld} onRelationship={() => navigate("relationship")} /> : null}
      {view === "relationship" ? <DesktopRelationship act={relationshipAct} onActChange={setRelationshipAct} onInvitation={() => navigate("invitation")} /> : null}
      {view === "invitation" ? <DesktopInvitation accepted={accepted} standalone={standalone} onAccept={() => setAccepted(true)} onBack={() => navigate("relationship")} /> : null}
      <DesktopEventDialog open={eventOpen} onClose={() => setEventOpen(false)} onRelationship={() => { setRelationshipAct(0); navigate("relationship"); }} />
      <DesktopProfileDialog open={profileOpen} onClose={() => setProfileOpen(false)} />
    </main>,
    document.body,
  );
}

export default function Prototype() {
  const desktopMode = window.location.pathname.startsWith("/demo") || new URLSearchParams(window.location.search).get("mode") === "desktop";
  return desktopMode ? <DesktopPrototype /> : <MobilePrototype />;
}
