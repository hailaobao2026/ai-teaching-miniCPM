export type UserRole = 'admin' | 'teacher' | 'student';
export type UserStatus = 'active' | 'disabled';
export type AppView = 'workspace' | 'history' | 'admin' | 'notebook';
export type AuthMode = 'login' | 'register';
export type LessonStage = 'confirm' | 'hint' | 'explain';
export type SubjectCode = 'chinese' | 'math' | 'english' | 'physics' | 'chemistry' | 'politics' | 'history' | 'geography' | 'biology';

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
  user: User;
  cookie_auth: boolean;
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
  demo_accounts?: Array<{ id: string; label: string; email: string }>;
  cookie_auth?: boolean;
  subjects?: SubjectInfo[];
}

export interface SubjectInfo {
  code: SubjectCode;
  name: string;
  icon: string;
  focus: string;
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
  subject?: SubjectCode | string;
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

export interface SpeechResponse {
  audio_base64: string;
  audio_mime: string;
  source: 'minicpm';
}

export interface ExampleItem {
  id: string;
  subject?: SubjectCode;
  title: string;
  problem: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
  created_at: string;
  input_type: 'text' | 'voice';
  audio_url?: string;
  audio_duration_seconds?: number;
}

export interface SavedLesson {
  id: string;
  subject?: SubjectCode;
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
  subject?: SubjectCode | string;
  problem: string;
  problems?: RecognizedProblem[];
  selected_problem_id?: string | null;
  annotations?: Annotation[];
  confidence?: number;
  source?: string;
  session_id?: string | null;
  degraded?: boolean;
  degraded_reason?: string | null;
  no_problems?: boolean;
  message?: string | null;
}

export interface RecognizedProblem {
  id: string;
  problem: string;
  annotations?: Annotation[];
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

export interface NotebookItem {
  id: string;
  problem: string;
  topic: string;
  topic_label: string;
  helpful: boolean;
  note: string;
  stage?: string | null;
  final_answer?: string | null;
  reply?: string | null;
  created_at: string;
  attempt_count: number;
  correct_count: number;
  latest_attempt?: string | null;
  latest_correct?: boolean;
  consecutive_wrong?: number;
}

export interface NotebookStats {
  total: number;
  wrong: number;
  mastered: number;
}

export interface NotebookListResponse {
  items: NotebookItem[];
  stats: NotebookStats;
}

export interface NotebookAttempt {
  id: string;
  notebook_item_id: string;
  attempt_number: number;
  answer: string;
  correct: boolean;
  hint_level: number;
  created_at: string;
}

export interface RetryHint {
  level: number;
  title: string;
  body: string;
}

export interface NotebookAttemptResponse {
  correct: boolean;
  attempt: NotebookAttempt;
  item: NotebookItem;
  hint: RetryHint;
  final_answer: string | null;
  can_mark_mastered: boolean;
}

export interface PracticeItem {
  id: string;
  title: string;
  problem: string;
  topic: string;
  topic_label: string;
  reason: string;
}

export interface PracticeRecommendResponse {
  topic: string;
  topic_label: string;
  items: PracticeItem[];
}
