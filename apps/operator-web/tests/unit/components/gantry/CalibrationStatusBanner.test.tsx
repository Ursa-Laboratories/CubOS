import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import CalibrationStatusBanner from "../../../../src/components/gantry/CalibrationStatusBanner";

describe("calibration status slot", () => {
  it("keeps one stable slot and layout class across idle, success, operation and fault", () => {
    const { rerender } = render(<CalibrationStatusBanner message={null} alarm={false} tone="idle" />);
    const slot = screen.getByTestId("calibration-status-slot");
    const layout = slot.className;
    for (const [message, tone, alarm] of [
      ["Homed.", "info", false], ["Homing… Please wait.", "warning", false],
      ["Recovering… Space to cancel.", "error", true], ["Recovery failed.", "error", true],
    ] as const) {
      rerender(<CalibrationStatusBanner message={message} alarm={alarm} tone={tone} />);
      expect(screen.getAllByTestId("calibration-status-slot")).toHaveLength(1);
      expect(screen.getByTestId("calibration-status-slot")).toBe(slot);
      expect(slot.className).toBe(layout);
      expect(screen.getByRole("region", { name: "Calibration message" })).toHaveTextContent(message);
    }
  });

  it("keeps the full long message keyboard reachable and Home outside its scroll region", () => {
    const message = "Controller verification failed. ".repeat(100);
    render(<CalibrationStatusBanner message={message} alarm tone="error" action={<button>Home and resume</button>} />);
    const region = screen.getByRole("region", { name: "Calibration message" });
    expect(region.textContent).toContain(message);
    expect(region).toHaveAttribute("tabindex", "0");
    region.focus();
    expect(region).toHaveFocus();
    const home = screen.getByRole("button", { name: "Home and resume" });
    expect(screen.getByTestId("calibration-status-slot")).toContainElement(home);
    expect(region).not.toContainElement(home);
    expect(home).toBeEnabled();
  });
});
