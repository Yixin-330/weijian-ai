import { type IslandCatalogResponse, type IslandId, type DesktopIsland } from "../../shared/api/types";
import { fallbackDesktopIslands } from "../../demo/content";
import { isIslandId } from "../../shared/config/options";

export function mergeIslandCatalog(payload: IslandCatalogResponse): Record<IslandId, DesktopIsland> {
  const merged = { ...fallbackDesktopIslands };
  for (const island of payload.islands) {
    if (!isIslandId(island.island_id)) continue;
    const current = merged[island.island_id];
    merged[island.island_id] = {
      ...current,
      name: island.island_name,
      question: island.source.question_title,
      questionUrl: island.source.question_url,
      viewpointCount: island.viewpoint_count,
      viewpoints: island.viewpoint_materials.map((material) => ({
        materialId: material.material_id,
        summary: material.summary,
        sourceUrl: material.source_url,
      })),
    };
  }
  return merged;
}
