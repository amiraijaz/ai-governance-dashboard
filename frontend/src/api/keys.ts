import { api } from "./client";

export interface APIKeyInfo {
  id: string;
  name: string | null;
  created_at: string;
  last_used_at: string | null;
  is_active: boolean;
}

export interface APIKeyCreated extends APIKeyInfo {
  key: string;
}

export async function listKeys(): Promise<APIKeyInfo[]> {
  const { data } = await api.get<APIKeyInfo[]>("/keys/");
  return data;
}

export async function createKey(name?: string): Promise<APIKeyCreated> {
  const { data } = await api.post<APIKeyCreated>("/keys/", { name });
  return data;
}

export async function deleteKey(id: string): Promise<void> {
  await api.delete(`/keys/${id}`);
}
