import { useEffect, useState } from "react";

let sequence = 0;

function uniqueJogId(): string {
  const bytes = new Uint8Array(16);
  let random: string;
  try {
    globalThis.crypto.getRandomValues(bytes);
    random = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  } catch {
    random = Math.random().toString(36).slice(2);
  }
  return `calibration-${Date.now().toString(36)}-${++sequence}-${random}`;
}

export type CalibrationAutoRecovery = {
  readonly active: boolean;
  readonly generation: number;
  readonly lifetime: number;
  begin: () => void;
  end: () => void;
  cancel: () => void;
  issueJogId: (generation?: number) => string | undefined;
  claimFault: (jogId: string) => boolean;
};

function createScope(): CalibrationAutoRecovery {
  let active = false;
  let generation = 0;
  let lifetime = 0;
  const owned = new Set<string>();
  const attempted = new Set<string>();
  const cancel = () => { generation += 1; owned.clear(); attempted.clear(); };
  return {
    get active() { return active; },
    get generation() { return generation; },
    get lifetime() { return lifetime; },
    begin: () => { lifetime += 1; cancel(); active = true; },
    end: () => { lifetime += 1; cancel(); active = false; },
    cancel,
    issueJogId: (expected = generation) => {
      if (!active || expected !== generation) return undefined;
      const id = uniqueJogId();
      owned.add(id);
      return id;
    },
    claimFault: (id) => {
      if (!active || !owned.has(id) || attempted.has(id)) return false;
      attempted.add(id);
      return true;
    },
  };
}

export function useCalibrationAutoRecovery(open: boolean, connected = true) {
  const [scope] = useState(createScope);
  useEffect(() => {
    if (open) scope.begin();
    else scope.end();
    return () => scope.end();
  }, [open, scope]);
  useEffect(() => {
    if (!connected) scope.cancel();
  }, [connected, scope]);
  return scope;
}
