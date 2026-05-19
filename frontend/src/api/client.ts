import axios, {
  AxiosError,
  AxiosRequestConfig,
  InternalAxiosRequestConfig,
} from "axios";

export const TOKEN_KEY = "aigov_token";
const REFRESH_KEY = "aigov_refresh_token";

const baseURL =
  (import.meta.env.VITE_API_URL as string | undefined) ??
  "http://localhost:8000/api";

export const api = axios.create({
  baseURL,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    config.headers.set("Authorization", `Bearer ${token}`);
  }
  return config;
});

// ---- 401 → refresh + replay queue --------------------------------------

interface Waiter {
  resolve: (token: string) => void;
  reject: (err: unknown) => void;
}

let isRefreshing = false;
let failedQueue: Waiter[] = [];

function flushQueue(token: string | null, err: unknown = null) {
  for (const w of failedQueue) {
    if (token) w.resolve(token);
    else w.reject(err);
  }
  failedQueue = [];
}

function redirectToLogin() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
  if (typeof window !== "undefined" && window.location.pathname !== "/login") {
    window.location.assign("/login");
  }
}

async function performRefresh(): Promise<string> {
  const refresh_token = localStorage.getItem(REFRESH_KEY);
  if (!refresh_token) throw new Error("no refresh token");
  // Bypass the instance to avoid recursing through this interceptor.
  const { data } = await axios.post<{
    access_token: string;
    refresh_token: string;
  }>(`${baseURL}/auth/refresh`, { refresh_token });
  localStorage.setItem(TOKEN_KEY, data.access_token);
  localStorage.setItem(REFRESH_KEY, data.refresh_token);
  return data.access_token;
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as
      | (AxiosRequestConfig & { _retry?: boolean })
      | undefined;
    const status = error.response?.status;

    // Anything other than 401, or a missing config: pass through.
    if (status !== 401 || !original) return Promise.reject(error);

    // Don't try to refresh on auth endpoints themselves — would loop.
    const url = original.url ?? "";
    if (
      url.includes("/auth/refresh") ||
      url.includes("/auth/login") ||
      url.includes("/auth/register")
    ) {
      if (url.includes("/auth/refresh")) redirectToLogin();
      return Promise.reject(error);
    }

    // Already retried once — give up.
    if (original._retry) {
      redirectToLogin();
      return Promise.reject(error);
    }
    original._retry = true;

    // A refresh is already in flight: queue this request and wait.
    if (isRefreshing) {
      return new Promise((resolve, reject) => {
        failedQueue.push({
          resolve: (token) => {
            original.headers = original.headers ?? {};
            (original.headers as Record<string, string>)["Authorization"] =
              `Bearer ${token}`;
            resolve(api(original));
          },
          reject,
        });
      });
    }

    // We own the refresh.
    isRefreshing = true;
    try {
      const newToken = await performRefresh();
      flushQueue(newToken);
      original.headers = original.headers ?? {};
      (original.headers as Record<string, string>)["Authorization"] =
        `Bearer ${newToken}`;
      return api(original);
    } catch (refreshErr) {
      flushQueue(null, refreshErr);
      redirectToLogin();
      return Promise.reject(refreshErr);
    } finally {
      isRefreshing = false;
    }
  }
);
