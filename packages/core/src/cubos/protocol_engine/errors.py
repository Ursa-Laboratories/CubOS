"""Protocol engine errors and command migration guidance."""


class ProtocolLoaderError(Exception):
    """Human-friendly protocol loader error intended for CLI output."""


class ProtocolExecutionError(Exception):
    """Error raised during protocol step execution."""


class GantryHealthCheckError(Exception):
    """Raised when the gantry fails its health check before a protocol run."""


LEGACY_COMMAND_HINTS: dict[str, str] = {
    "safe_approach_height": (
        "`safe_approach_height` was renamed to `interwell_scan_height` "
        "(labware-relative offset above the well surface for between-wells "
        "XY travel)."
    ),
    "indentation_limit": (
        "`indentation_limit` was renamed to `indentation_limit_height` and "
        "its meaning changed: it is now a *signed* labware-relative offset "
        "(mm above the well surface; negative = below), not a sign-agnostic "
        "descent magnitude. Convert e.g. `indentation_limit: 5.0` to "
        "`indentation_limit_height: -5.0`."
    ),
    "z_limit": (
        "`z_limit` is no longer supported. Use `indentation_limit_height` "
        "(signed labware-relative offset, mm above the well surface)."
    ),
    "entry_travel_height": (
        "`entry_travel_height` is no longer supported. Inter-labware/entry "
        "travel uses the gantry's `safe_z` (absolute deck-frame Z)."
    ),
    "interwell_travel_height": (
        "`interwell_travel_height` was renamed to `interwell_scan_height`."
    ),
}
