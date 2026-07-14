import { describe, expect, it } from "vitest";
import {
  buildCalibratedConfig,
  calculateSingleInstrumentZCalibration,
  DEFAULT_HOMING_PULL_OFF_MM,
  getCalibrationBlockHeight,
  getConfiguredHomingPullOff,
  getFactoryZTravel,
} from "./calibrationMath";
import type { GantryConfig } from "../../types";

function gantryConfig(): GantryConfig {
  return {
    serial_port: "/dev/ttyUSB0",
    gantry_type: "cub_xl",
    cnc: {
      factory_z_travel_mm: 110,
      calibration_block_height_mm: 35,
      y_axis_motion: "head",
      safe_z: 120,
    },
    working_volume: {
      x_min: 0,
      x_max: 300,
      y_min: 0,
      y_max: 200,
      z_min: 0,
      z_max: 80,
    },
    grbl_settings: {
      max_travel_z: 80,
    },
    instruments: {
      asmi: {
        type: "asmi",
        vendor: "vernier",
        offset_x: 0,
        offset_y: 0,
        depth: 0,
      },
    },
  };
}

describe("factory Z calibration inputs", () => {
  it("returns rounded factory_z_travel_mm from config", () => {
    expect(getFactoryZTravel(gantryConfig())).toBe(110);
    expect(getCalibrationBlockHeight(gantryConfig())).toBe(35);
  });

  it("accepts total_z_range from older CubOS gantry payloads", () => {
    const config = gantryConfig();
    delete (config.cnc as unknown as Record<string, unknown>).factory_z_travel_mm;
    config.cnc.total_z_range = 87;
    expect(getFactoryZTravel(config)).toBe(87);
  });

  it("throws when factory_z_travel_mm is missing", () => {
    const config = gantryConfig();
    delete (config.cnc as unknown as Record<string, unknown>).factory_z_travel_mm;
    expect(() => getFactoryZTravel(config)).toThrow("cnc.factory_z_travel_mm");
  });

  it("throws when factory_z_travel_mm is zero", () => {
    const config = gantryConfig();
    config.cnc.factory_z_travel_mm = 0;
    expect(() => getFactoryZTravel(config)).toThrow("cnc.factory_z_travel_mm");
  });

  it("throws when factory_z_travel_mm is negative", () => {
    const config = gantryConfig();
    config.cnc.factory_z_travel_mm = -50;
    expect(() => getFactoryZTravel(config)).toThrow("cnc.factory_z_travel_mm");
  });

  it("throws when calibration_block_height_mm is missing", () => {
    const config = gantryConfig();
    delete (config.cnc as unknown as Record<string, unknown>).calibration_block_height_mm;
    expect(() => getCalibrationBlockHeight(config)).toThrow("cnc.calibration_block_height_mm");
  });

  it("defaults the homing pull-off when the YAML doesn't seed one", () => {
    const config = gantryConfig();
    expect(getConfiguredHomingPullOff(config)).toBe(DEFAULT_HOMING_PULL_OFF_MM);
    config.grbl_settings = { ...config.grbl_settings, homing_pull_off: 10 };
    expect(getConfiguredHomingPullOff(config)).toBe(10);
  });

  it("still rejects an explicitly invalid homing pull-off", () => {
    const config = gantryConfig();
    config.grbl_settings = { ...config.grbl_settings, homing_pull_off: -5 };
    expect(() => getConfiguredHomingPullOff(config)).toThrow("non-negative");
  });
});

