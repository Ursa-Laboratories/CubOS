import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import CampaignCameraMonitor from "./CampaignCameraMonitor";
import type { CameraMonitorStatus } from "./types";

const status = (overrides: Partial<CameraMonitorStatus> = {}): CameraMonitorStatus => ({
  instrument: "camera",
  state: "running",
  connected: true,
  camera_id: 0,
  lease_id: "lease-1",
  lease_expires_at: 115,
  subscriber_count: 1,
  requested_resolution: { width: 800, height: 600 },
  actual_resolution: { width: 800, height: 600 },
  requested_pixel_format: null,
  actual_pixel_format: "BGR8",
  frame_id: 7,
  received_at: 100,
  frame_age_seconds: 4.2,
  image_url: null,
  control_fingerprint: "abc",
  run_id: "run-7",
  campaign_id: "campaign-3",
  trial_number: 2,
  step_index: 8,
  step_command: "measure_color",
  step_substep: null,
  expected_well: "plate.A3",
  well_identity_verification: "not_verified_by_cv",
  roi: null,
  quality: null,
  processing_profile: null,
  analysis_image_url: "/api/v1/instruments/camera/monitor/analysis-frame?instrument=camera",
  analysis_source_run_id: "run-6",
  analysis_source_well: "plate.A2",
  analysis_source_frame_id: 6,
  analysis_source_received_at: 99,
  analysis_is_current_frame: false,
  latest_analysis: {
    roi: { center_x_px: 455, center_y_px: 317, radius_px: 18, center_residual_px: 58 },
    quality: { score: 0.2, glare_fraction: 0.04, flags: ["high_clipping"] },
    processing_profile: { calibration_status: "uncalibrated" },
  },
  warnings: ["Exposure is clipped"],
  error: null,
  ...overrides,
});

afterEach(() => vi.restoreAllMocks());

