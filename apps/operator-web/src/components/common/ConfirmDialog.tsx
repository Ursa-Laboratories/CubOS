import React, { useEffect, useRef } from "react";
import * as theme from "../../theme";

/**
 * In-app replacement for window.confirm. Native dialogs are silently
 * auto-dismissed (returning false) in embedded browser panes, which made
 * confirm-gated actions like Home and discard-changes appear broken there.
 */

export interface ConfirmOptions {
  message: string;
  title?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Style the confirm button as destructive (discard flows). */
  danger?: boolean;
}

interface ConfirmDialogProps extends ConfirmOptions {
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  message,
  title,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    confirmRef.current?.focus();
  }, []);

  return (
    <div
      style={overlayStyle}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-label={title ?? message}
        style={dialogStyle}
        onKeyDown={(event) => {
          // stopPropagation keeps Escape (and any other key) from reaching
          // window-level handlers like the gantry keyboard-jog listener.
          event.stopPropagation();
          if (event.key === "Escape") onCancel();
        }}
      >
        {title && <h3 style={titleStyle}>{title}</h3>}
        <p style={messageStyle}>{message}</p>
        <div style={actionsStyle}>
          <button type="button" onClick={onCancel} style={theme.btn.secondary}>
            {cancelLabel}
          </button>
          <button
            type="button"
            ref={confirmRef}
            onClick={onConfirm}
            style={danger ? theme.btn.danger : theme.btn.primary}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

// Above the calibration wizard overlay (zIndex 50) so a confirm is never
// buried under another modal surface.
const overlayStyle: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  background: theme.chrome.backdrop,
  zIndex: 60,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: 24,
};

const dialogStyle: React.CSSProperties = {
  width: "min(400px, 92vw)",
  background: theme.color.surface,
  border: `1px solid ${theme.color.border}`,
  borderRadius: theme.radius.lg,
  boxShadow: theme.shadow.overlay,
  padding: 18,
};

const titleStyle: React.CSSProperties = {
  ...theme.panelTitle,
  fontSize: 15,
  margin: "0 0 8px",
};

const messageStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 13,
  lineHeight: 1.5,
  color: theme.color.text,
};

const actionsStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
  gap: 8,
  marginTop: 16,
};
