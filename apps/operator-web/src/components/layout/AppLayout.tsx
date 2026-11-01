import type { ReactNode } from "react";
import { card, chrome, color } from "../../theme";
import "./AppLayout.css";

interface Props {
  banner?: ReactNode;
  header: ReactNode;
  left: ReactNode;
  topRight: ReactNode;
  bottomRight: ReactNode;
}

export default function AppLayout({ banner, header, left, topRight, bottomRight }: Props) {
  return (
    <div className="operator-layout" style={{ background: color.canvas }}>
      {banner}
      <header
        className="operator-header"
        style={{
          background: chrome.headerBg,
          borderBottom: `1px solid ${color.border}`,
          boxShadow: chrome.headerHairline,
        }}
      >
        {header}
      </header>
      <div className="operator-workspace">
        <section className="operator-editor" style={card}>
          {left}
        </section>
        <section className="operator-preview" style={card}>
          {topRight}
        </section>
        <section className="operator-controls" style={card}>
          {bottomRight}
        </section>
      </div>
    </div>
  );
}
