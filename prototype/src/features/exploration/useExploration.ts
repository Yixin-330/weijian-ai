import { useEffect, useRef, useState } from "react";
import type { CreatedWorld, ExplorationPayload } from "../../shared/api/types";
import { isStandaloneExperience } from "../../shared/experience/mode";
import { advanceWorld, readExploration, readWorld, saveExploration } from "./api";

/** Owns settings, optimistic rollback and task lifecycle for both layouts. */
export function useExploration(world: CreatedWorld, onWorldChange: (world: CreatedWorld) => void) {
  const [settings, setSettings] = useState<ExplorationPayload | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const scope = useRef<AbortController | null>(null);
  const inFlight = useRef(false);
  const standalone = isStandaloneExperience();
  const userId = world.user.id;

  useEffect(() => {
    const controller = new AbortController();
    scope.current = controller;
    inFlight.current = false;
    setSettings(null); setBusy(false); setNote("");
    return () => { controller.abort(); };
  }, [userId]);

  useEffect(() => {
    if (standalone) return;
    const controller = new AbortController();
    readExploration(userId, controller.signal)
      .then((value) => { if (!controller.signal.aborted && !inFlight.current) setSettings(value); })
      .catch((error) => { if (!controller.signal.aborted) setNote(String(error)); });
    return () => { controller.abort(); };
  }, [userId, world.latest_tick?.id, standalone]);

  const run = async (task: (signal: AbortSignal) => Promise<void>) => {
    const controller = scope.current;
    if (standalone || inFlight.current || !controller || controller.signal.aborted) return;
    inFlight.current = true; setBusy(true); setNote("");
    try { await task(controller.signal); }
    catch (error) {
      if (!controller.signal.aborted) setNote(error instanceof Error ? error.message : "暂时无法更新探索");
    } finally {
      if (!controller.signal.aborted) { inFlight.current = false; setBusy(false); }
    }
  };

  const save = (changes: Partial<ExplorationPayload["state"]>) => run(async (signal) => {
    if (!settings) return;
    const previous = settings;
    const merged = { ...settings.state, ...changes };
    setSettings({ ...settings, state: merged });
    try {
      const next = await saveExploration(userId, merged, signal);
      if (signal.aborted) return;
      setSettings(next); setNote("探索边界已经保存，下次相遇立即生效。");
    } catch (error) {
      if (!signal.aborted) setSettings(previous);
      throw error;
    }
  });

  const explore = () => run(async (signal) => {
    await advanceWorld(userId, { signal });
    const [next, state] = await Promise.all([readWorld(userId, signal), readExploration(userId, signal)]);
    if (signal.aborted) return;
    onWorldChange(next); setSettings(state);
    setNote(next.latest_tick?.match_reason || "本次探索已经完成。");
  });

  const refresh = () => run(async (signal) => {
    const state = await readExploration(userId, signal);
    if (signal.aborted) return;
    setSettings(state); setNote("已经刷新探索状态，可回到世界查看最近相遇。");
  });

  return { settings, busy, note, standalone, save, explore, refresh };
}