describe("CampaignCameraMonitor", () => {
  it("starts, shows exact frame metadata and freshness, then releases the monitor", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (path.endsWith("/start")) return new Response(JSON.stringify(status({ frame_id: null, frame_age_seconds: null })), { status: 200 });
      if (path.endsWith("/stop")) return new Response(JSON.stringify(status({ state: "stopped" })), { status: 200 });
      if (path.endsWith("/heartbeat")) return new Response(JSON.stringify(status()), { status: 200 });
      if (path.includes("/monitor?instrument=")) return new Response(JSON.stringify(status()), { status: 200 });
      throw new Error(`unexpected request ${path} ${init?.method ?? "GET"}`);
    });

    const view = render(<CampaignCameraMonitor instrument="camera" />);
    const image = await screen.findByAltText("Live campaign frame from camera");
    expect(image).toHaveAttribute("src", expect.stringContaining("frame_id=7"));
    expect(screen.getByText("4.2 s old · stale")).toBeInTheDocument();
    expect(screen.getByText("plate.A3")).toBeInTheDocument();
    expect(screen.getByText("9: measure_color")).toBeInTheDocument();
    expect(screen.getByText(/run-6 · plate.A2 · frame 6 · prior frame/)).toBeInTheDocument();
    expect(screen.getByText(/455.0, 317.0 px · 58.0 px residual/)).toBeInTheDocument();
    expect(screen.getByText(/does not verify well identity/i)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Exposure is clipped");
    expect(screen.getByRole("alert")).toHaveTextContent("high_clipping");

    view.unmount();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/instruments/camera/monitor/stop",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ instrument: "camera", lease_id: "lease-1" }) }),
    ));
  });

  it("keeps polling after a transient status error", async () => {
    let statusCalls = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/start")) return new Response(JSON.stringify(status({ frame_id: null })), { status: 200 });
      if (path.endsWith("/stop")) return new Response(JSON.stringify(status({ state: "stopped" })), { status: 200 });
      if (path.endsWith("/heartbeat")) return new Response(JSON.stringify(status()), { status: 200 });
      if (path.includes("/monitor?instrument=")) {
        statusCalls += 1;
        if (statusCalls === 1) return new Response("camera owner busy", { status: 503 });
        return new Response(JSON.stringify(status()), { status: 200 });
      }
      throw new Error(`unexpected request ${path}`);
    });

    const view = render(<CampaignCameraMonitor instrument="camera" />);
    expect(await screen.findByText(/camera owner busy/i)).toBeInTheDocument();
    expect(await screen.findByAltText("Live campaign frame from camera", {}, { timeout: 2500 })).toBeInTheDocument();
    expect(statusCalls).toBeGreaterThanOrEqual(2);
    view.unmount();
    expect(fetchMock).toHaveBeenCalled();
  }, 5000);

  it("draws exact-current ROI in source-image pixels without stretching its radius", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/stop")) return new Response(JSON.stringify(status({ state: "stopped" })), { status: 200 });
      return new Response(JSON.stringify(status({
        analysis_is_current_frame: true,
        roi: { center_x_px: 455, center_y_px: 317, radius_px: 18 },
      })), { status: 200 });
    });
    const view = render(<CampaignCameraMonitor instrument="camera" />);
    await screen.findByAltText("Live campaign frame from camera");
    const roi = document.querySelector(".campaign-detected-center");
    expect(roi).toHaveAttribute("cx", "455");
    expect(roi).toHaveAttribute("cy", "317");
    expect(roi).toHaveAttribute("r", "18");
    expect(roi?.closest("svg")).toHaveAttribute("viewBox", "0 0 800 600");
    view.unmount();
  });

  it("renews its own lease before expiry", async () => {
    vi.useFakeTimers();
    try {
      const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const path = String(input);
        if (path.endsWith("/start") || path.endsWith("/heartbeat") || path.includes("/monitor?instrument=")) {
          return new Response(JSON.stringify(status()), { status: 200 });
        }
        if (path.endsWith("/stop")) return new Response(JSON.stringify(status({ state: "stopped" })), { status: 200 });
        throw new Error(`unexpected request ${path}`);
      });
      const view = render(<CampaignCameraMonitor instrument="camera" />);
      await vi.advanceTimersByTimeAsync(5100);
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/instruments/camera/monitor/heartbeat",
        expect.objectContaining({ method: "POST", body: JSON.stringify({ instrument: "camera", lease_id: "lease-1" }) }),
      );
      view.unmount();
      await vi.runAllTimersAsync();
    } finally {
      vi.useRealTimers();
    }
  });

  it("releases a lease that arrives after the view has already unmounted", async () => {
    let resolveStart!: (response: Response) => void;
    const startResponse = new Promise<Response>((resolve) => { resolveStart = resolve; });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/start")) return startResponse;
      if (path.endsWith("/stop")) return new Response(JSON.stringify(status({ state: "stopped" })), { status: 200 });
      if (path.includes("/monitor?instrument=")) return new Response(JSON.stringify(status({ lease_id: null })), { status: 200 });
      throw new Error(`unexpected request ${path}`);
    });
    const view = render(<CampaignCameraMonitor instrument="camera" />);
    view.unmount();
    resolveStart(new Response(JSON.stringify(status()), { status: 200 }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/instruments/camera/monitor/stop",
      expect.objectContaining({ body: JSON.stringify({ instrument: "camera", lease_id: "lease-1" }) }),
    ));
  });

  it("reacquires a new lease after heartbeat expiry", async () => {
    vi.useFakeTimers();
    try {
      let starts = 0;
      const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        const path = String(input);
        if (path.endsWith("/start")) {
          starts += 1;
          return new Response(JSON.stringify(status({ lease_id: `lease-${starts}` })), { status: 200 });
        }
        if (path.endsWith("/heartbeat")) return new Response("lease expired", { status: 409 });
        if (path.endsWith("/stop")) return new Response(JSON.stringify(status({ state: "stopped" })), { status: 200 });
        if (path.includes("/monitor?instrument=")) return new Response(JSON.stringify(status()), { status: 200 });
        throw new Error(`unexpected request ${path}`);
      });
      const view = render(<CampaignCameraMonitor instrument="camera" />);
      await vi.advanceTimersByTimeAsync(5100);
      expect(starts).toBe(2);
      view.unmount();
      await vi.runAllTimersAsync();
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/instruments/camera/monitor/stop",
        expect.objectContaining({ body: JSON.stringify({ instrument: "camera", lease_id: "lease-2" }) }),
      );
    } finally {
      vi.useRealTimers();
    }
  });
});
