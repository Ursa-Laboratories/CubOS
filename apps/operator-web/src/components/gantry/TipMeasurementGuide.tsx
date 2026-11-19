import tipPhoto from "./picus-tip.webp";

export default function TipMeasurementGuide() {
  return (
    <svg role="img" aria-label="Measure vertically from the lower edge of the black nozzle to the bottom of the attached tip."
      viewBox="0 0 280 165" width="280" style={{ display: "block", maxWidth: "100%", height: "auto" }}>
      <image href={tipPhoto} width="100" height="165" />
      <path d="M53 32.5 H100 M48 153 H100" stroke="white" strokeWidth="3" />
      <path d="M53 32.5 H118 M48 153 H118" stroke="currentColor" strokeDasharray="3 2" />
      <g fill="currentColor">
        <path d="M111 33 l-3 7 h6 Z M111 153 l-3 -7 h6 Z" />
        <rect x="110.3" y="39" width="1.4" height="108" />
        <text x="125" y="36" fontSize="13">End of black nozzle</text>
        <text x="125" y="157" fontSize="13">Bottom of tip</text>
      </g>
    </svg>
  );
}
