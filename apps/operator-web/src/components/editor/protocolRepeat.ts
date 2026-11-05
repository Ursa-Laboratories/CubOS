import type { ProtocolStep } from "../../types";

export function replaceWellTarget(value: unknown, sourceTarget: string, targetTarget: string): unknown {
  if (typeof value === "string") return value === sourceTarget ? targetTarget : value;
  if (Array.isArray(value)) {
    return value.map((item) => replaceWellTarget(item, sourceTarget, targetTarget));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        key,
        replaceWellTarget(item, sourceTarget, targetTarget),
      ]),
    );
  }
  return value;
}

export interface RepeatArgs extends Record<string, unknown> {
  labware: string;
  template_well: string;
  wells: string[];
  steps: ProtocolStep[];
}

export function repeatArgs(step: ProtocolStep): RepeatArgs | null {
  if (step.command !== "repeat") return null;
  const { labware, template_well, wells, steps } = step.args;
  if (typeof labware !== "string" || typeof template_well !== "string"
      || !Array.isArray(wells) || !wells.every(well => typeof well === "string")
      || !Array.isArray(steps) || !steps.every(child => child && typeof child === "object"
        && typeof child.command === "string" && child.command !== "repeat"
        && child.args && typeof child.args === "object" && !Array.isArray(child.args))) return null;
  return step.args as RepeatArgs;
}

export function createRepeatBlock(
  steps: ProtocolStep[], start: number, end: number, labware: string, template: string, wells: string[],
): ProtocolStep[] {
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end < start || end > steps.length) {
    throw new Error(`Choose a valid step range between 1 and ${steps.length}.`);
  }
  if (!labware || !template || wells.length === 0) throw new Error("Choose a plate, template well, and target wells.");
  const children = steps.slice(start - 1, end);
  if (children.some(step => step.command === "repeat")) throw new Error("A repeat cannot contain another repeat.");
  return [...steps.slice(0, start - 1), { command: "repeat", args: {
    labware, template_well: template, wells: [...wells], steps: structuredClone(children),
  } }, ...steps.slice(end)];
}

export function stepToYaml(step: ProtocolStep): Record<string, unknown> {
  const repeat = repeatArgs(step);
  return { [step.command]: repeat ? { ...repeat, steps: repeat.steps.map(stepToYaml) }
    : Object.keys(step.args).length ? step.args : null };
}

export function stepsFromYaml(items: unknown[], insideRepeat = false): ProtocolStep[] {
  return items.map((item, i) => {
    if (typeof item === "string") item = { [item]: null };
    if (!item || typeof item !== "object" || Array.isArray(item) || Object.keys(item).length !== 1) {
      throw new Error(`Step ${i + 1} must have exactly one command key.`);
    }
    const [command, value] = Object.entries(item)[0];
    if (value != null && (typeof value !== "object" || Array.isArray(value))) {
      throw new Error(`Step ${i + 1} (${command}) args must be a mapping.`);
    }
    const args = { ...(value ?? {}) } as Record<string, unknown>;
    if (command === "repeat") {
      if (insideRepeat) throw new Error("A repeat cannot contain another repeat.");
      if (!Array.isArray(args.steps)) throw new Error("Repeat steps must be a list.");
      args.steps = stepsFromYaml(args.steps, true);
      const candidate = { command, args };
      const repeat = repeatArgs(candidate);
      if (!repeat || !repeat.labware || !repeat.template_well || !repeat.wells.length || !repeat.steps.length) {
        throw new Error("Repeat requires a plate, template well, target wells, and steps.");
      }
    }
    return { command, args };
  });
}
