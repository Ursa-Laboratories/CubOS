import { useState, type ReactNode } from "react";
import type { CommandInfo, LabwareResponse, ProtocolStep } from "../../types";
import type { RepeatArgs } from "./protocolRepeat";
import { PlatePreview, WellPlateSelector } from "./WellPlateSelector";
import { replaceWellTarget } from "./protocolRepeat";

interface Props {
  value: RepeatArgs;
  index: number;
  labware: LabwareResponse[];
  commands: CommandInfo[];
  onChange: (value: RepeatArgs) => void;
  onRemove: () => void;
  onMove: (direction: -1 | 1) => void;
  first: boolean;
  last: boolean;
  createStep: (command: string) => ProtocolStep;
  renderChild: (step: ProtocolStep, index: number) => ReactNode;
}

export default function RepeatBlockEditor({ value, index, labware, commands, onChange, onRemove,
  onMove, first, last, createStep, renderChild }: Props) {
  const [open, setOpen] = useState(true);
  const [command, setCommand] = useState(commands[0]?.name ?? "move");
  const entry = labware.find(item => item.key === value.labware);
  const wells = Object.keys(entry?.wells ?? {});
  const setChildren = (children: ProtocolStep[]) => onChange({ ...value, steps: children });
  const changeTarget = (key: string, template: string, targets: string[]) => {
    const source = `${value.labware}.${value.template_well}`;
    const destination = `${key}.${template}`;
    onChange({ ...value, labware: key, template_well: template, wells: targets,
      steps: value.steps.map(step => ({ ...step, args: replaceWellTarget(step.args, source, destination) as Record<string, unknown> })),
    });
  };
  return <section className="repeat-panel repeat-block" aria-label={`Repeat block ${index + 1}`}>
    <div className="repeat-block-header">
      <button type="button" className="repeat-heading" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span>Repeat {index + 1} <span className="repeat-heading-action">· {value.labware} · {value.wells.length} {value.wells.length === 1 ? "well" : "wells"} · {value.steps.length} {value.steps.length === 1 ? "step" : "steps"}</span></span>
        <span className="repeat-heading-action">{open ? "Minimize −" : "Expand +"}</span>
      </button>
      <div className="repeat-block-actions">
        <button type="button" aria-label={`Move repeat ${index + 1} up`} disabled={first} onClick={() => onMove(-1)}>↑</button>
        <button type="button" aria-label={`Move repeat ${index + 1} down`} disabled={last} onClick={() => onMove(1)}>↓</button>
        <button type="button" aria-label={`Remove repeat ${index + 1}`} onClick={onRemove}>×</button>
      </div>
    </div>
    {open && <div className="repeat-body">
      <div className="repeat-labware" role="group" aria-label={`Repeat ${index + 1} labware`}>
        {labware.map(item => <button type="button" key={item.key} className="repeat-labware-choice"
          aria-label={`Use ${item.key} for repeat ${index + 1}`} aria-pressed={item.key === value.labware}
          onClick={() => {
            if (item.key === value.labware) return;
            const ids = Object.keys(item.wells ?? {});
            changeTarget(item.key, ids[0] ?? "", ids);
          }}><PlatePreview wells={Object.keys(item.wells ?? {})} /><span>{item.key}</span></button>)}
      </div>
      {!entry && <p role="alert">Plate {value.labware} is not on the loaded deck.</p>}
      {entry && value.wells.some(well => !wells.includes(well)) && <p role="alert">
        Missing wells: {value.wells.filter(well => !wells.includes(well)).join(", ")}
      </p>}
      <label className="repeat-template-label">Template well
        <select aria-label={`Repeat ${index + 1} template well`} value={value.template_well}
          onChange={event => changeTarget(value.labware, event.target.value, value.wells)}>
          {[...new Set([value.template_well, ...wells])].map(well => <option key={well}>{well}</option>)}
        </select>
      </label>
      <WellPlateSelector wells={wells} selected={value.wells} template={value.template_well}
        onChange={targets => onChange({ ...value, wells: targets })} />
      <div className="repeat-children">
        {value.steps.map((step, childIndex) => <div className="repeat-child" key={childIndex}>
          <div className="repeat-child-heading"><strong>{childIndex + 1}. {step.command}</strong>
            <div className="repeat-block-actions">
              {([-1, 1] as const).map(direction => <button type="button" key={direction}
                aria-label={`Move repeat ${index + 1} step ${childIndex + 1} ${direction === -1 ? "up" : "down"}`}
                disabled={childIndex + direction < 0 || childIndex + direction >= value.steps.length}
                onClick={() => { const next = [...value.steps]; [next[childIndex], next[childIndex + direction]] = [next[childIndex + direction], next[childIndex]]; setChildren(next); }}>
                {direction === -1 ? "↑" : "↓"}</button>)}
              <button type="button" aria-label={`Remove repeat ${index + 1} step ${childIndex + 1}`}
                onClick={() => setChildren(value.steps.filter((_, j) => j !== childIndex))}>×</button>
            </div>
          </div>
          {renderChild(step, childIndex)}
        </div>)}
      </div>
      <div className="repeat-add-child">
        <select aria-label={`Add step to repeat ${index + 1}`} value={command} onChange={event => setCommand(event.target.value)}>
          {commands.map(item => <option key={item.name} value={item.name}>{item.name}</option>)}
        </select>
        <button type="button" className="repeat-child-add-button" disabled={!commands.some(item => item.name === command)} onClick={() => setChildren([...value.steps, createStep(command)])}>Add step to repeat</button>
      </div>
    </div>}
  </section>;
}
