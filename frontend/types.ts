export type UserRole = 'admin' | 'teacher' | 'student';
export type UserStatus = 'active' | 'disabled';
export type AppView = 'workspace' | 'history' | 'admin';
export type AuthMode = 'login' | 'register';
export type LessonStage = 'confirm' | 'hint' | 'explain';

export interface User {
  id: string;
  email: string;
  nickname: string;
  role: UserRole;
  status: UserStatus;
  grade?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface AuthResponse {
  token: string;
  user: User;
}

export interface AppConfig {
  mode: 'minicpm' | 'mock' | string;
  model: string;
  gateway_url: string;
  provider: string;
  mvp_mode: string;
  auth_required: boolean;
  roles: string[];
  grades: Array<{ code: string; name: string }>;
  demo_accounts: Array<{ id: string; label: string; email: string }>;
}

export interface Annotation {
  x: number;
  y: number;
  width: number;
  height: number;
  label?: string;
}

export interface LessonStep {
  title: string;
  body: string;
  state?: 'open' | 'locked' | string;
}

export interface LessonResponse {
  session_id?: string;
  reply: string;
  steps?: LessonStep[];
  final_answer?: string | null;
  next_question?: string | null;
  confidence?: number;
  source?: string;
  stage?: LessonStage | string;
  audio_base64?: string | null;
  audio_mime?: string | null;
  annotations?: Annotation[];
}

export interface ExampleItem {
  id: string;
  title: string;
  problem: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
}

export interface SavedLesson {
  id: string;
  problem: string;
  reply: string;
  final_answer?: string | null;
  saved_at: string;
}

export interface AdminStats {
  users_total: number;
  users_active: number;
  users_by_role?: Partial<Record<UserRole, number>>;
  sessions_total?: number;
  mode?: string;
  upstream_configured?: boolean;
}

export interface AdminUser extends User {
  last_login_at?: string | null;
}

export interface RecognizeResponse {
  problem: string;
  annotations?: Annotation[];
  confidence?: number;
  source?: string;
}

export interface StreamEvent {
  type: string;
  session_id?: string;
  text?: string;
  delta?: string;
  lesson?: LessonResponse;
  source?: string;
  error?: string;
  [key: string]: unknown;
}
