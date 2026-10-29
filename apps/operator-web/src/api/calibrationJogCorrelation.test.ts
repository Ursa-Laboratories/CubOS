import { afterEach, expect, it, vi } from "vitest";
import { gantryApi } from "./client";

afterEach(() => vi.unstubAllGlobals());

it("preserves legacy jog bodies and passes optional correlation IDs unchanged", async () => {
  const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(async () => new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await gantryApi.jog(0, 1, 0);
  await gantryApi.jog(0, 1, 0, "calibration-owned");
  await gantryApi.jogBlocking(0, 0, 1, 12);
  await gantryApi.jogBlocking(0, 0, 1, 12, "calibration-lift");
  await gantryApi.recoverCalibrationLimit({ x: 0, y: 1, z: 0, jog_id: "calibration-owned" });
  expect(fetchMock.mock.calls.map(([, init]) => JSON.parse(String(init?.body)))).toEqual([
    { x: 0, y: 1, z: 0 },
    { x: 0, y: 1, z: 0, jog_id: "calibration-owned" },
    { x: 0, y: 0, z: 1, timeout_s: 12 },
    { x: 0, y: 0, z: 1, timeout_s: 12, jog_id: "calibration-lift" },
    { x: 0, y: 1, z: 0, jog_id: "calibration-owned" },
  ]);
});
