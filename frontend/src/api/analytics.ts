import { api } from "./client";
import type {
  AnalyticsCost,
  AnalyticsLatency,
  AnalyticsModel,
  AnalyticsRequests,
  DashboardSummary,
  Period,
} from "../types";

export type CostGroupBy = "day" | "model" | "team";

export async function getCostAnalytics(
  period: Period = "30d",
  group_by: CostGroupBy = "day"
): Promise<AnalyticsCost[]> {
  const { data } = await api.get<AnalyticsCost[]>("/analytics/cost", {
    params: { period, group_by },
  });
  return data;
}

export async function getRequestAnalytics(
  period: Period = "30d"
): Promise<AnalyticsRequests[]> {
  const { data } = await api.get<AnalyticsRequests[]>("/analytics/requests", {
    params: { period },
  });
  return data;
}

export async function getLatencyAnalytics(
  period: Period = "30d"
): Promise<AnalyticsLatency[]> {
  const { data } = await api.get<AnalyticsLatency[]>("/analytics/latency", {
    params: { period },
  });
  return data;
}

export async function getModelAnalytics(): Promise<AnalyticsModel[]> {
  const { data } = await api.get<AnalyticsModel[]>("/analytics/models");
  return data;
}

export async function getDashboardSummary(): Promise<DashboardSummary> {
  const { data } = await api.get<DashboardSummary>("/analytics/summary");
  return data;
}
