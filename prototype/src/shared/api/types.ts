

export type ScreenId = "create" | "born" | "world" | "lifeform" | "event" | "relationship" | "connection" | "icebreaker";

export type ArtworkScreenId = Exclude<ScreenId, "create" | "born">;

export type SheetId = "evidence" | "memory" | "respond" | "saved" | "response-saved" | "profile" | "intro" | "chat" | null;

export type CalibrationId = "like-me" | "recent" | "opposing" | "wrong";

export type TopicId = "choice_uncertainty" | "intimacy_and_autonomy" | "ai_and_loneliness";

export type ExplorationId = "observe" | "inquire" | "act";

export type SocialPaceId = "observe_first" | "shared_experiences" | "open_to_connection";

export type CreatedWorld = {
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
    status: "candidate" | "confirmed" | "rejected" | "superseded" | "deleted";
    version?: number;
    topic_code?: string;
    confidence: number;
    evidence_ids: string[];
    allow_social_recommendation: boolean;
    calibration?: "like_me" | "recent" | "opposes" | "wrong" | null;
  }>;
  relationships?: RelationshipPayload[];
  latest_tick?: {
    id?: string;
    selected_island_id: string;
    decision_reason: string;
    matching_status?: "waiting" | "matched" | "paused" | "cooldown" | "failed";
    match_reason?: string;
    encounter_id?: string | null;
  } | null;
  source_mode?: "precomputed" | "live";
};

export type LifeformPayload = CreatedWorld["lifeform"];

export type EncounterTurn = {
  id: string;
  turn_number: number;
  actor_lifeform_id: string;
  action: "approach" | "observe" | "respond" | "cooperate" | "avoid" | "leave";
  public_utterance: string;
  reason_summary: string;
};

export type EncounterPayload = {
  id: string;
  world_tick_id: string;
  island_id: string;
  fixture_version: string;
  event_id: string;
  title: string;
  dilemma: string;
  lifeform_ids: [string, string];
  status: "completed" | "left";
  turns: EncounterTurn[];
  outcome_summary: string;
  relationship_id: string;
  shared_memory: string;
  return_question: string;
  source_mode: "fixture";
  match_reason?: string;
  companion_is_demo?: boolean;
};

export type RelationshipStatus = "active" | "ended" | "blocked";

export type RelationshipPayload = {
  id: string;
  lifeform_ids: [string, string];
  status: RelationshipStatus;
  island_id: string;
  headline: string;
  shared_experiences: string[];
  encounter_count: number;
  source_mode: "precomputed" | "live" | "fallback";
};

export type LiveEncounterResult = {
  world: CreatedWorld;
  encounter: EncounterPayload | null;
  relationship: RelationshipPayload | null;
  companion: LifeformPayload | null;
};

export type OnboardingAnswers = {
  currentQuestion: string;
  topics: TopicId[];
  exploration: ExplorationId | null;
  socialPace: SocialPaceId | null;
  allowMemory: boolean;
  allowSocial: boolean;
};

export type CalibrationResult = { world: CreatedWorld; decisionReason: string };

export type DesktopView = "world" | "lifeform" | "relationship" | "invitation";

export type DesktopStage = "onboarding" | "born" | DesktopView;

export type IslandId = "stability" | "intimacy" | "ai_loneliness";

export type IslandViewpoint = { materialId: string; summary: string; sourceUrl: string };

export type DesktopIsland = {
  name: string;
  eyebrow: string;
  question: string;
  questionUrl: string;
  note: string;
  position: string;
  viewpointCount: number;
  viewpoints: IslandViewpoint[];
};

export type IslandCatalogResponse = {
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

export type ExplorationPayload = {
  state: { enabled: boolean; allow_cross_island: boolean; allow_demo_partners: boolean;
    is_demo: boolean; social_pace: "observe_first" | "shared_experiences" | "open_to_connection";
    excluded_topics: TopicId[]; available_at: string };
  status: "waiting" | "paused" | "cooldown";
  last_match_reason: string;
  last_encounter_id: string | null;
  last_encounter_is_demo: boolean;
  authorized_topics: string[];
};
