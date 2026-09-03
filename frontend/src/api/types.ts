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
