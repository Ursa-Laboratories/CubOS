import type { EightChannelGeometry, InstrumentConfig } from "../../types";
import { NumberField } from "./fields";
import * as theme from "../../theme";

export default function PipetteGeometryFields({ instrument, onChange }: {
  instrument: InstrumentConfig;
  onChange: (next: InstrumentConfig) => void;
}) {
  const geometry = instrument.channel_geometry;
  const set = (value: EightChannelGeometry) => onChange({ ...instrument, channel_geometry: value });
  return <fieldset style={{ border: `1px solid ${theme.color.border}`, marginTop: 12 }}>
    <legend>8-channel head geometry</legend>
    <label><input type="checkbox" checked={!!geometry} onChange={event => {
      if (event.target.checked) set({ axis: "y", spacing_mm: 9, length_mm: 0, width_mm: 0, height_mm: 0 });
      else {
        const next = { ...instrument };
        delete next.channel_geometry;
        onChange(next);
      }
    }} />Enable for an 8-channel model</label>
    {geometry && <>
      <p style={{ fontSize: 12 }}>Measure the full swept head, including the mount. Length runs along the tip row; width runs across it; height is above the bare nozzles. Length must exceed seven tip spacings. Use an envelope centered on the tip row that covers both sides of any asymmetric body.</p>
      <label>Channel orientation <select style={theme.input} value={geometry.axis}
        onChange={event => set({ ...geometry, axis: event.target.value as "x" | "y" })}>
        <option value="x">Left to right (+X), leftmost tip reference</option>
        <option value="y">Front to back (+Y), frontmost tip reference</option>
      </select></label>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 8 }}>
        {([['spacing_mm', 'Channel spacing (mm)'], ['length_mm', 'Head length along row (mm)'], ['width_mm', 'Head width across row (mm)'], ['height_mm', 'Head height above nozzles (mm)']] as const).map(([key, label]) => (
          <NumberField key={key} label={label} value={geometry[key] ?? 9} onChange={value => set({ ...geometry, [key]: value })} />
        ))}
      </div>
      <p style={{ fontSize: 12 }}>Recalibrate all offsets and labware references after changing orientation. WPos plus the pipette offset refers to the {geometry.axis === "x" ? "leftmost" : "frontmost"} tip.</p>
    </>}
  </fieldset>;
}
