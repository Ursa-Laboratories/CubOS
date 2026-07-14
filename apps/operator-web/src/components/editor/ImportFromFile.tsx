import * as theme from "../../theme";

interface Props {
  configs: string[];
  onSelectFile: (f: string) => void;
  label: string;
}

export default function ImportFromFile({ configs, onSelectFile, label }: Props) {
  const displayLabel = label.replace(/^Import\s+/i, "").replace(/\s+config$/i, "");
  const placeholder = configs.length > 0 ? `Choose ${displayLabel.toLowerCase()}...` : "No configs found";

  return (
    <label style={wrapperStyle}>
      <span style={labelStyle}>{displayLabel}</span>
      <select
        aria-label={label}
        value=""
        onChange={(e) => {
          if (e.target.value) {
            onSelectFile(e.target.value);
          }
        }}
        style={selectStyle}
      >
        <option value="" disabled>{placeholder}</option>
        {configs.map((c) => (
          <option key={c} value={c}>{c}</option>
        ))}
      </select>
    </label>
  );
}

const wrapperStyle: React.CSSProperties = {
  display: "grid",
  gap: 4,
  minWidth: 0,
  width: "min(100%, 340px)",
  flex: "0 1 340px",
};

const labelStyle: React.CSSProperties = {
  ...theme.sectionLabel,
};

const selectStyle: React.CSSProperties = {
  ...theme.input,
  height: 34,
  padding: "0 10px",
  width: "100%",
};
