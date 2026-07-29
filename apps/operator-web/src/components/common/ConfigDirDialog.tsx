import React, { useEffect, useRef, useState } from "react";
import * as theme from "../../theme";

/**
 * In-app fallback for the config-directory Browse action. The
 * `/settings/browse` endpoint opens a native picker on the machine
 * running the API; on a headless or remote appliance there is no
 * display to open it on, so Browse must still respond with a way to
 * enter the directory path directly.
 */

interface ConfigDirDialogProps {
  initialPath: string;
  error: string | null;
  onSubmit: (path: string) => void;
  onCancel: () => void;
}

export function ConfigDirDialog({
  initialPath,
  error,
  onSubmit,
  onCancel,
}: ConfigDirDialogProps) {
  const [path, setPath] = useState(initialPath);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  return (
    <div
      style={overlayStyle}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Select config directory"
        style={dialogStyle}
        onKeyDown={(event) => {
          // stopPropagation keeps Escape (and any other key) from reaching
          // window-level handlers like the gantry keyboard-jog listener.
          event.stopPropagation();
          if (event.key === "Escape") onCancel();
        }}
      >
        <h3 style={titleStyle}>Select config directory</h3>
        <p style={messageStyle}>
          Enter the path of a config directory on the CubOS machine.
        </p>
        <input
          ref={inputRef}
          aria-label="Config directory path"
          value={path}
          onChange={(event) => setPath(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && path.trim()) onSubmit(path.trim());
          }}
          style={inputStyle}
          spellCheck={false}
        />
        {error && (
          <p role="alert" style={errorStyle}>{error}</p>
        )}
        <div style={actionsStyle}>
          <button type="button" onClick={onCancel} style={theme.btn.secondary}>
            Cancel
          </button>
          <button
            type="button"
            onClick={() => onSubmit(path.trim())}
            disabled={!path.trim()}
            style={theme.btn.primary}
          >
            Use Directory
          </button>
        </div>
      </div>
    </div>
  );
}

// Same layer as ConfirmDialog: above the calibration wizard overlay
// (zIndex 50) so the dialog is never buried under another modal surface.
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
  width: "min(460px, 92vw)",
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
  margin: "0 0 10px",
  fontSize: 13,
  lineHeight: 1.5,
  color: theme.color.text,
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  padding: "7px 9px",
  fontSize: 13,
  fontFamily: theme.font.mono,
  color: theme.color.text,
  background: theme.color.surfaceMuted,
  border: `1px solid ${theme.color.border}`,
  borderRadius: theme.radius.md,
};

const errorStyle: React.CSSProperties = {
  margin: "8px 0 0",
  fontSize: 12,
  color: theme.color.danger,
};

const actionsStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
  gap: 8,
  marginTop: 16,
};
