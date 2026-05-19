import { api } from "./client";
import type { PaginatedLogs } from "../types";

export interface LogFilters {
  model_id?: string;
  status?: string;
  flagged?: boolean;
  date_from?: string;
  date_to?: string;
  page?: number;
  limit?: number;
}

export async function getLogs(filters: LogFilters = {}): Promise<PaginatedLogs> {
  const { data } = await api.get<PaginatedLogs>("/logs/", { params: filters });
  return data;
}

export async function exportCsv(
  filters: Omit<LogFilters, "page" | "limit"> = {}
): Promise<Blob> {
  const { data } = await api.get<Blob>("/logs/export/csv", {
    params: filters,
    responseType: "blob",
  });
  return data;
}
