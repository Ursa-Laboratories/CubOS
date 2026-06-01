import cubos
from cubos.protocols import filmetrics_scan_protocol
from cubos.protocols import move_a1_protocol as exported_move_a1_protocol
from cubos.protocols.asmi import move_a1_protocol
from cubos.protocols.sharc import uv_motion_scan_protocol
from cubos.protocols.sterling import vial_scan_protocol
from protocol_engine.loader import load_protocol_from_yaml


def _protocol_signature(protocol):
    return (
        protocol.positions,
        [(step.index, step.command_name, step.args) for step in protocol.steps],
    )


def test_asmi_move_a1_python_protocol_matches_yaml():
    yaml_protocol = load_protocol_from_yaml("configs/protocol/asmi_move_a1.yaml")

    assert _protocol_signature(move_a1_protocol()) == _protocol_signature(
        yaml_protocol
    )
    assert _protocol_signature(exported_move_a1_protocol()) == _protocol_signature(
        yaml_protocol
    )


def test_cubos_package_exports_protocol_builder():
    step = cubos.protocol_step("home")

    assert step.command_name == "home"
    assert step.args == {}


def test_filmetrics_scan_python_protocol_matches_yaml():
    yaml_protocol = load_protocol_from_yaml("configs/protocol/filmetrics_scan.yaml")

    assert _protocol_signature(filmetrics_scan_protocol()) == _protocol_signature(
        yaml_protocol
    )


def test_sharc_uv_motion_scan_python_protocol_matches_yaml():
    yaml_protocol = load_protocol_from_yaml("configs/protocol/sharc_uv_motion_scan.yaml")

    assert _protocol_signature(uv_motion_scan_protocol()) == _protocol_signature(
        yaml_protocol
    )


def test_sterling_vial_scan_python_protocol_matches_yaml():
    yaml_protocol = load_protocol_from_yaml("configs/protocol/sterling_vial_scan.yaml")

    assert _protocol_signature(vial_scan_protocol()) == _protocol_signature(
        yaml_protocol
    )
