import { api } from "./client";
import type {
  EvalRun,
  EvalRunCreated,
  EvalRunTrigger,
  EvalSuite,
  EvalSuiteCreate,
  EvalSuiteDetail,
  EvalSuiteUpdate,
  EvalType,
  PaginatedEvalResults,
  RunStatus,
} from "../types";

export async function getSuites(filters?: {
  eval_type?: EvalType;
  model_id?: string;
}): Promise<EvalSuite[]> {
  const { data } = await api.get<EvalSuite[]>("/evals/suites", {
    params: filters,
  });
  return data;
}

export async function getSuite(id: string): Promise<EvalSuiteDetail> {
  const { data } = await api.get<EvalSuiteDetail>(`/evals/suites/${id}`);
  return data;
}

export async function createSuite(payload: EvalSuiteCreate): Promise<EvalSuite> {
  const { data } = await api.post<EvalSuite>("/evals/suites", payload);
  return data;
}

export async function updateSuite(
  id: string,
  payload: EvalSuiteUpdate,
): Promise<EvalSuite> {
  const { data } = await api.put<EvalSuite>(`/evals/suites/${id}`, payload);
  return data;
}

export async function deleteSuite(id: string): Promise<void> {
  await api.delete(`/evals/suites/${id}`);
}

export async function runSuite(
  id: string,
  payload?: EvalRunTrigger,
): Promise<EvalRunCreated> {
  const { data } = await api.post<EvalRunCreated>(
    `/evals/suites/${id}/run`,
    payload ?? {},
  );
  return data;
}

export async function getRun(id: string): Promise<EvalRun> {
  const { data } = await api.get<EvalRun>(`/evals/runs/${id}`);
  return data;
}

export async function getRunResults(
  id: string,
  page = 1,
  limit = 50,
): Promise<PaginatedEvalResults> {
  const { data } = await api.get<PaginatedEvalResults>(
    `/evals/runs/${id}/results`,
    { params: { page, limit } },
  );
  return data;
}

export async function listRuns(filters?: {
  status?: RunStatus;
  limit?: number;
}): Promise<EvalRun[]> {
  const { data } = await api.get<EvalRun[]>("/evals/runs", { params: filters });
  return data;
}
