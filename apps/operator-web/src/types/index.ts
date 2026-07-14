// Mirrors backend Pydantic models

export interface Coordinate3D {
  x: number;
  y: number;
  z: number;
}

export interface Coordinate2D {
  x: number;
  y: number;
}

export interface CalibrationPoints {
  a1: Coordinate3D | null;
  a2: Coordinate3D;
}

export interface WellPlateConfig {
  type: "well_plate";
  name: string;
  model_name: string;
  rows: number;
  columns: number;
  length?: number | null;
  width?: number | null;
  height?: number | null;
  well_depth?: number | null;
  a1?: Coordinate3D | null;
  calibration: CalibrationPoints;
  x_offset: number;
  y_offset: number;
  capacity_ul?: number | null;
  working_volume_ul?: number | null;
}

export interface VialConfig {
  type: "vial";
  name: string;
  model_name: string;
  height: number;
  diameter: number;
  location: Coordinate3D;
  capacity_ul: number;
  working_volume_ul: number;
}

export interface TipRackConfig {
  type: "tip_rack";
  name: string;
  model_name: string;
  load_name?: string;
  rows?: number;
  columns?: number;
  z_pickup?: number;
  z_drop?: number;
  tips?: Record<string, WellPosition>;
  tip_present?: Record<string, boolean>;
  [key: string]: unknown;
}

export interface NestedWellPlateConfig {
  name?: string;
  model_name: string;
  rows: number;
  columns: number;
  calibration: {
    a1: Coordinate2D | Coordinate3D | null;
    a2: Coordinate2D | Coordinate3D;
  };
  x_offset: number;
  y_offset: number;
  length?: number | null;
  width?: number | null;
  height?: number | null;
  well_depth?: number | null;
  capacity_ul?: number;
  working_volume_ul?: number;
  [key: string]: unknown;
}

export interface NestedVialConfig {
  name?: string;
  model_name: string;
  height: number;
  diameter: number;
  location: Coordinate2D | Coordinate3D;
  capacity_ul: number;
  working_volume_ul: number;
  [key: string]: unknown;
}

export interface WellPlateHolderConfig {
  type: "well_plate_holder";
  name: string;
  model_name?: string;
  location?: Coordinate3D;
  well_plate?: NestedWellPlateConfig | null;
  [key: string]: unknown;
}

export interface VialHolderConfig {
  type: "vial_holder";
  name: string;
  model_name?: string;
  location?: Coordinate3D;
  vials?: Record<string, NestedVialConfig>;
  [key: string]: unknown;
}

export interface TipDisposalConfig {
  type: "tip_disposal";
  name: string;
  model_name?: string;
  location?: Coordinate3D;
  [key: string]: unknown;
}

export type UnsupportedDeckConfig =
  | TipRackConfig
  | WellPlateHolderConfig
  | VialHolderConfig
  | TipDisposalConfig;

export type LabwareConfig = WellPlateConfig | VialConfig | UnsupportedDeckConfig;

export interface WellPosition {
  x: number;
  y: number;
  z: number;
}

export interface GeometryResponse {
  length: number | null;
  width: number | null;
  height: number | null;
}

export interface LabwareResponse {
  key: string;
  config: LabwareConfig;
  wells: Record<string, WellPosition> | null;
  location?: Coordinate3D;
  geometry?: GeometryResponse;
  positions?: Record<string, WellPosition>;
}

export interface DeckResponse {
  filename: string;
  labware: LabwareResponse[];
}

export interface DeckConfig {
  labware: Record<string, LabwareConfig>;
}

export interface InstrumentConfig {
  type: string;
  vendor: string;
  offset_x: number;
  offset_y: number;
  depth?: number;
  [key: string]: unknown;
}

export interface WorkingVolume {
  x_min: number;
  x_max: number;
  y_min: number;
  y_max: number;
  z_min: number;
  z_max: number;
}

export interface CncConfig {
  factory_z_travel_mm: number;
  total_z_range?: number;
  total_z_height?: number;
  calibration_block_height_mm?: number | null;
  y_axis_motion?: "head" | "bed";
  safe_z?: number | null;
}

