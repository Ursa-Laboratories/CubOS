import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import type { InstrumentConfig } from "../../types";
import PipetteGeometryFields from "./PipetteGeometryFields";
import { channelGeometryBounds } from "../../utils/pipetteGeometry";

function Form() {
  const [instrument, setInstrument] = useState<InstrumentConfig>({ type: "pipette", vendor: "opentrons", offset_x: 0, offset_y: 0 });
  return <><PipetteGeometryFields instrument={instrument} onChange={setInstrument} /><output>{channelGeometryBounds(instrument) ? "measured" : "incomplete"}</output></>;
}

it("requires measured dimensions and switches the reference with orientation", async () => {
  const user = userEvent.setup();
  render(<Form />);
  await user.click(screen.getByLabelText("Enable for an 8-channel model"));
  expect(screen.getByText("incomplete")).toBeInTheDocument();
  for (const [label, value] of [["Head length along row (mm)", "80"], ["Head width across row (mm)", "30"], ["Head height above nozzles (mm)", "120"]]) {
    await user.clear(screen.getByLabelText(label));
    await user.type(screen.getByLabelText(label), value);
  }
  expect(screen.getByText("measured")).toBeInTheDocument();
  expect(screen.getByText(/refers to the frontmost tip/)).toBeInTheDocument();
  await user.selectOptions(screen.getByLabelText("Channel orientation"), "x");
  expect(screen.getByText(/refers to the leftmost tip/)).toBeInTheDocument();
  await user.click(screen.getByLabelText("Enable for an 8-channel model"));
  expect(screen.queryByLabelText("Channel orientation")).not.toBeInTheDocument();
});
