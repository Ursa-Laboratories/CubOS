import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function zipResponse(body: string): Response {
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "application/zip" },
  });
}

function renderApp() {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        refetchOnWindowFocus: false,
      },
    },
  });

  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

const defaultCampaigns = [
  {
    campaign_id: 1,
    campaign_description: "ASMI sample campaign",
    created_at: "2025-10-30 12:20:00",
    latest_measurement_at: "2025-10-30 12:22:07",
    experiment_count: 2,
    well_count: 2,
    measurement_count: 2,
    measurement_counts: {
      uvvis: 0,
      filmetrics: 0,
      uv_curing: 0,
      camera: 0,
      asmi: 2,
      potentiostat: 0,
    },
    asmi_measurement_count: 2,
  },
];

function installFetchMock(campaignsResponse = () => jsonResponse(defaultCampaigns)) {
  const fetchMock = vi.fn(async (input: string | URL | Request) => {
    const url = new URL(
      typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url,
      "http://localhost",
    );
    const path = url.pathname;

    if (path === "/api/settings") {
      return jsonResponse({ config_dir: "/mock/Zoo/configs" });
    }
    if (path === "/api/deck/configs" || path === "/api/gantry/configs" || path === "/api/protocol/configs") {
      return jsonResponse([]);
    }
    if (path === "/api/gantry/instrument-types") {
      return jsonResponse([]);
    }
    if (path === "/api/gantry/instrument-schemas") {
      return jsonResponse({});
    }
    if (path === "/api/protocol/commands") {
      return jsonResponse([]);
    }
    if (path === "/api/gantry/position") {
      return jsonResponse({
        x: 0,
        y: 0,
        z: 0,
        work_x: 0,
        work_y: 0,
        work_z: 0,
        status: "Idle",
        connected: false,
      });
    }
    if (path === "/api/data/campaigns") {
      return campaignsResponse();
    }
    if (path === "/api/data/campaigns/1/measurements.zip") {
      return zipResponse("mock zip bytes");
    }
    if (path === "/api/data/campaigns/1/asmi.zip") {
      return zipResponse("mock asmi zip bytes");
    }

    return new Response("Not found", { status: 404 });
  });

  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("Results view", () => {
  beforeEach(() => {
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:zoo-asmi-csv"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows campaign output and exports measurement and ASMI ZIPs", async () => {
    const user = userEvent.setup();
    const fetchMock = installFetchMock();

    renderApp();

    await screen.findByDisplayValue("/mock/Zoo/configs");
    await user.click(screen.getByRole("button", { name: "Results" }));

    expect(await screen.findByText("Campaign #1")).toBeInTheDocument();
    expect(screen.getByText("ASMI sample campaign")).toBeInTheDocument();
    expect(screen.getByText(new Date("2025-10-30 12:22:07").toLocaleString())).toBeInTheDocument();
    expect(screen.getAllByText("2")).toHaveLength(3);

    await user.click(screen.getByRole("button", { name: "Measurements ZIP" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/data/campaigns/1/measurements.zip"));
    await user.click(screen.getByRole("button", { name: "ASMI ZIP" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/data/campaigns/1/asmi.zip"));
    expect(URL.createObjectURL).toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:zoo-asmi-csv");
  });

  it("shows first-run empty state without an error", async () => {
    const user = userEvent.setup();
    installFetchMock(() => jsonResponse([]));

    renderApp();

    await screen.findByDisplayValue("/mock/Zoo/configs");
    await user.click(screen.getByRole("button", { name: "Results" }));

    expect(await screen.findByText("No campaigns yet — run a protocol to create one.")).toBeInTheDocument();
    expect(screen.queryByText(/Data load failed/i)).not.toBeInTheDocument();
  });

  it("shows parsed backend error details without raw JSON", async () => {
    const user = userEvent.setup();
    installFetchMock(() => jsonResponse({ detail: "Data database is unreadable" }, 400));

    renderApp();

    await screen.findByDisplayValue("/mock/Zoo/configs");
    await user.click(screen.getByRole("button", { name: "Results" }));

    const alert = await screen.findByText(/Data load failed/i);
    expect(alert).toHaveTextContent("Data load failed: Data database is unreadable");
    expect(alert).not.toHaveTextContent("400:");
    expect(alert).not.toHaveTextContent("{\"detail\"");
  });
});
