export type UserRole = "admin" | "reviewer" | "member";
export type ProjectRole = "owner" | "editor" | "viewer";

export interface User {
  id: string;
  email: string;
  display_name: string;
  locale: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  settings: Record<string, unknown>;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  my_role: ProjectRole | null;
  member_count: number;
}

export interface Member {
  id: string;
  user_id: string;
  email: string;
  display_name: string;
  role: ProjectRole;
  created_at: string;
}

export interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  project_id: string | null;
  user_id: string | null;
  device_id: string | null;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
  key?: string;
}

export interface Device {
  id: string;
  name: string;
  os: string | null;
  agent_targets: string[];
  cli_version: string | null;
  last_seen_at: string | null;
  created_at: string;
}

export interface Notification {
  id: string;
  kind: string;
  title: string;
  body: string | null;
  subject_type: string | null;
  subject_id: string | null;
  payload: Record<string, unknown>;
  read_at: string | null;
  created_at: string;
}

export interface Page<T> {
  items: T[];
  total: number;
}

export interface AdminStats {
  users: number;
  projects: number;
  devices: number;
  jobs_running: number;
}

export interface AuditEntry {
  id: string;
  actor_user_id: string | null;
  project_id: string | null;
  action: string;
  subject_type: string | null;
  subject_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  created_at: string;
}

export interface Job {
  id: string;
  type: string;
  status: string;
  progress: number;
  message: string | null;
  error: string | null;
  project_id: string | null;
  user_id: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown> };
}

export interface Skill {
  id: string;
  project_id: string;
  name: string;
  title: string;
  summary: string | null;
  visibility: "private" | "shared" | "public";
  development_state: "active" | "suspended" | "archived";
  suspend_note: string | null;
  current_published_version_id: string | null;
  latest_version_id: string | null;
  tags: string[];
  category_id?: string | null;
  install_count?: number;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  latest_interview_state: string | null;
  latest_interview_id: string | null;
}

export interface PendingQuestion {
  question: string;
  why: string;
  expects: "text" | "choice" | "yes_no" | "file" | "confirmation";
  options: string[];
  target_gate: string;
}

