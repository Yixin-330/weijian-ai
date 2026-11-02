import { useEffect, useState } from "react";
import { requestJson } from "../../shared/api/client";
import type { IslandCatalogResponse } from "../../shared/api/types";
import { fallbackDesktopIslands } from "../../demo/content";
import { mergeIslandCatalog } from "./catalog";

export function useIslandCatalog(standalone: boolean) {
  const [islands, setIslands] = useState(fallbackDesktopIslands);
  const [catalogLive, setCatalogLive] = useState(standalone);
  useEffect(() => {
    if (standalone) return;
    const controller = new AbortController();
    requestJson<IslandCatalogResponse>("/islands", { signal: controller.signal }, "岛屿目录读取失败")
      .then((payload) => {
        if (!controller.signal.aborted) { setIslands(mergeIslandCatalog(payload)); setCatalogLive(true); }
      })
      .catch(() => { if (!controller.signal.aborted) setCatalogLive(false); });
    return () => { controller.abort(); };
  }, [standalone]);
  return { islands, catalogLive };
}
