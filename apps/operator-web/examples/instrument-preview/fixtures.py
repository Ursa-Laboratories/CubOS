"""Illustrative configurations and a shared deck for the Operator CAD preview."""

def head(kind, vendor, x=0, **details):
    return {"type": kind, "vendor": vendor, "offline": True,
            "offset_x": x, "offset_y": 0, "depth": 0, **details}


# Offsets in millimeters illustrate how multiple heads share a carriage.
SETUPS = {
    "pipettes": ("Pipettes", {
        "sartorius": head("pipette", "sartorius", -90, pipette_model="picus2_1ch_5000"),
        "opentrons_single": head("pipette", "opentrons", 0, pipette_model="p300_single_gen2"),
        "opentrons_multi": head("pipette", "opentrons", 85, pipette_model="p300_multi_gen2"),
    }),
    "picus-300": ("Picus 2 · 300 µL", {
        "sartorius_single": head("pipette", "sartorius", -53, pipette_model="picus2_1ch_300"),
        "sartorius_multi": head("pipette", "sartorius", 53, pipette_model="picus2_8ch_300"),
    }),
    "mechanics": ("Mechanical tools", {
        "force_probe": head("asmi", "vernier", -100),
        "capper": head("capper", "pawduino", 0),
        "mounted_tool": head("mounted_tool", "mount_only", 74),
    }),
    "cappers": ("Capper variants", {
        "pawduino": head("capper", "pawduino", -78),
        "nano_text": head("capper", "nano_text", 0),
        "mock": head("capper", "mock", 78),
    }),
    "optics": ("Optics and UV curing", {
        "filmetrics": head("filmetrics", "kla", -72),
        "uv_vis": head("uvvis_ccs", "thorlabs"),
        "uv_curing": head("uv_curing", "excelitas", 72),
    }),
    "imaging": ("Imaging and illumination", {
        "raspberry_pi": head("camera", "raspberry_pi", -65),
        "ring_light": head("lighting", "pawduino", 0),
        "flir": head("camera", "flir", 75),
    }),
    "electrochemistry": ("Electrochemistry", {
        "admiral": head("potentiostat", "admiral", -60),
        "emstat": head("potentiostat", "emstat", 60),
    }),
    "raman": ("Raman probe", {
        "raman_probe": head("mounted_tool", "mount_only"),
    }),
}

GANTRY = {
    "serial_port": "OFFLINE-PREVIEW",
    "gantry_type": "genmitsu_4040_pro_max",
    "cnc": {"factory_z_travel_mm": 80, "calibration_block_height_mm": 35,
            "y_axis_motion": "head", "safe_z": 70},
    "working_volume": {"x_min": 0, "x_max": 390, "y_min": 0, "y_max": 390,
                       "z_min": 0, "z_max": 70},
}


def point(x, y, z):
    return {"x": x, "y": y, "z": z}


def grid(x, y, z, rows=8, columns=12, spacing=9):
    return {
        f"{chr(65 + row)}{column + 1}": point(x + column * spacing, y - row * spacing, z)
        for row in range(rows)
        for column in range(columns)
    }


def footprint(length, width, height):
    return {"length": length, "width": width, "height": height}


def plate_or_tips(key, kind, name, dimensions, positions, **details):
    return {
        "key": key,
        "config": {"type": kind, "name": name, "model_name": f"sample_{key}",
                   "rows": 8, "columns": 12, "x_offset": 9, "y_offset": 9,
                   "calibration": {"a1": positions["A1"], "a2": positions["A2"]}, **details},
        "wells": positions if kind == "well_plate" else None,
        "positions": positions,
        "geometry": dimensions,
    }


def sample_deck():
    plate = footprint(127.76, 85.47, 14.35)
    tips = grid(174.5, 205.5, 55)
    vial_positions = grid(35, 200, 48, rows=3, columns=4, spacing=24)
    vials = {
        name: {"model_name": "sample_vial", "location": position, "height": 35,
               "diameter": 15, "capacity_ul": 2000, "working_volume_ul": 0}
        for name, position in vial_positions.items()
    }
    vial_location = point(71, 176, 0)
    waste_location = point(224, 64, 35)
    return {
        "filename": "preview-deck.yaml",
        "labware": [
            plate_or_tips("plate", "well_plate", "96-well plate", plate,
                          grid(25.5, 95.5, 14.35), **plate),
            plate_or_tips("tips", "tip_rack", "Tips", footprint(127, 85, 55), tips,
                          pickup_z=55, tip_length=50,
                          tip_present={name: index >= 8 for index, name in enumerate(tips)}),
            {"key": "vials", "config": {"type": "vial_holder", "name": "12-vial holder",
                                       "location": vial_location,
                                       "labware_seat_height_from_bottom": 13, "vials": vials},
             "wells": None, "location": vial_location, "positions": vial_positions,
             "geometry": footprint(110, 85, 20)},
            {"key": "waste", "config": {"type": "tip_disposal", "name": "Tip disposal",
                                       "location": waste_location},
             "wells": None, "location": waste_location, "geometry": footprint(100, 72, 35)},
        ],
    }
