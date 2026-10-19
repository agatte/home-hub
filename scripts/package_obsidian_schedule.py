"""OFF by default. Prepare a pinned bundle or emit disabled task XML; never register."""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import json
from pathlib import Path
import xml.etree.ElementTree as ET

from launch_obsidian_mirror import (
    FILES, SOURCE_COMMIT, QuietArgumentParser, digest, file_digest, plain, read_small, validate_spec,
)

TASK_NAME = "HomeHub Obsidian Mirror Refresh"
NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"


def manifest_bytes(spec):
    validate_spec(spec)
    return json.dumps(spec, sort_keys=True, separators=(",", ":")).encode("utf-8")


def task_xml(spec):
    """Pure builder: no path probing, process, registration or activation API."""
    anchor = digest(manifest_bytes(spec))
    root = ET.Element("Task", {"version": "1.4", "xmlns": NS})

    def element(parent, tag, value=None):
        child = ET.SubElement(parent, tag)
        if value is not None:
            child.text = str(value)
        return child

    registration = element(root, "RegistrationInfo")
    element(registration, "URI", "\\" + TASK_NAME)
    triggers = element(root, "Triggers")
    logon = element(triggers, "LogonTrigger")
    element(logon, "Enabled", "true")
    element(logon, "UserId", spec["sid"])
    calendar = element(triggers, "CalendarTrigger")
    repetition = element(calendar, "Repetition")
    element(repetition, "Interval", "PT1H")
    element(repetition, "Duration", "P1D")
    element(repetition, "StopAtDurationEnd", "false")
    element(calendar, "StartBoundary", "2026-10-19T00:00:00")
    element(calendar, "Enabled", "true")
    daily = element(calendar, "ScheduleByDay")
    element(daily, "DaysInterval", "1")
    principals = element(root, "Principals")
    principal = ET.SubElement(principals, "Principal", {"id": "OrdinaryUser"})
    element(principal, "UserId", spec["sid"])
    element(principal, "LogonType", "InteractiveToken")
    element(principal, "RunLevel", "LeastPrivilege")
    settings = element(root, "Settings")
    for tag, value in (
        ("MultipleInstancesPolicy", "IgnoreNew"), ("DisallowStartIfOnBatteries", "false"),
        ("StopIfGoingOnBatteries", "false"), ("AllowHardTerminate", "false"),
        ("StartWhenAvailable", "false"), ("RunOnlyIfNetworkAvailable", "false"),
        ("Enabled", "false"), ("WakeToRun", "false"), ("ExecutionTimeLimit", "PT0S"),
    ):
        element(settings, tag, value)
    actions = ET.SubElement(root, "Actions", {"Context": "OrdinaryUser"})
    action = element(actions, "Exec")
    element(action, "Command", spec["python"])
    element(action, "Arguments", '-I -B "' + spec["bundle"] +
            '\\launch_obsidian_mirror.py" --run --anchor ' + anchor)
    element(action, "WorkingDirectory", spec["bundle"])
    return ET.tostring(root, encoding="unicode")


def prepare(spec, source, reviewed_pins_sha256):
    """Explicit package write only, exclusive new directory, no task operations.

    Review pins independently BEFORE supplying their digest. Never overwrite,
    roll back, remove partial output, touch Vault, or generate runtime trust.
    """
    validate_spec(spec)
    source = Path(source)
    plain(source)
    pins_path = source / "obsidian_launcher_pins.json"
    plain(pins_path)
    raw = read_small(pins_path, 16384)
    if digest(raw) != reviewed_pins_sha256:
        raise ValueError("reviewed_pins")
    pins = json.loads(raw)
    if (set(pins) != {"source_commit", "files"} or pins["source_commit"] != SOURCE_COMMIT
            or pins["files"] != spec["files"] or set(pins["files"]) != FILES):
        raise ValueError("pins")
    blobs = {}
    for name, expected in pins["files"].items():
        path = source / name
        plain(path)
        data = read_small(path)
        if digest(data) != expected:
            raise ValueError("source_pin")
        blobs[name] = data
    python = Path(spec["python"])
    plain(python)
    if file_digest(python) != spec["python_sha256"]:
        raise ValueError("python_pin")
    destination = Path(spec["bundle"])
    plain(destination.parent)
    # Parent must already exist and be reviewed. No implicit mkdir hierarchy.
    destination.mkdir(exist_ok=False)
    for name, data in blobs.items():
        with (destination / name).open("xb") as stream:
            stream.write(data)
    with (destination / "manifest.json").open("xb") as stream:
        stream.write(manifest_bytes(spec))
    return digest(manifest_bytes(spec))


def main(argv=None, *, output=None):
    parser = QuietArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--spec-json")
    parser.add_argument("--xml", action="store_true")
    parser.add_argument("--stage", action="store_true")
    parser.add_argument("--approve-stage")
    parser.add_argument("--reviewed-pins-sha256")
    result = {"status": "off", "registered": False}
    try:
        args = parser.parse_args(argv)
        if args.xml:
            if args.stage or args.approve_stage or args.reviewed_pins_sha256 or not args.spec_json:
                raise ValueError("mode")
            print(task_xml(json.loads(args.spec_json)), file=output or sys.stdout)
            return 0
        if any((args.stage, args.approve_stage, args.spec_json, args.reviewed_pins_sha256)):
            if not (args.stage and args.spec_json and args.reviewed_pins_sha256):
                raise ValueError("two_keys")
            spec = validate_spec(json.loads(args.spec_json))
            if args.approve_stage != spec["bundle"]:
                raise ValueError("two_keys")
            anchor = prepare(spec, Path(__file__).parent, args.reviewed_pins_sha256)
            result = {"status": "prepared_only", "manifest_sha256": anchor, "registered": False}
    except Exception:
        print('{"status":"package_refused_review_evidence"}', file=output or sys.stdout)
        return 2
    print(json.dumps(result, sort_keys=True), file=output or sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
