import { afterEach, describe, expect, it, vi } from "vitest";
import { gantryApi } from "./client";

function json(status: string) {
  return new Response(JSON.stringify({ connected: true, status, work_x: 0, work_y: 0, work_z: 0 }), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("position polling across homing", () => {
  afterEach(() => vi.unstubAllGlobals());

  it.each([
    ["home", () => gantryApi.home()],
    ["prepare-origin", () => gantryApi.prepareCalibrationOrigin()],
    ["home-and-center", () => gantryApi.homeAndCenterForCalibration()],
  ] as const)("re-reads a stale Home required response after %s succeeds", async (_name, home) => {
    let finishPoll!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => { finishPoll = resolve; });
    let reads = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/position")) return ++reads === 1 ? pending : json("Idle");
      return json("Idle");
    });
    vi.stubGlobal("fetch", fetchMock);
    const poll = gantryApi.getPosition();
    await home();
    finishPoll(json("Home required"));
    expect((await poll).status).toBe("Idle");
    expect(reads).toBe(2);
    expect(fetchMock.mock.calls.filter(([input]) => !String(input).endsWith("/position"))).toHaveLength(1);
  });

  it("preserves a fresh real Y fault after discarding a stale pre-home response", async () => {
    let finishPoll!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => { finishPoll = resolve; });
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/position")) return ++reads === 1 ? pending : json("ALARM:3; Pn:Y");
      return json("Idle");
    }));
    const poll = gantryApi.getPosition();
    await gantryApi.prepareCalibrationOrigin();
    finishPoll(json("Home required"));
    expect((await poll).status).toBe("ALARM:3; Pn:Y");
    expect(reads).toBe(2);
  });

  it("re-reads a poll begun during Home if it finishes after Home succeeds", async () => {
    let finishPoll!: (response: Response) => void;
    let finishHome!: (response: Response) => void;
    const pendingPoll = new Promise<Response>((resolve) => { finishPoll = resolve; });
    const pendingHome = new Promise<Response>((resolve) => { finishHome = resolve; });
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => String(input).endsWith("/position")
      ? ++reads === 1 ? pendingPoll : json("Idle") : pendingHome));
    const home = gantryApi.home();
    const poll = gantryApi.getPosition();
    finishHome(json("Idle"));
    await home;
    finishPoll(json("Home required"));
    expect((await poll).status).toBe("Idle");
    expect(reads).toBe(2);
  });

  it("bounds position re-reads when homing boundaries keep changing", async () => {
    const finish: Array<(response: Response) => void> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => String(input).endsWith("/position")
      ? new Promise<Response>((resolve) => { finish.push(resolve); }) : json("Idle")));
    const poll = gantryApi.getPosition();
    const rejected = expect(poll).rejects.toThrow(/fresh position update/);
    for (let read = 0; read < 3; read += 1) {
      await vi.waitFor(() => expect(finish).toHaveLength(read + 1));
      await gantryApi.home();
      finish[read](json("Home required"));
    }
    await rejected;
    expect(finish).toHaveLength(3);
  });
});
