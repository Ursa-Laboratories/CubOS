import { useState } from "react";
import type { CSSProperties } from "react";
import { dataApi } from "../../api/client";
import type { CampaignSummary } from "../../types";
import * as theme from "../../theme";

interface Props {
  campaigns: CampaignSummary[];
  isLoading: boolean;
  error: unknown;
  onRefresh: () => void;
}

type ExportKind = "measurements" | "asmi";

type ExportingState = {
  campaignId: number;
  kind: ExportKind;
};

export default function DataOutputPanel({
  campaigns,
  isLoading,
  error,
  onRefresh,
}: Props) {
  const [exporting, setExporting] = useState<ExportingState | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const handleExport = async (campaign: CampaignSummary, kind: ExportKind) => {
    setExporting({ campaignId: campaign.campaign_id, kind });
    setExportError(null);
    try {
      const blob = kind === "measurements"
        ? await dataApi.exportCampaignMeasurementsZip(campaign.campaign_id)
        : await dataApi.exportCampaignAsmiZip(campaign.campaign_id);
      const href = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = href;
      link.download = kind === "measurements"
        ? `campaign_${campaign.campaign_id}_measurements.zip`
        : `campaign_${campaign.campaign_id}_asmi_raw_csvs.zip`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(href);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : String(err));
    } finally {
      setExporting(null);
    }
  };

  return (
    <section style={panelStyle} aria-label="Campaign results output">
      <div style={headerStyle}>
        <div>
          <h3 style={titleStyle}>Campaign Results</h3>
          <div style={subtitleStyle}>Stored instrument measurement output</div>
        </div>
        <button onClick={onRefresh} style={secondaryButtonStyle}>
          Refresh
        </button>
      </div>

      {Boolean(error) && (
        <div style={errorStyle}>Data load failed: {error instanceof Error ? error.message : String(error)}</div>
      )}
      {exportError && (
        <div style={errorStyle}>Export failed: {exportError}</div>
      )}
      {isLoading && <div style={emptyStyle}>Loading campaigns...</div>}
      {!isLoading && campaigns.length === 0 && (
        <div style={emptyStyle}>No campaigns yet — run a protocol to create one.</div>
      )}
      {!isLoading && campaigns.length > 0 && (
        <div style={tableFrameStyle}>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Campaign</th>
                <th style={thStyle}>Last measured</th>
                <th style={thStyle}>Experiments</th>
                <th style={thStyle}>Wells</th>
                <th style={thStyle}>Measurements</th>
                <th style={thStyle}>Export</th>
              </tr>
            </thead>
            <tbody>
              {campaigns.map((campaign) => {
                const measurementsDisabled = campaign.measurement_count === 0 || exporting !== null;
                const asmiDisabled = campaign.asmi_measurement_count === 0 || exporting !== null;
                const timestamp = campaign.latest_measurement_at ?? campaign.created_at;
                return (
                  <tr key={campaign.campaign_id}>
                    <td style={tdStyle}>
                      <div style={strongTextStyle}>Campaign #{campaign.campaign_id}</div>
                      <div style={metaTextStyle}>{campaign.campaign_description}</div>
                    </td>
                    <td style={tdStyle}>{formatTimestamp(timestamp)}</td>
                    <td style={tdNumericStyle}>{campaign.experiment_count}</td>
                    <td style={tdNumericStyle}>{campaign.well_count}</td>
                    <td style={tdNumericStyle}>{campaign.measurement_count}</td>
                    <td style={tdStyle}>
                      <button
                        onClick={() => void handleExport(campaign, "measurements")}
                        disabled={measurementsDisabled}
                        style={primaryButtonStyle}
                      >
                        {isExporting(exporting, campaign.campaign_id, "measurements") ? "Exporting..." : "Measurements ZIP"}
                      </button>
                      <button
                        onClick={() => void handleExport(campaign, "asmi")}
                        disabled={asmiDisabled}
                        style={secondaryExportButtonStyle}
                      >
                        {isExporting(exporting, campaign.campaign_id, "asmi") ? "Exporting..." : "ASMI ZIP"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function isExporting(exporting: ExportingState | null, campaignId: number, kind: ExportKind): boolean {
  return exporting?.campaignId === campaignId && exporting.kind === kind;
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

// The panel sits inside the shared card shell, so it stays borderless-clean.
const panelStyle: CSSProperties = {
  overflow: "hidden",
};

const headerStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  padding: "12px 14px",
  borderBottom: `1px solid ${theme.color.border}`,
};

const titleStyle: CSSProperties = {
  ...theme.panelTitle,
};

const subtitleStyle: CSSProperties = {
  marginTop: 2,
  color: theme.color.textMuted,
  fontSize: 12,
};

const tableFrameStyle: CSSProperties = {
  overflowX: "auto",
};

const tableStyle: CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  fontSize: 13,
  color: theme.color.text,
};

const thStyle: CSSProperties = {
  ...theme.sectionLabel,
  padding: "9px 12px",
  textAlign: "left",
  borderBottom: `1px solid ${theme.color.border}`,
};

const tdStyle: CSSProperties = {
  padding: "10px 12px",
  borderBottom: `1px solid ${theme.color.border}`,
  verticalAlign: "middle",
};

const tdNumericStyle: CSSProperties = {
  ...tdStyle,
  ...theme.mono,
};

const strongTextStyle: CSSProperties = {
  fontWeight: 600,
  color: theme.color.ink,
};

const metaTextStyle: CSSProperties = {
  marginTop: 2,
  color: theme.color.textMuted,
  fontSize: 12,
};

const emptyStyle: CSSProperties = {
  padding: "24px 16px",
  color: theme.color.textMuted,
  fontSize: 13,
  textAlign: "center",
};

const errorStyle: CSSProperties = {
  ...theme.notice.error,
  margin: 12,
};

const primaryButtonStyle: CSSProperties = {
  ...theme.btn.primary,
  ...theme.btnSmall,
  marginRight: 6,
};

const secondaryExportButtonStyle: CSSProperties = {
  ...theme.btn.secondary,
  ...theme.btnSmall,
};

const secondaryButtonStyle: CSSProperties = {
  ...theme.btn.secondary,
  ...theme.btnSmall,
};
