import { type ArtworkScreenId, type IslandId, type DesktopIsland } from "../shared/api/types";

export const screens: Record<ArtworkScreenId, { src: string; alt: string }> = {
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

export const fallbackDesktopIslands: Record<IslandId, DesktopIsland> = {
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

export const relationshipActs = [
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
