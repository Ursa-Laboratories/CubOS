import { useCallback, useSyncExternalStore } from "react";
import { gantryApi, type LimitRecoveryContext } from "../api/client";

type Snapshot = { context: LimitRecoveryContext | null; error: string | null };
const empty: Snapshot = { context: null, error: null };
let snapshot = empty;
const listeners = new Set<() => void>();
let timer: ReturnType<typeof setInterval> | null = null;
let generation = 0;
let pending = false;

async function poll() {
  if (pending || listeners.size === 0) return;
  pending = true;
  const current = generation;
  try {
    const context = await gantryApi.getLimitRecoveryContext();
    if (current !== generation) return;
    snapshot = { context, error: null };
  } catch (error) {
    if (current !== generation) return;
    snapshot = { context: null, error: error instanceof Error ? error.message : String(error) };
  } finally {
    if (current === generation) {
      pending = false;
      listeners.forEach((notify) => notify());
    }
  }
}

function subscribe(notify: () => void) {
  listeners.add(notify);
  if (listeners.size === 1) {
    void poll();
    timer = setInterval(() => { void poll(); }, 1000);
  }
  return () => {
    listeners.delete(notify);
    if (listeners.size === 0) {
      if (timer) clearInterval(timer);
      timer = null;
      generation += 1;
      pending = false;
      snapshot = empty;
    }
  };
}

export function useLimitRecoveryContext(enabled: boolean) {
  const listen = useCallback((notify: () => void) => enabled ? subscribe(notify) : () => undefined, [enabled]);
  return useSyncExternalStore(listen, () => enabled ? snapshot : empty);
}
