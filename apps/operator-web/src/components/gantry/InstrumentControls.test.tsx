import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import InstrumentControls from "./InstrumentControls";
import { instrumentsApi } from "../../api/client";

const lightingEntry = {
  instrument: "lights",
  connected: false,
  channels: { white: [5, 10, 15, 25, 50, 100], contact: [5, 10, 20, 30, 50] },
  active: { white: 0, contact: 0 },
};

const cameraEntry = {
  instrument: "camera",
  vendor: "flir",
  connected: false,
  last_image: null,
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("InstrumentControls", () => {
  it("renders nothing while the gantry is disconnected", () => {
    const { container } = render(
      <InstrumentControls connected={false} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the config has no lighting or camera", async () => {
    vi.spyOn(instrumentsApi, "listLighting").mockResolvedValue([]);
    vi.spyOn(instrumentsApi, "listCameras").mockResolvedValue([]);
    const { container } = render(<InstrumentControls connected />);
    await waitFor(() => expect(instrumentsApi.listLighting).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders vendor-declared levels and sends set on click", async () => {
    vi.spyOn(instrumentsApi, "listLighting").mockResolvedValue([lightingEntry]);
    vi.spyOn(instrumentsApi, "listCameras").mockResolvedValue([]);
    const setLights = vi
      .spyOn(instrumentsApi, "setLights")
      .mockResolvedValue({ ...lightingEntry, connected: true, active: { white: 25, contact: 0 } });

    render(<InstrumentControls connected />);
    const level = await screen.findByRole("button", { name: "25%" });
    await userEvent.click(level);
    expect(setLights).toHaveBeenCalledWith({
      instrument: "lights",
      channel: "white",
      brightness: 25,
    });
  });

  it("sends all_off from the All lights off button", async () => {
    vi.spyOn(instrumentsApi, "listLighting").mockResolvedValue([lightingEntry]);
    vi.spyOn(instrumentsApi, "listCameras").mockResolvedValue([]);
    const setLights = vi
      .spyOn(instrumentsApi, "setLights")
      .mockResolvedValue({ ...lightingEntry, connected: true });

    render(<InstrumentControls connected />);
    await userEvent.click(
      await screen.findByRole("button", { name: "All lights off" }),
    );
    expect(setLights).toHaveBeenCalledWith({
      instrument: "lights",
      all_off: true,
    });
  });

  it("captures an image from the camera button", async () => {
    vi.spyOn(instrumentsApi, "listLighting").mockResolvedValue([]);
    vi.spyOn(instrumentsApi, "listCameras").mockResolvedValue([cameraEntry]);
    const capture = vi
      .spyOn(instrumentsApi, "capture")
      .mockResolvedValue({ instrument: "camera", image_path: "/tmp/x.png" });

    render(<InstrumentControls connected />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Capture image" }),
    );
    expect(capture).toHaveBeenCalledWith("camera");
  });

  it("disables controls while a protocol run is active", async () => {
    vi.spyOn(instrumentsApi, "listLighting").mockResolvedValue([lightingEntry]);
    vi.spyOn(instrumentsApi, "listCameras").mockResolvedValue([cameraEntry]);

    render(<InstrumentControls connected isRunning />);
    const level = await screen.findByRole("button", { name: "25%" });
    expect(level).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Capture image" }),
    ).toBeDisabled();
    expect(
      screen.getByText(/disabled while a protocol run/i),
    ).toBeInTheDocument();
  });
});
