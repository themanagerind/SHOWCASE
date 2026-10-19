"use client";

import { useEffect, useRef } from "react";

/**
 * Calls `fn` every `ms` while the tab is visible, and once more when it becomes visible again. Errors are
 * swallowed (the page keeps its last data); hidden tabs make no requests (deep audit B4).
 */
export function usePoll(fn: () => Promise<unknown>, ms: number, enabled = true) {
  const ref = useRef(fn);
  useEffect(() => { ref.current = fn; }, [fn]);
  useEffect(() => {
    if (!enabled) return;
    const run = () => { if (document.visibilityState === "visible") ref.current().catch(() => {}); };
    const id = setInterval(run, ms);
    document.addEventListener("visibilitychange", run);
    return () => { clearInterval(id); document.removeEventListener("visibilitychange", run); };
  }, [ms, enabled]);
}
