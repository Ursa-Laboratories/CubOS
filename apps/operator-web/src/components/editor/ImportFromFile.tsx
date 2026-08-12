import * as theme from "../../theme";

interface Props {
  configs: string[];
  onSelectFile: (f: string) => void;
  label: string;
  /** Currently loaded config file; shown as the selected option. */
  selectedFile?: string | null;
}

export default function ImportFromFile({ configs, onSelectFile, label, selectedFile }: Props) {
  const displayLabel = label.replace(/^Import\s+/i, "").replace(/\s+config$/i, "");
  const placeholder = configs.length > 0 ? `Choose ${displayLabel.toLowerCase()}...` : "No configs found";
  const value = selectedFile && configs.includes(selectedFile) ? selectedFile : "";

  return (
    <label style={wrapperStyle}>
      <span style={labelStyle}>{displayLabel}</span>
      <select
        aria-label={label}
        value={value}
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
