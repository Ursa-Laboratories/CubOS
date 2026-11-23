import type { ReactNode } from "react";
import * as theme from "../../theme";
import styles from "./CalibrationWizard.module.css";

type Props = {
  message: string | null;
  alarm: boolean;
  tone: "error" | "warning" | "info" | "idle";
  action?: ReactNode;
  children?: ReactNode;
};

export default function CalibrationStatusBanner({ message, alarm, tone, action, children }: Props) {
  const appearance = tone === "idle" ? { border: "1px solid transparent" }
    : theme.notice[tone];
  return <div data-testid="calibration-status-slot" className={styles.statusSlot} style={appearance}
    role={tone === "error" ? "alert" : "status"} aria-label="Calibration status">
    <div className={styles.statusMessage} role="region" aria-label="Calibration message" tabIndex={message ? 0 : undefined}>
      {alarm && <strong style={{ color: theme.color.danger, fontSize: 11 }}>GANTRY ALARM</strong>}
      {message && <div>{message}</div>}
      {children}
    </div>
    <div className={styles.statusAction}>{action}</div>
  </div>;
}