export interface InterviewSession {
  id: string;
  project_id: string;
  skill_id: string;
  user_id: string;
  state: string;
  language: string;
  turn_count: number;
  token_usage: { input_tokens?: number; output_tokens?: number };
  pending_question: PendingQuestion | null;
  error: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface InterviewMessage {
  id: string;
  ordinal: number;
  role: "user" | "assistant" | "system";
  content: string;
  attachments: unknown[];
  meta: Record<string, unknown>;
  created_at: string;
}

export interface GateResult {
  id: string;
  title: string;
  passed: boolean;
  detail: string;
}

export interface KnowledgeStep {
  key: string;
  title: string;
  description: string;
  kind_hint: "deterministic" | "generative" | "human_gate";
  uses: string[];
  decision_rules: string[];
  example: string;
  side_effects: "read_only" | "reversible" | "irreversible" | "unknown";
  restore_strategy: string;
  unclear: boolean;
}

export interface KnowledgeDocBody {
  task: { name: string; goal: string; trigger: string; actor_role: string };
  data_sources: { ref: string; kind: string; role: string; access: string; fields_used: string[]; sensitivity: string }[];
  inputs: { name: string; description: string; example: string }[];
  outputs: { name: string; description: string; example: string }[];
  steps: KnowledgeStep[];
  edge_cases: { condition: string; expected_handling: string; source_ref: string | null; confirmed: boolean }[];
  acceptance_criteria: { id: string; statement: string; checkable_by: string }[];
  integrations: { system: string; purpose: string; protocol: string; credentials_needed: string[]; authorizations: string; contact: string }[];
  constraints: { tools_available: string[]; forbidden_actions: string[]; secrets_needed: string[]; pii: boolean };
  open_questions: string[];
  glossary: { name: string; description: string; example: string }[];
  human_confirmed: boolean;
}

export interface KnowledgeDoc {
  id: string;
  revision: number;
  doc: KnowledgeDocBody;
  completeness: { gates: GateResult[]; passed: number; total: number };
  frozen: boolean;
  created_at: string;
}

export interface InterviewDetail {
  session: InterviewSession;
  messages: InterviewMessage[];
  knowledge: KnowledgeDoc | null;
  procedure_state: string | null;
  waiting_for: string | null;
  current_step: string | null;
  supervisor: { decision: string; effective: string; reasons: string[]; missing: string[]; failing_gate: string | null } | null;
}

export interface MemoryEntry {
  id: string;
  skill_id: string;
  kind: string;
  title: string;
  body: string;
  structured: Record<string, unknown>;
  step_key: string | null;
  source: string;
  source_ref: string | null;
  skill_version_id: string | null;
  author_user_id: string | null;
  status: string;
  superseded_by_id: string | null;
  tags: string[];
  created_at: string;
}

export interface DataSource {
  id: string;
  project_id: string;
  name: string;
  kind: string;
  description: string | null;
  access_notes: string | null;
  schema_def: Record<string, unknown>;
  sample_refs: unknown[];
  sensitivity: string;
  created_at: string;
  updated_at: string;
}

export interface Provider {
  id: string;
  scope: "system" | "project";
  project_id: string | null;
  name: string;
  adapter: string;
  base_url: string | null;
  model: string;
  models: string[];
  purposes: string[];
  extra: Record<string, unknown>;
  is_default: boolean;
  is_enabled: boolean;
  has_api_key: boolean;
  health: { ok?: boolean; message?: string; latency_ms?: number };
  created_at: string;
}

export interface ProviderTestResult {
  ok: boolean;
  message: string;
  latency_ms: number | null;
  models: string[];
  capabilities: Record<string, boolean>;
}

export interface StepDefinition {
  id: string;
  ordinal: number;
  key: string;
  title: string;
  instruction: string;
  kind: "deterministic" | "generative" | "human_gate";
  side_effects: "read_only" | "reversible" | "irreversible" | "unknown";
  restore_strategy: string;
  trial_mode: "real" | "simulate" | "sandbox_copy";
  requires_explicit_auth: boolean;
  inputs: string[];
  outputs: string[];
  data_source_refs: string[];
  success_criteria: string | null;
  failure_modes: string[];
  network: boolean;
  mcp_tool_name: string | null;
  library_component_slug: string | null;
  test_status: string;
  confirmations_count: number;
}

export interface SkillVersion {
  id: string;
  skill_id: string;
  version: string;
  state: string;
  parent_version_id: string | null;
  origin: string;
  manifest: { files: { path: string; hash: string; size: number }[]; total_size?: number };
  frontmatter: Record<string, unknown>;
  changelog: string | null;
  rationale: string | null;
  validation_report: { ok: boolean; issues: { level: string; code: string; message: string; path: string | null }[] };
  signature: string | null;
  created_by: string | null;
  is_current_draft: boolean;
  state_changed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SkillVersionDetail extends SkillVersion {
  steps: StepDefinition[];
  dependencies: { component_slug: string; reason: string | null; version_constraint: string | null }[];
  build_log: string | null;
}

export interface TargetInfo {
  id: string;
  display_name: string;
  global_skill_dir: string;
  workspace_skill_dir: string | null;
  mcp_config_path: string;
  mcp_config_format: string;
  supports_git_install: boolean;
  verified_on: string;
  docs_url: string;
}

export interface LibraryComponent {
  id: string;
  kind: "skill" | "mcp_server";
  slug: string;
  name: string;
  description: string;
  version: string;
  source: Record<string, unknown>;
  tools: { name: string; description?: string; side_effects?: string }[];
  env_requirements: { name: string; description?: string; secret?: boolean }[];
  install: Record<string, unknown>;
  docs: string | null;
  tags: string[];
  is_enabled: boolean;
  added_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface Trial {
  id: string;
  user_id: string;
  project_id: string;
  device_id: string | null;
  skill_id: string;
  skill_version_id: string;
  purpose: "develop" | "retest" | "hub_evaluate";
  target_agent: string;
  mode: "interactive" | "async";
  state: string;
  build: number;
  current_step_key: string | null;
  current_iteration: number;
  corrections: { step_key: string; iteration: number; text: string; at: string }[];
  outcome: string | null;
  summary: string | null;
  keep_installed: boolean | null;
  started_at: string | null;
  suspended_at: string | null;
  ended_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TrialCreated extends Trial {
  session_token: string;
  cli_command: string;
  package_url: string;
}

export interface Checkpoint {
  id: string;
  run_id: string;
  trial_session_id: string | null;
  step_key: string;
  phase: "explain" | "preview" | "execute" | "verify";
  iteration: number;
  execution_mode: string;
  state: "pending" | "decided" | "expired";
  proposal: Record<string, unknown>;
  decision: string | null;
  correction_text: string | null;
  updated_instructions: string | null;
  decided_by: string | null;
  decided_at: string | null;
  expires_at: string;
  created_at: string;
}

export interface Run {
  id: string;
  project_id: string;
  skill_id: string;
  skill_version_id: string | null;
  skill_version: string | null;
  trial_session_id: string | null;
  source: string;
  agent_target: string | null;
  status: string;
  inputs_summary: string | null;
  summary: string | null;
  error: Record<string, unknown> | null;
  llm_usage: Record<string, number>;
  human_feedback: string | null;
  is_golden: boolean;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
}

export interface RunStep {
  id: string;
  ordinal: number;
  step_key: string;
  title: string | null;
  status: string;
  iteration: number;
  execution_mode: string | null;
  proposed_action: unknown;
  executed_action: unknown;
  inputs: unknown;
  outputs: unknown;
  error: unknown;
  tool_name: string | null;
  duration_ms: number | null;
  created_at: string;
}

export interface TrialDetail {
  trial: Trial;
  skill_name: string;
  skill_title: string;
  version: string;
  steps: StepDefinition[];
  runs: Run[];
  pending_checkpoint: Checkpoint | null;
  checkpoints: Checkpoint[];
  package_url: string;
}

export interface Discussion {
  id: string;
  skill_id: string;
  skill_version_id: string;
  trial_session_id: string | null;
  checkpoint_id: string | null;
  step_key: string;
  state: string;
  outcome: Record<string, unknown> | null;
  messages: { role: string; content: string; at: string; proposal?: { new_instruction?: string | null; change_summary?: string | null; memory_entries?: { kind: string; title: string; body: string }[] } | null }[];
  created_at: string;
}

export interface ReviewRequest {
  id: string;
  skill_version_id: string;
  skill_id: string;
  project_id: string;
  requested_by: string;
  state: string;
  assignee_id: string | null;
  summary: string | null;
  checklist: Record<string, unknown>;
  priority: string;
  decided_at: string | null;
  created_at: string;
  updated_at: string;
  skill_title?: string;
  skill_name?: string;
  version?: string;
  requested_by_name?: string;
}

export interface ReviewDecision {
  id: string;
  review_request_id: string;
  reviewer_id: string;
  decision: string;
  comment: string | null;
  file_comments: { path: string; line?: number; text: string }[];
  created_at: string;
}

export interface VersionDiff {
  from: string | null;
  to: string;
  files: { path: string; status: string; diff: string | null }[];
  steps: { added: string[]; removed: string[]; changed: string[]; reordered: string[] };
  suggested_bump: string;
}

export interface ReviewBundle {
  request: ReviewRequest;
  skill_title: string;
  skill_name: string;
  version: string;
  version_id: string;
  previous_version: string | null;
  diff: VersionDiff;
  files: { path: string; size: number }[];
  decisions: ReviewDecision[];
  memory_count: number;
}

export interface VersionTransition {
  id: string;
  from_state: string;
  to_state: string;
  actor_user_id: string | null;
  reason: string | null;
  created_at: string;
}

export interface HubSkill extends Skill {
  published_version: string | null;
  published_version_id: string | null;
  category_slug: string | null;
  is_favorite: boolean;
  project_slug: string;
  is_featured: boolean;
  published_at: string | null;
  install_count: number;
}

export interface Category {
  id: string;
  slug: string;
  name: Record<string, string>;
  description: string | null;
  ordinal: number;
  count: number;
}

export interface HubHome {
  featured: HubSkill[];
  latest: HubSkill[];
  most_installed: HubSkill[];
  categories: Category[];
  public: boolean;
}

export interface HubSkillDetail {
  skill: HubSkill;
  readme: string;
  versions: { id: string; version: string; state: string; changelog: string | null; created_at: string }[];
  install_targets: TargetInfo[];
  dependencies: { component_slug: string; reason: string | null }[];
  memory_public: { kind: string; title: string; body: string }[];
  git_url: string | null;
  zip_url: string | null;
  my_installation: Installation | null;
}

export interface Installation {
  id: string;
  device_id: string | null;
  skill_id: string;
  skill_version_id: string;
  target_agent: string;
  channel: string;
  kind: string;
  state: string;
  installed_at: string | null;
  confirmed_at: string | null;
  last_run_at: string | null;
  run_count: number;
  created_at: string;
  updated_at: string;
  skill_title: string;
  skill_name: string;
  installed_version: string;
  latest_version: string | null;
  latest_version_id: string | null;
  update_available: boolean;
}