describe("calculateSingleInstrumentZCalibration", () => {
  it("handles scenario A where the instrument reaches deck bottom", () => {
    expect(calculateSingleInstrumentZCalibration({
      homeZ: 110,
      blockTouchZ: 60,
      blockHeight: 35,
      factoryZTravel: 110,
      homedZ: 85,
    })).toMatchObject({
      homeToBlockTravel: 50,
      remainingBelowBlock: 60,
      canReachDeckBottom: true,
      zMin: 0,
      zMax: 85,
      maxTravelZ: 85,
    });
  });

  it("handles scenario B where the instrument cannot reach deck bottom", () => {
    expect(calculateSingleInstrumentZCalibration({
      homeZ: 110,
      blockTouchZ: 10,
      blockHeight: 35,
      factoryZTravel: 110,
      homedZ: 135,
    })).toMatchObject({
      homeToBlockTravel: 100,
      remainingBelowBlock: 10,
      canReachDeckBottom: false,
      zMin: 25,
      zMax: 135,
      maxTravelZ: 110,
    });
  });

  it("estimates zMax from travel when homedZ is omitted", () => {
    const result = calculateSingleInstrumentZCalibration({
      homeZ: 110,
      blockTouchZ: 60,
      blockHeight: 35,
      factoryZTravel: 110,
    });
    // homeToBlockTravel = 110 - 60 = 50; estimated zMax = 50 + 35 = 85
    expect(result.homeToBlockTravel).toBe(50);
    expect(result.zMax).toBe(85);
    expect(result.zMin).toBe(0);
    expect(result.maxTravelZ).toBe(85);
  });

  it("throws when blockTouchZ is at or above homeZ", () => {
    expect(() => calculateSingleInstrumentZCalibration({
      homeZ: 50,
      blockTouchZ: 55,
      blockHeight: 35,
      factoryZTravel: 110,
    })).toThrow("Block touch Z must be below");
  });

  it("throws when blockTouchZ equals homeZ", () => {
    expect(() => calculateSingleInstrumentZCalibration({
      homeZ: 110,
      blockTouchZ: 110,
      blockHeight: 35,
      factoryZTravel: 110,
    })).toThrow("Block touch Z must be below");
  });

  it("throws when home-to-block travel exceeds factory Z travel", () => {
    expect(() => calculateSingleInstrumentZCalibration({
      homeZ: 110,
      blockTouchZ: 0,
      blockHeight: 35,
      factoryZTravel: 80,
    })).toThrow("exceeds the configured factory Z travel");
  });

  it("throws when any input is non-finite", () => {
    expect(() => calculateSingleInstrumentZCalibration({
      homeZ: NaN,
      blockTouchZ: 60,
      blockHeight: 35,
      factoryZTravel: 110,
    })).toThrow("must be a finite number");

    expect(() => calculateSingleInstrumentZCalibration({
      homeZ: 110,
      blockTouchZ: Infinity,
      blockHeight: 35,
      factoryZTravel: 110,
    })).toThrow("must be a finite number");
  });

  it("throws when blockHeight is zero or negative", () => {
    expect(() => calculateSingleInstrumentZCalibration({
      homeZ: 110,
      blockTouchZ: 60,
      blockHeight: 0,
      factoryZTravel: 110,
    })).toThrow("Calibration reference height must be positive");

    expect(() => calculateSingleInstrumentZCalibration({
      homeZ: 110,
      blockTouchZ: 60,
      blockHeight: -5,
      factoryZTravel: 110,
    })).toThrow("Calibration reference height must be positive");
  });

  it("throws when factoryZTravel is zero or negative", () => {
    expect(() => calculateSingleInstrumentZCalibration({
      homeZ: 110,
      blockTouchZ: 60,
      blockHeight: 35,
      factoryZTravel: 0,
    })).toThrow("Factory Z travel must be positive");
  });
});

