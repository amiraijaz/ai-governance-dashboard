import { api } from "./client";

export type FlagSeverity = "GREEN" | "YELLOW" | "RED";
export type ReviewStatus = "safe" | "issue_found" | "escalated";

export interface SafetyFlagItem {
  id: string;
  log_id: string;
  model_id: string;
  model_name: string | null;
  timestamp: string;
  flag_type: string;
  severity: FlagSeverity;
  confidence: number;
  details: Record<string, unknown> | null;
  reviewed: boolean;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_status: ReviewStatus | null;
  review_notes: string | null;
}

export interface FlagDetail extends SafetyFlagItem {
  prompt_hash: string | null;
  log_metadata: Record<string, unknown> | null;
}

export interface PaginatedFlags {
  items: SafetyFlagItem[];
  page: number;
  limit: number;
  total: number;
}

export interface FlagStats {
  total: number;
  open: number;
  green: number;
  yellow: number;
  red: number;
  reviewed_today: number;
}

export interface FlagFilters {
  severity?: FlagSeverity;
  reviewed?: boolean;
  model_id?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  limit?: number;
}

export interface FlagReviewRequest {
  review_status: ReviewStatus;
  review_notes?: string;
}

export async function getFlags(filters: FlagFilters = {}): Promise<PaginatedFlags> {
  const { data } = await api.get<PaginatedFlags>("/flags/", { params: filters });
  return data;
}

export async function getFlag(id: string): Promise<FlagDetail> {
  const { data } = await api.get<FlagDetail>(`/flags/${id}`);
  return data;
}

export async function getFlagStats(): Promise<FlagStats> {
  const { data } = await api.get<FlagStats>("/flags/stats");
  return data;
}

export async function reviewFlag(
  id: string,
  payload: FlagReviewRequest
): Promise<SafetyFlagItem> {
  const { data } = await api.put<SafetyFlagItem>(`/flags/${id}/review`, payload);
  return data;
}
