import { api } from "./client";
import type { Model, ModelStatus, RiskLevel } from "../types";

export interface ModelFilters {
  provider?: string;
  risk_level?: RiskLevel;
  status?: ModelStatus;
  page?: number;
  limit?: number;
}

export interface PaginatedModels {
  items: Model[];
  total: number;
  page: number;
  pages: number;
}

export interface ModelCreate {
  name: string;
  provider: string;
  model_version: string;
  use_case?: string;
  owner_team?: string;
  owner_email?: string;
  deployment_date?: string;
  risk_level?: RiskLevel;
  status?: ModelStatus;
  description?: string;
}

export type ModelUpdate = Partial<ModelCreate>;

export async function getModels(filters: ModelFilters = {}): Promise<Model[]> {
  // Convenience: callers that don't care about pagination get a flat array
  // of the first page. Use getModelsPaged for the full envelope.
  const { data } = await api.get<PaginatedModels>("/models/", {
    params: { limit: 500, ...filters },
  });
  return data.items;
}

export async function getModelsPaged(
  filters: ModelFilters = {}
): Promise<PaginatedModels> {
  const { data } = await api.get<PaginatedModels>("/models/", { params: filters });
  return data;
}

export async function getModel(id: string): Promise<Model> {
  const { data } = await api.get<Model>(`/models/${id}`);
  return data;
}

export async function createModel(payload: ModelCreate): Promise<Model> {
  const { data } = await api.post<Model>("/models/", payload);
  return data;
}

export async function updateModel(id: string, payload: ModelUpdate): Promise<Model> {
  const { data } = await api.patch<Model>(`/models/${id}`, payload);
  return data;
}

export async function archiveModel(id: string): Promise<Model> {
  return updateModel(id, { status: "Archived" });
}