export interface GrblSettingsConfig {
  dir_invert_mask?: number | null;
  status_report?: number | null;
  soft_limits?: boolean | null;
  hard_limits?: boolean | null;
  homing_enable?: boolean | null;
  homing_dir_mask?: number | null;
  homing_pull_off?: number | null;
  steps_per_mm_x?: number | null;
  steps_per_mm_y?: number | null;
  steps_per_mm_z?: number | null;
  max_rate_x?: number | null;
  max_rate_y?: number | null;
  max_rate_z?: number | null;
  accel_x?: number | null;
  accel_y?: number | null;
  accel_z?: number | null;
  max_travel_x?: number | null;
  max_travel_y?: number | null;
  max_travel_z?: number | null;
}

export interface GantryConfig {
  serial_port: string;
  gantry_type: "cub" | "cub_xl";
  cnc: CncConfig;
  working_volume: WorkingVolume;
  grbl_settings?: GrblSettingsConfig | null;
  instruments: Record<string, InstrumentConfig>;
}

export interface GantryResponse {
  filename: string;
  config: GantryConfig;
}

export interface GantryPosition {
  x: number;
  y: number;
  z: number;
  work_x: number | null;
  work_y: number | null;
  work_z: number | null;
  status: string;
  connected: boolean;
  calibration_active: boolean;
  calibration_warning?: string | null;
  move_error?: string | null;
}

export interface ZCalibrationSummary {
  block_height: number;
  total_z_range: number;
  home_z: number;
  block_touch_z: number;
  home_to_block_travel: number;
  remaining_below_block: number;
  can_reach_deck_bottom: boolean;
  z_min: number;
  z_max: number;
  max_travel_z: number;
}

export interface FinalizeOriginResponse {
  measured_volume: Coordinate3D;
  z_calibration: ZCalibrationSummary;
  max_travel: Coordinate3D;
  position: Coordinate3D;
  homing_pull_off_mm?: number | null;
}

export interface GrblSettingsResponse {
  settings: Record<string, string>;
}

export interface CampaignSummary {
  campaign_id: number;
  campaign_description: string;
  created_at: string;
  latest_measurement_at: string | null;
  experiment_count: number;
  well_count: number;
  measurement_count: number;
  measurement_counts: Record<string, number>;
  asmi_measurement_count: number;
}

export interface ProtocolRunResponse {
  status: string;
  steps_executed: number;
  campaign_id: number;
}

export interface ProtocolRunStatus {
  active: boolean;
  protocol_file: string | null;
}

// Gantry-mounted instrument introspection (from CubOS)

export interface InstrumentTypeInfo {
  type: string;
  vendors: string[];
  is_mock: boolean;
}

export interface PipetteModelInfo {
  name: string;
  family: string;
  channels: number;
  max_volume: number;
  min_volume: number;
}

export interface InstrumentFieldInfo {
  name: string;
  type: string;
  required: boolean;
  default: unknown;
  choices: string[] | null;
}

export type InstrumentSchemas = Record<string, Record<string, InstrumentFieldInfo[]>>;

export type InstrumentMeasurementMethods = Record<string, string[]>;

// Protocol

export interface CommandArg {
  name: string;
  type: string;
  required: boolean;
  default: unknown;
}

export interface CommandInfo {
  name: string;
  args: CommandArg[];
  description: string;
}

export interface ProtocolStep {
  command: string;
  args: Record<string, unknown>;
}

export interface ProtocolConfig {
  positions?: Record<string, number[]> | null;
  protocol: ProtocolStep[];
}

export interface ProtocolResponse {
  filename: string;
  positions?: Record<string, number[]> | null;
  steps: ProtocolStep[];
}

export interface ProtocolValidationResponse {
  valid: boolean;
  errors: string[];
  output?: string;
}

export interface ProtocolSetupValidationRequest {
  gantry_file: string;
  deck_file: string;
  protocol_file: string;
}
