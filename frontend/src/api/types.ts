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
