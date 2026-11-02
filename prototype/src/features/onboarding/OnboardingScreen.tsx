import { type OnboardingAnswers, type TopicId, type CreatedWorld } from "../../shared/api/types";
import { KeyboardTextarea } from "../../mobile";
import { topicOptions, explorationOptions, socialPaceOptions, islandLabels } from "../../shared/config/options";
import { ArrowRightIcon } from "@radix-ui/react-icons";

export function OnboardingScreen({ answers, onChange, submitting, error, onSubmit }: {
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

export function BirthScreen({ world, onEnter }: { world: CreatedWorld; onEnter: () => void }) {
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
