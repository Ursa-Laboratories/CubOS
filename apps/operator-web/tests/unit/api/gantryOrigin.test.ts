import { afterEach, describe, expect, it, vi } from "vitest";
import { gantryApi } from "../../../src/api/client";
import { isDeckOrigin, requireDeckOrigin } from "../../../src/utils/gantryOrigin";
import type { GantryConfig } from "../../../src/types";

afterEach(() => vi.unstubAllGlobals());

describe("deck-only gantry boundary", () => {
  it.each([{}, { origin_policy: "deck_origin" }])("accepts valid deck configuration %j", (config) => {
    expect(isDeckOrigin(config)).toBe(true);
    expect(() => requireDeckOrigin(config)).not.toThrow();
  });

  it.each(["home_origin", "unknown", null])("rejects unsupported %s configuration before writes or calibration", async (policy) => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const config = { origin_policy: policy } as unknown as GantryConfig;
    expect(isDeckOrigin(config)).toBe(false);
    await expect(gantryApi.put("legacy.yaml", config)).rejects.toThrow("Unsupported coordinate origin");
    await expect(gantryApi.previewInstrumentOffsets({ config, reference_instrument: "pipette", captures: {} })).rejects.toThrow("Unsupported coordinate origin");
    await expect(gantryApi.finalizeCalibrationOrigin({ origin_policy: policy, home_z: 0, block_touch_z: -20, block_height: 10, factory_z_travel: 80 } as unknown as Parameters<typeof gantryApi.finalizeCalibrationOrigin>[0])).rejects.toThrow("Unsupported coordinate origin");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects legacy server data instead of exposing a different coordinate frame", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ filename: "legacy.yaml", config: { origin_policy: "home_origin" } }), { status: 200 })));
    await expect(gantryApi.get("legacy.yaml")).rejects.toThrow("Unsupported coordinate origin");
  });

  it.each([undefined, "deck_origin"])("rejects unmistakable legacy bounds with policy %s", async (origin_policy) => {
    const config = { origin_policy, working_volume: { x_max: 0, y_max: 0, z_min: -80 } } as unknown as GantryConfig;
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    expect(isDeckOrigin(config)).toBe(false);
    await expect(gantryApi.put("legacy.yaml", config)).rejects.toThrow("Unsupported coordinate origin");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("preserves configured negative XY travel in a valid deck frame", () => {
    expect(isDeckOrigin({ working_volume: { x_min: -10, x_max: 300, y_min: -20, y_max: 200, z_min: 0, z_max: 80 } })).toBe(true);
  });
});
