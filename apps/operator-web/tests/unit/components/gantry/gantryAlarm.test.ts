import { describe, expect, it } from "vitest";
import { hasGantryAlarm, isGantryHoming, isVerifiedIdle } from "../../../../src/components/gantry/gantryAlarm";

describe("gantry fault detection", () => {
  it.each(["ALARM:3", "[MSG:Check Limits]", "error:9 Reset to continue", "<Idle|Pn:Z>", "Home required"])("detects %s", (status) => {
    expect(hasGantryAlarm(status)).toBe(true);
    expect(isVerifiedIdle({ connected: true, status })).toBe(false);
  });
  it.each(["Idle", "<Idle|WPos:0,0,0>", "<Idle|Pn:D>", "Run", null, ""])("does not treat %s as a fault", (status) => {
    expect(hasGantryAlarm(status)).toBe(false);
  });
  it("distinguishes homing from faults and accepts only finite verified work coordinates", () => {
    const verified = { connected: true, status: "Idle", work_x: 0, work_y: 0, work_z: 0 };
    expect(isVerifiedIdle(verified)).toBe(true);
    expect(isVerifiedIdle({ ...verified, work_z: null })).toBe(false);
    expect(isVerifiedIdle({ ...verified, work_z: NaN })).toBe(false);
    expect(isVerifiedIdle({ ...verified, status: "Homing" })).toBe(false);
    expect(isGantryHoming("Homing")).toBe(true);
    expect(isGantryHoming("Jog")).toBe(false);
    expect(hasGantryAlarm("Homing")).toBe(false);
  });
});