describe("buildCalibratedConfig", () => {
  it("preserves factory Z travel while saving calibrated bounds and soft limits", () => {
    const calibrated = buildCalibratedConfig({
      config: gantryConfig(),
      measuredVolume: { x: 398.5, y: 299.25, z: 96.75 },
      zMin: 0,
      zMax: 110,
      maxTravel: { x: 398.5, y: 299.25, z: 110 },
      isMulti: false,
      instruments: ["asmi"],
      instrumentPositions: {},
      referenceInstrument: "asmi",
      lowestInstrument: "asmi",
    });

    expect(calibrated.cnc.factory_z_travel_mm).toBe(110);
    expect(calibrated.cnc.safe_z).toBe(110);
    expect(calibrated.working_volume).toEqual({
      x_min: 0,
      x_max: 398.5,
      y_min: 0,
      y_max: 299.25,
      z_min: 0,
      z_max: 110,
    });
    expect(calibrated.grbl_settings?.max_travel_z).toBe(110);
  });

  it("does not update stale factory_z_travel_mm from calibrated max travel", () => {
    const config = gantryConfig();
    config.cnc.factory_z_travel_mm = 87;

    const calibrated = buildCalibratedConfig({
      config,
      measuredVolume: { x: 398.5, y: 299.25, z: 91.5 },
      zMin: 0,
      zMax: 91.5,
      maxTravel: { x: 398.5, y: 299.25, z: 91.5 },
      isMulti: false,
      instruments: ["asmi"],
      instrumentPositions: {},
      referenceInstrument: "asmi",
      lowestInstrument: "asmi",
    });

    expect(calibrated.cnc.factory_z_travel_mm).toBe(87);
    expect(calibrated.working_volume.z_max).toBe(91.5);
    expect(calibrated.grbl_settings?.max_travel_z).toBe(91.5);
  });

  it("saves controller max travel separately from usable working volume", () => {
    const calibrated = buildCalibratedConfig({
      config: gantryConfig(),
      measuredVolume: { x: 386, y: 250.5, z: 91 },
      zMin: 0,
      zMax: 91,
      maxTravel: { x: 396, y: 260.5, z: 101 },
      isMulti: false,
      instruments: ["asmi"],
      instrumentPositions: {},
      referenceInstrument: "asmi",
      lowestInstrument: "asmi",
    });

    expect(calibrated.working_volume).toEqual({
      x_min: 0,
      x_max: 386,
      y_min: 0,
      y_max: 250.5,
      z_min: 0,
      z_max: 91,
    });
    expect(calibrated.grbl_settings?.max_travel_x).toBe(396);
    expect(calibrated.grbl_settings?.max_travel_y).toBe(260.5);
    expect(calibrated.grbl_settings?.max_travel_z).toBe(101);
  });

  it("calibrates a camera from centered block position and measured block distance", () => {
    const config = gantryConfig();
    config.instruments.camera = {
      type: "camera",
      vendor: "raspberry_pi",
      offset_x: 0,
      offset_y: 0,
      depth: 0,
      offline: true,
    };

    const calibrated = buildCalibratedConfig({
      config,
      measuredVolume: { x: 398.5, y: 299.25, z: 96.75 },
      zMin: 0,
      zMax: 110,
      maxTravel: { x: 398.5, y: 299.25, z: 110 },
      isMulti: true,
      instruments: ["asmi", "camera"],
      instrumentPositions: {
        asmi: { x: 199, y: 149.5, z: 12.5 },
        camera: { x: 211, y: 153.5, z: 35.5 },
      },
      referenceInstrument: "asmi",
      lowestInstrument: "asmi",
      cameraBlockDistances: { camera: 20 },
    });

    expect(calibrated.instruments.camera).toMatchObject({
      offset_x: -12,
      offset_y: -4,
      depth: 3,
    });
  });

  it("requires a camera distance before saving calibrated offsets", () => {
    const config = gantryConfig();
    config.instruments.camera = {
      type: "camera",
      vendor: "raspberry_pi",
      offset_x: 0,
      offset_y: 0,
      depth: 0,
      offline: true,
    };

    expect(() => buildCalibratedConfig({
      config,
      measuredVolume: { x: 398.5, y: 299.25, z: 96.75 },
      zMin: 0,
      zMax: 110,
      maxTravel: { x: 398.5, y: 299.25, z: 110 },
      isMulti: true,
      instruments: ["asmi", "camera"],
      instrumentPositions: {
        asmi: { x: 199, y: 149.5, z: 12.5 },
        camera: { x: 211, y: 153.5, z: 35.5 },
      },
      referenceInstrument: "asmi",
      lowestInstrument: "asmi",
    })).toThrow("Distance from calibration block is required for camera.");
  });
});
