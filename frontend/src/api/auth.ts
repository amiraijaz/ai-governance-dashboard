import { api, TOKEN_KEY } from "./client";
import type { AuthTokens, UserProfile } from "../types";

export interface UserMe {
  id: string;
  email: string;
  role: string;
  organisation: string | null;
  created_at: string;
}

export async function getMe(): Promise<UserMe> {
  const { data } = await api.get<UserMe>("/auth/me");
  return data;
}

const REFRESH_KEY = "aigov_refresh_token";

const EMAIL_KEY = "aigov_email";

export async function login(email: string, password: string): Promise<AuthTokens> {
  const { data } = await api.post<AuthTokens>("/auth/login", { email, password });
  localStorage.setItem(TOKEN_KEY, data.access_token);
  localStorage.setItem(REFRESH_KEY, data.refresh_token);
  localStorage.setItem(EMAIL_KEY, email);
  return data;
}

export async function register(
  email: string,
  password: string,
  organisation?: string
): Promise<UserProfile> {
  const { data } = await api.post<UserProfile>("/auth/register", {
    email,
    password,
    organisation,
  });
  return data;
}

export async function refreshToken(): Promise<AuthTokens> {
  const refresh_token = localStorage.getItem(REFRESH_KEY);
  if (!refresh_token) throw new Error("No refresh token");
  const { data } = await api.post<AuthTokens>("/auth/refresh", { refresh_token });
  localStorage.setItem(TOKEN_KEY, data.access_token);
  localStorage.setItem(REFRESH_KEY, data.refresh_token);
  return data;
}

export function logout(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(EMAIL_KEY);
}

export function getCurrentEmail(): string | null {
  return localStorage.getItem(EMAIL_KEY);
}
