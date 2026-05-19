import { api } from "./client";

export type ReportStatus = "pending" | "complete" | "failed";

export interface ReportSummary {
  id: string;
  generated_at: string;
  date_from: string;
  date_to: string;
  file_size_bytes: number | null;
  status: ReportStatus;
  error_message: string | null;
}

export interface ReportCreated {
  id: string;
  status: ReportStatus;
  message: string;
}

export interface ReportCreate {
  date_from: string;
  date_to: string;
  model_ids?: string[] | null;
  format?: "pdf" | "csv";
}

export async function getReports(): Promise<ReportSummary[]> {
  const { data } = await api.get<ReportSummary[]>("/reports/");
  return data;
}

export async function getReport(id: string): Promise<ReportSummary> {
  const { data } = await api.get<ReportSummary>(`/reports/${id}`);
  return data;
}

export async function generateReport(payload: ReportCreate): Promise<ReportCreated> {
  const { data } = await api.post<ReportCreated>("/reports/generate", payload);
  return data;
}

export async function downloadReport(id: string, filename?: string): Promise<void> {
  const { data, headers } = await api.get<Blob>(`/reports/${id}/download`, {
    responseType: "blob",
  });
  const cd = (headers["content-disposition"] as string | undefined) ?? "";
  const m = cd.match(/filename="?([^";]+)"?/);
  const name = filename ?? m?.[1] ?? `aigov-report-${id}.pdf`;
  const url = URL.createObjectURL(data);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
