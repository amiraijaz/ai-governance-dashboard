export type RiskLevel = "Low" | "Medium" | "High" | "Critical";
export type ModelStatus = "Active" | "Paused" | "Archived";
export type FlagSeverity = "GREEN" | "YELLOW" | "RED";
export type Period = "7d" | "30d" | "90d";

export interface Model {
  id: string;
  name: string;
  provider: string;
  model_version: string;
  use_case: string | null;
  owner_team: string | null;
  owner_email: string | null;
  deployment_date: string | null;
  risk_level: RiskLevel;
  status: ModelStatus;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface AuditLog {
  id: string;
  model_id: string;
  timestamp: string;
  prompt_hash: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_cost_usd: number;
  latency_ms: number;
  user_id: string | null;
  session_id: string | null;
  status: string;
  flagged: boolean;
  flag_severity: FlagSeverity | null;
  metadata: Record<string, unknown> | null;
}

export interface PaginatedLogs {
  items: AuditLog[];
  page: number;
  limit: number;
  total: number;
}

export interface SafetyFlag {
  id: string;
  log_id: string;
  model_id: string;
  timestamp: string;
  flag_type: string;
  severity: FlagSeverity;
  confidence: number;
  details: Record<string, unknown> | null;
  reviewed: boolean;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_status: string | null;
  review_notes: string | null;
}

export interface AnalyticsCost {
  label: string;
  total_cost_usd: number;
  request_count: number;
}

export interface AnalyticsRequests {
  date: string;
  count: number;
  success_count: number;
  error_count: number;
  flagged_count: number;
}

export interface AnalyticsLatency {
  date: string;
  avg_latency_ms: number;
  p95_latency_ms: number;
  p99_latency_ms: number;
}

export interface AnalyticsModel {
  model_name: string;
  provider: string;
  total_calls: number;
  total_cost_usd: number;
  avg_latency_ms: number;
  total_tokens: number;
}

export interface MetricDelta {
  current: number;
  previous: number;
  pct_change: number | null;
}

export interface RiskBreakdown {
  low: number;
  medium: number;
  high: number;
  critical: number;
  added_this_month: number;
}

export interface CostDriver {
  name: string;
  cost: number;
  share_pct: number;
}

export interface SeverityBreakdown {
  red: number;
  yellow: number;
  green: number;
}

export interface DashboardSummary {
  models_registered: number;
  calls_this_month: number;
  cost_this_month: number;
  open_flags: number;
  cost_last_30_days: { date: string; cost: number }[];
  top_models: { name: string; calls: number }[];
  models_by_risk: RiskBreakdown;
  top_cost_models: CostDriver[];
  open_flags_by_severity: SeverityBreakdown;
  calls_delta: MetricDelta;
  cost_delta: MetricDelta;
  flags_delta: MetricDelta;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface UserProfile {
  id: string;
  email: string;
  role: string;
  organisation: string | null;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Eval framework
// ---------------------------------------------------------------------------

export type EvalType = "rag" | "llm_judge" | "drift";
export type RunStatus = "pending" | "running" | "complete" | "failed";

export interface EvalSuite {
  id: string;
  name: string;
  description: string | null;
  eval_type: EvalType;
  config: Record<string, any> | null;
  model_id: string | null;
  owner_email: string | null;
  created_at: string;
  updated_at: string;
}

export interface EvalSuiteDetail extends EvalSuite {
  recent_runs: EvalRun[];
}

export interface EvalRun {
  id: string;
  suite_id: string;
  status: RunStatus;
  started_at: string | null;
  completed_at: string | null;
  summary: Record<string, any> | null;
  error_message: string | null;
  triggered_by: string | null;
  created_at: string;
}

export interface EvalRunCreated {
  run_id: string;
  status: RunStatus;
  message: string;
}

export interface EvalResult {
  id: string;
  run_id: string;
  log_id: string | null;
  case_input: string | null;
  case_output: string | null;
  scores: Record<string, any> | null;
  passed: boolean;
  details: Record<string, any> | null;
  created_at: string;
}

export interface PaginatedEvalResults {
  items: EvalResult[];
  page: number;
  limit: number;
  total: number;
}

export interface EvalSuiteCreate {
  name: string;
  description?: string | null;
  eval_type: EvalType;
  config: Record<string, any>;
  model_id?: string | null;
}

export type EvalSuiteUpdate = Partial<Omit<EvalSuiteCreate, "eval_type">>;

export interface EvalRunTrigger {
  cases?: Record<string, any>[];
}
