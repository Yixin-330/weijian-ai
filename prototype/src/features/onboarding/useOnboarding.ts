import { useEffect, useRef, useState } from "react";
import type { CreatedWorld, OnboardingAnswers } from "../../shared/api/types";
import { createWorldFromOnboarding } from "./api";

/** One creation intent keeps its idempotency key across explicit retries. */
export function useOnboarding() {
  const [answers, setAnswers] = useState<OnboardingAnswers>({
    currentQuestion: "", topics: [], exploration: null, socialPace: null,
    allowMemory: true, allowSocial: false,
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [key] = useState(() => crypto.randomUUID());
  const scope = useRef<AbortController | null>(null);
  const inFlight = useRef(false);
  useEffect(() => {
    const controller = new AbortController(); scope.current = controller;
    return () => { controller.abort(); };
  }, []);

  const submit = async (): Promise<CreatedWorld | null> => {
    const signal = scope.current?.signal;
    if (!signal || signal.aborted || inFlight.current || !answers.exploration || !answers.socialPace) return null;
    inFlight.current = true; setSubmitting(true); setError("");
    try {
      const world = await createWorldFromOnboarding(answers, key, signal);
      return signal.aborted ? null : world;
    } catch (failure) {
      if (!signal.aborted) setError(failure instanceof Error ? failure.message : "暂时无法创建，请稍后重试。");
      return null;
    } finally {
      if (!signal.aborted) { inFlight.current = false; setSubmitting(false); }
    }
  };
  return { answers, setAnswers, submitting, error, submit };
}
