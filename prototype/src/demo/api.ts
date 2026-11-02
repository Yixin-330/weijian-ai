import { type CreatedWorld } from "../shared/api/types";
import { readApiError, apiFetch } from "../shared/api/client";

export async function bootstrapDemoWorld(): Promise<CreatedWorld> {
  const response = await apiFetch(`/demo/bootstrap`, { method: "POST" });
  if (!response.ok) throw new Error(await readApiError(response, "体验世界初始化失败"));
  return response.json() as Promise<CreatedWorld>;
}
