import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import CampaignFluidState from "./CampaignFluidState";
import type { DeckResponse, FluidStateSummary } from "../../types";

const deck: DeckResponse = {
  filename: "deck.yaml",
  labware: [{
    key: "tips",
    config: {
      type: "tip_rack",
      name: "Tips",
      model_name: "tips",
      rows: 1,
      columns: 2,
      tips: { A1: { x: 0, y: 0, z: 0 }, A2: { x: 1, y: 0, z: 0 } },
    },
    wells: null,
  }],
};

const created: FluidStateSummary = {
  id: 12,
  label: "fresh",
  deck_path: "/configs/deck.yaml",
  deck_fingerprint: "a".repeat(64),
  created_at: "now",
  updated_at: "now",
  container_count: 1,
  operation_count: 0,
};

function renderState(props: Partial<React.ComponentProps<typeof CampaignFluidState>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onSelect = vi.fn();
  render(<QueryClientProvider client={client}><CampaignFluidState deckFile="deck.yaml" deck={deck} states={[]} selectedId={null} onSelect={onSelect} {...props} /></QueryClientProvider>);
  return onSelect;
}

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

describe("CampaignFluidState", () => {
  it("creates and binds a fresh state with explicit volumes and tip states without resetting another state", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(created), { status: 201 }));
    const onSelect = renderState();
    fireEvent.click(screen.getByText("Create a fresh fluid state"));
    fireEvent.change(screen.getByLabelText("New campaign fluid state label"), { target: { value: "fresh" } });
    fireEvent.click(screen.getByRole("button", { name: "Add container volume" }));
    fireEvent.change(screen.getByLabelText("Campaign seed container 1"), { target: { value: "stocks.A1" } });
    fireEvent.change(screen.getByLabelText("Campaign seed volume 1"), { target: { value: "900" } });
    fireEvent.click(screen.getByLabelText("tips.A1 tip present"));
    expect(screen.getByLabelText("tips.A2 tip present")).toBeChecked();
    fireEvent.click(screen.getByLabelText("I verified these tip states against the physical rack"));
    fireEvent.click(screen.getByRole("button", { name: "Create and bind state" }));

    await waitFor(() => expect(onSelect).toHaveBeenCalledWith(12));
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toEqual({
      deck_file: "deck.yaml",
      label: "fresh",
      fluids: { "stocks.A1": { volume_ul: 900 } },
      tips: { "tips.A1": false, "tips.A2": true },
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(init?.method).toBe("POST");
  });

  it("attaches a selected state to a failed campaign only with an operator reconciliation note", async () => {
    const stopped = {
      campaign_id: "old-1", spec: { name: "old", gantry_file: "g", deck_file: "deck.yaml", protocol_file: "p", parameters: [], sequences: [], objective: { mode: "result" as const, path: "1.value", direction: "minimize" as const }, optimizer: { method: "ei" as const, kernel: "matern52" as const, initial_trials: 1, initial_points: [], exploration: 0.1, seed: 1 }, stop: { max_trials: 2, target_value: null, patience: 1, min_improvement: 0, max_seconds: null }, mock_mode: false, fluid_state_id: null }, state: "failed" as const, created_at: "", updated_at: "", active_run_id: null, trials: [], best_objective: null, stop_reason: null, error: null, pause_requested: false, stop_requested: false,
    };
    const updated = { ...stopped, spec: { ...stopped.spec, fluid_state_id: 12 } };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(updated), { status: 200 }));
    const attached = vi.fn();
    renderState({ states: [created], selectedId: 12, selectedCampaign: stopped, onCampaignAttached: attached });
    const button = screen.getByRole("button", { name: "Attach state to campaign" });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Campaign fluid state reconciliation note"), { target: { value: "A1-A3 consumed; volumes checked" } });
    fireEvent.click(button);
    await waitFor(() => expect(attached).toHaveBeenCalledWith(updated));
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/campaigns/old-1/fluid-state", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ fluid_state_id: 12, reconciliation_note: "A1-A3 consumed; volumes checked" }),
    }));
  });

  it("requires tip confirmation again after a slot changes", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(created), { status: 201 }));
    renderState();
    fireEvent.click(screen.getByText("Create a fresh fluid state"));
    fireEvent.click(screen.getByRole("button", { name: "Add container volume" }));
    fireEvent.change(screen.getByLabelText("Campaign seed container 1"), { target: { value: "stocks.A1" } });
    fireEvent.change(screen.getByLabelText("Campaign seed volume 1"), { target: { value: "500" } });
    const confirmation = screen.getByLabelText("I verified these tip states against the physical rack");
    fireEvent.click(confirmation);
    expect(confirmation).toBeChecked();
    fireEvent.click(screen.getByLabelText("tips.A1 tip present"));
    expect(confirmation).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Create and bind state" }));
    expect(await screen.findByText(/Confirm that the displayed tip states match/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
