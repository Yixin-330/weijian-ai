import { useState } from "react";
import { worldArtworkSrc } from "../../shared/assets/artwork";
import { CheckCircledIcon, ArrowRightIcon } from "@radix-ui/react-icons";

export function DesktopInvitation({ accepted, standalone, actorAppearance, companionName, sharedMemory, returnQuestion, onAccept, onBack }: { accepted: boolean; standalone: boolean; actorAppearance?: string; companionName: string; sharedMemory?: string; returnQuestion?: string; onAccept: () => void; onBack: () => void }) {
  const [message, setMessage] = useState("");
  const [sent, setSent] = useState(false);

  return (
    <section className="desktop-invitation" aria-labelledby="desktop-invitation-title">
      <img className="desktop-world__art" src={worldArtworkSrc(actorAppearance)} alt={`与${companionName}共同经历后的真人邀请`} draggable={false} />
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
                <strong>{returnQuestion || "最近一次你明知没有完美答案，却仍然作出的决定是什么？"}</strong>
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
            <h1 id="desktop-invitation-title">愿意认识{companionName}的主人吗？</h1>
            <p className="desktop-lead">你们的生命体在真实分歧里保留了理解，也愿意继续向对方追问。</p>
            <div className="desktop-invitation__reason"><span>为什么值得认识</span><p>{sharedMemory || "你们都重视自主决定，但对风险和责任的衡量不同。这种差异没有终止交流，反而产生了下一次问题。"}</p></div>
            <div className="desktop-invitation__question"><span>可以从这里开始</span><strong>{returnQuestion || "最近一次你明知没有完美答案，却仍然作出的决定是什么？"}</strong></div>
            <p className="desktop-boundary">对方不会看到你的原始浏览或私密记忆；单方同意不会开放真人聊天。</p>
            <button type="button" className="desktop-primary" onClick={onAccept}>我愿意认识{companionName}的主人<ArrowRightIcon /></button>
            <button type="button" className="desktop-secondary" onClick={onBack}>继续观察这段关系</button>
          </>
        )}
      </div>
    </section>
  );
}
