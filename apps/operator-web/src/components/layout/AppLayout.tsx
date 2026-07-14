import type { ReactNode } from "react";
import { card, chrome, color } from "../../theme";

interface Props {
  header: ReactNode;
  left: ReactNode;
  topRight: ReactNode;
  bottomRight: ReactNode;
}

export default function AppLayout({ header, left, topRight, bottomRight }: Props) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        background: color.canvas,
      }}
    >
      <header
        style={{
          flex: "0 0 auto",
          display: "flex",
          alignItems: "center",
          gap: 16,
          minHeight: 56,
          padding: "8px 16px",
          background: chrome.headerBg,
          borderBottom: `1px solid ${color.border}`,
          boxShadow: chrome.headerHairline,
        }}
      >
        {header}
      </header>
      <div
        style={{
          flex: "1 1 auto",
          minHeight: 0,
          display: "grid",
          gridTemplateColumns: "minmax(0, 3fr) minmax(0, 2fr)",
          gridTemplateRows: "minmax(0, 1fr) auto",
          gap: 14,
          padding: 14,
        }}
      >
        <section
          style={{
            ...card,
            gridRow: "1 / 3",
            gridColumn: "1",
            overflow: "auto",
            padding: 18,
          }}
        >
          {left}
        </section>
        <section
          style={{
            ...card,
            gridRow: "1",
            gridColumn: "2",
            overflow: "hidden",
            padding: 16,
            minHeight: 0,
            display: "flex",
            flexDirection: "column",
          }}
        >
          {topRight}
        </section>
        <section
          style={{
            ...card,
            gridRow: "2",
            gridColumn: "2",
            padding: 16,
            overflow: "hidden",
          }}
        >
          {bottomRight}
        </section>
      </div>
    </div>
  );
}
