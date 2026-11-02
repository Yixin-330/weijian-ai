

export const apiBaseUrl = () => (import.meta.env?.VITE_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

/** Central transport seam. Mutations are never silently retried. */
export function apiFetch(path: string, options?: RequestInit): Promise<Response> {
  return fetch(`${apiBaseUrl()}/api/v1${path}`, options);
}

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

export async function requestJson<T>(path: string, options?: RequestInit, fallback = "请求失败"): Promise<T> {
  const response = await apiFetch(path, options);
  if (!response.ok) throw new ApiError(await readApiError(response, fallback), response.status);
  return response.json() as Promise<T>;
}

export async function readApiError(response: Response, fallback: string) {
  const payload = await response.json().catch(() => null) as { detail?: unknown } | null;
  return typeof payload?.detail === "string" ? payload.detail : `${fallback}（${response.status}）`;
}
