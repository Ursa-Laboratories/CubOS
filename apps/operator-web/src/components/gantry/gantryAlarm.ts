export function hasGantryAlarm(status: string | null | undefined): boolean {
  if (!status) return false;
  return /\balarm\b|\bcheck limits\b|\breset to continue\b|\berror:\s*9\b|\bhome required\b/i.test(status)
    || /(?:^|[|;]\s*)Pn:[A-Z]*[XYZ][A-Z]*(?:[|>;]|$)/i.test(status);
}

export function isGantryHoming(status: string | null | undefined): boolean {
  return !!status && /^<?homing(?:[|>]|$)/i.test(status);
}

export function isVerifiedIdle(position: { connected: boolean; status: string; work_x?: number | null; work_y?: number | null; work_z?: number | null }): boolean {
  return position.connected && /^(?:<)?Idle(?:\||>|$)/i.test(position.status)
    && !hasGantryAlarm(position.status)
    && [position.work_x, position.work_y, position.work_z].every((value) => typeof value === "number" && Number.isFinite(value));
}
