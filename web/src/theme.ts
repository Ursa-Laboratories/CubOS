import type { CSSProperties } from "react";

/**
 * Zoo design system tokens.
 *
 * The runtime theme lives in `index.css`: dark/default values are defined on
 * `:root, :root[data-theme="dark"]`, and light values are defined on
 * `:root[data-theme="light"]`. This module keeps the existing inline-style
 * export shape, but color and shadow values are CSS variable references so
 * components update when the root `data-theme` changes.
 */

export const color = {
  // Neutrals. "ink" stays the highest-contrast text color so component code
  // reads the same in any theme.
  ink: "var(--z-ink)",
  text: "var(--z-text)",
  textSecondary: "var(--z-text-secondary)",
  textMuted: "var(--z-text-muted)",
  textFaint: "var(--z-text-faint)",
  border: "var(--z-border)",
  borderStrong: "var(--z-border-strong)",
  canvas: "var(--z-canvas)",
  surface: "var(--z-surface)",
  surfaceMuted: "var(--z-surface-muted)",
  surfaceSunken: "var(--z-surface-sunken)",

  // Accent.
  accent: "var(--z-accent)",
  accentHover: "var(--z-accent-hover)",
  accentTint: "var(--z-accent-tint)",
  accentTintBorder: "var(--z-accent-tint-border)",
  accentText: "var(--z-accent-text)",

  // The launch surface for the one primary action.
  launchGradient: "var(--z-btn-primary-bg)",

  // Semantic - danger. #dc2626 is load-bearing: fields.test.tsx asserts it
  // as the required-field error border.
  danger: "#dc2626",
  dangerBg: "var(--z-danger-bg)",
  dangerBorder: "var(--z-danger-border)",
  dangerText: "var(--z-danger-text)",

  // Semantic - warning: unsaved edits, run-in-progress.
  warning: "var(--z-warning)",
  warningBg: "var(--z-warning-bg)",
  warningBorder: "var(--z-warning-border)",
  warningText: "var(--z-warning-text)",

  // Semantic - success: connected, valid, complete.
  success: "var(--z-success)",
  successBg: "var(--z-success-bg)",
  successBorder: "var(--z-success-border)",
  successText: "var(--z-success-text)",
} as const;

export const categorical = {
  emerald: "var(--z-cat-emerald)",
  amber: "var(--z-cat-amber)",
  violet: "var(--z-cat-violet)",
  blue: "var(--z-cat-blue)",
  slate: "var(--z-cat-slate)",
} as const;

export const viz = {
  canvas: "var(--z-viz-canvas)",
  frame: "var(--z-viz-frame)",
  grid: "var(--z-viz-grid)",
  tick: "var(--z-viz-tick)",
  caption: "var(--z-viz-caption)",
  halo: "var(--z-viz-halo)",
  plateFill: "var(--z-viz-plate-fill)",
  plateStroke: "var(--z-viz-plate-stroke)",
  wellFill: "var(--z-viz-well-fill)",
  wellStroke: "var(--z-viz-well-stroke)",
  label: "var(--z-viz-label)",
  tiprackFill: "var(--z-viz-tiprack-fill)",
  tiprackStroke: "var(--z-viz-tiprack-stroke)",
  tip: "var(--z-viz-tip)",
  holderFill: "var(--z-viz-holder-fill)",
  holderStroke: "var(--z-viz-holder-stroke)",
  holderLabel: "var(--z-viz-holder-label)",
  vialFill: "var(--z-viz-vial-fill)",
  vialStroke: "var(--z-viz-vial-stroke)",
  vialLabel: "var(--z-viz-vial-label)",
  marker: "var(--z-viz-marker)",
  markerHalo: "var(--z-viz-marker-halo)",
  markerLabel: "var(--z-viz-marker-label)",
  markerRing: "var(--z-viz-marker-ring)",
} as const;

export const chrome = {
  headerBg: "var(--z-header-bg)",
  headerHairline: "var(--z-header-hairline)",
  brandGlow: "var(--z-brand-glow)",
  segmentActiveBg: "var(--z-segment-active-bg)",
  segmentActiveShadow: "var(--z-segment-active-shadow)",
  telemetryGlow: "var(--z-telemetry-glow)",
  backdrop: "var(--z-backdrop)",
} as const;

export const font = {
  ui: 'Inter, -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", system-ui, sans-serif',
  mono: 'ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace',
} as const;

