export const UNSUPPORTED_GANTRY_ORIGIN = "Unsupported coordinate origin. Use a deck-origin gantry configuration.";

type OriginConfig = { origin_policy?: unknown; working_volume?: unknown };

export function isDeckOrigin(config: OriginConfig | null | undefined): boolean {
  if (!config || (config.origin_policy !== undefined && config.origin_policy !== "deck_origin")) return false;
  const volume = config.working_volume;
  if (volume && typeof volume === "object") {
    const values = volume as Record<string, unknown>;
    const [xMax, yMax, zMin] = [values.x_max, values.y_max, values.z_min].map(Number);
    if ([xMax, yMax, zMin].every(Number.isFinite)
      && Math.abs(xMax) <= 1e-9 && Math.abs(yMax) <= 1e-9 && zMin < -1e-9) return false;
  }
  return true;
}

export function requireDeckOrigin(config: OriginConfig | null | undefined): void {
  if (!isDeckOrigin(config)) throw new Error(UNSUPPORTED_GANTRY_ORIGIN);
}