export const radius = {
  sm: 6,
  md: 8,
  lg: 12,
} as const;

export const shadow = {
  card: "var(--z-shadow-card)",
  raised: "var(--z-shadow-raised)",
  overlay: "var(--z-shadow-overlay)",
  /** Theme-specific glow for the launch action and live indicators. */
  glow: "var(--z-shadow-glow)",
} as const;

// ---------------------------------------------------------------------------
// Shared style objects
// ---------------------------------------------------------------------------

/** Card panel - the basic surface everything sits on. */
export const card: CSSProperties = {
  background: color.surface,
  border: `1px solid ${color.border}`,
  borderRadius: radius.lg,
  boxShadow: shadow.card,
};

/** Standard text/number input. */
export const input: CSSProperties = {
  background: color.surfaceSunken,
  border: `1px solid ${color.borderStrong}`,
  color: color.ink,
  padding: "5px 8px",
  borderRadius: radius.sm,
  fontSize: 13,
  lineHeight: 1.4,
};

/** Field label text above an input. */
export const fieldLabel: CSSProperties = {
  color: color.textMuted,
  fontSize: 12,
  fontWeight: 500,
};

/** Uppercase micro-label for section headers and readout captions. */
export const sectionLabel: CSSProperties = {
  color: color.textFaint,
  fontSize: 11,
  fontWeight: 600,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

/** Panel heading (card titles). */
export const panelTitle: CSSProperties = {
  margin: 0,
  fontSize: 14,
  fontWeight: 600,
  color: color.ink,
  letterSpacing: "-0.01em",
};

const btnBase: CSSProperties = {
  borderRadius: radius.sm + 1,
  padding: "6px 14px",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
  lineHeight: 1.4,
  whiteSpace: "nowrap",
};

export const btn = {
  /** Launch button - the one primary action on a surface. */
  primary: {
    ...btnBase,
    background: "var(--z-btn-primary-bg)",
    color: "#ffffff",
    border: "1px solid var(--z-btn-primary-border)",
    boxShadow: "var(--z-btn-primary-shadow)",
    textShadow: "var(--z-btn-primary-text-shadow)",
  } as CSSProperties,

  /** Outlined button - secondary actions. */
  secondary: {
    ...btnBase,
    background: color.surfaceMuted,
    color: color.text,
    border: `1px solid ${color.borderStrong}`,
    fontWeight: 500,
  } as CSSProperties,

  /** Borderless quiet button - tertiary/inline actions. */
  ghost: {
    ...btnBase,
    background: "transparent",
    color: color.textSecondary,
    border: "1px solid transparent",
    fontWeight: 500,
  } as CSSProperties,

  /** Outlined destructive button - stop/cancel/delete. */
  danger: {
    ...btnBase,
    background: color.dangerBg,
    color: color.dangerText,
    border: `1px solid ${color.dangerBorder}`,
    fontWeight: 500,
  } as CSSProperties,
} as const;

/** Compact size variant - spread after a btn.* style. */
export const btnSmall: CSSProperties = {
  padding: "4px 10px",
  fontSize: 12,
};

const noticeBase: CSSProperties = {
  borderRadius: radius.md,
  fontSize: 12,
  lineHeight: 1.45,
  padding: "8px 12px",
};

export const notice = {
  error: {
    ...noticeBase,
    background: color.dangerBg,
    border: `1px solid ${color.dangerBorder}`,
    color: color.dangerText,
  } as CSSProperties,
  warning: {
    ...noticeBase,
    background: color.warningBg,
    border: `1px solid ${color.warningBorder}`,
    color: color.warningText,
  } as CSSProperties,
  success: {
    ...noticeBase,
    background: color.successBg,
    border: `1px solid ${color.successBorder}`,
    color: color.successText,
  } as CSSProperties,
  info: {
    ...noticeBase,
    background: color.accentTint,
    border: `1px solid ${color.accentTintBorder}`,
    color: color.accentText,
  } as CSSProperties,
} as const;

/** Small rounded status pill (e.g. "Connected", "Running"). */
export const pill: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  borderRadius: 999,
  padding: "3px 10px",
  fontSize: 12,
  fontWeight: 500,
  lineHeight: 1.4,
};

/** Monospace numeric/text readout (coordinates, filenames, YAML). */
export const mono: CSSProperties = {
  fontFamily: font.mono,
  fontVariantNumeric: "tabular-nums",
};
