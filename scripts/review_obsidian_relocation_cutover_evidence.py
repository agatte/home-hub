"""Pure offline #489 packet consistency review; never host or move authority.

Inputs are ordinary in-memory JSON-shaped data, not authenticated observations.
No I/O, CLI, clock, runtime imports, path normalization or seal verification.
"""

import re

PARENT = r"C:\Users\Anthony\Documents"
OLD = PARENT + r"\HomeHub Knowledge Vault"
NEW_PARENT = PARENT + r"\HomeHub Vault Storage"
NEW = NEW_PARENT + r"\HomeHub Knowledge Vault"
PREFIX = ".HomeHub Knowledge Vault-homehub-"
MAX_SIBLINGS = 2048
MAX_AGE_SECONDS = 300  # Supplied-time consistency only, never live freshness.
GATES = (
    "separate_review_and_authorization_of_bounded_host_read_only_collection",
    "independent_authentication_of_packet_pins_seals_and_current_host_state",
    "separate_host_staging_authorization",
    "attended_disable_triggers_drain_workers_close_obsidian_and_recheck_locks",
    "handle_bound_identity_acl_link_volume_and_collision_checks_at_each_write",
    "separate_task_update_obsidian_rebind_and_move_authorizations",
    "postflight_full_preservation_verification_before_resuming_triggers",
    "crash_or_drift_stop_preserve_all_evidence_review_rollback_no_auto_delete",
)


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _fields(value, names, reason):
    _require(type(value) is dict and set(value) == set(names.split()), reason)


def _hex(value, length=64):
    return type(value) is str and re.fullmatch("[0-9a-f]{" + str(length) + "}", value)


def _names(value):
    _require(type(value) is list and len(value) <= MAX_SIBLINGS, "sibling_bounds")
    for name in value:
        _require(type(name) is str and len(name) <= 180 and re.fullmatch(
            re.escape(PREFIX) + r"[A-Za-z0-9][A-Za-z0-9._-]*", name
        ) and not name.endswith((".", " ")), "sibling_literal")
    _require(len({n.casefold() for n in value}) == len(value), "sibling_collision")
    _require(value == sorted(value), "sibling_order")


def _observation(value):
    _fields(value, "volume file_id filesystem reparse hard_links acl_sha256 "
            "acl_reviewed recursive_plain_tree content_sha256 seal_sha256", "observation_shape")
    _require(_hex(value["volume"], 16) and _hex(value["file_id"], 32), "file_identity")
    _require(value["filesystem"] == "NTFS" and value["reparse"] is False
             and type(value["hard_links"]) is int and value["hard_links"] == 1
             and value["recursive_plain_tree"] is True, "filesystem_links")
    _require(_hex(value["acl_sha256"]) and value["acl_reviewed"] is True, "acl_observation")
    _require(_hex(value["content_sha256"]) and _hex(value["seal_sha256"]), "hash_shape")


def _review(packet, reviewed_siblings, reviewed_bindings, now):
    _names(reviewed_siblings)
    _fields(packet, "schema old new captured_at physical_confirmation inventory_complete "
            "siblings records parents destination_absent collisions task quiescence "
            "bindings backup rollback", "packet_shape")
    _require(type(packet["schema"]) is int and packet["schema"] == 1, "schema")
    _require(packet["old"] == OLD and packet["new"] == NEW, "vault_literals")
    captured = packet["captured_at"]
    _require(type(now) is int and type(captured) is int
             and 0 <= now - captured <= MAX_AGE_SECONDS, "supplied_time_window")
    _require(packet["physical_confirmation"] is True, "physical_confirmation_missing")
    _require(packet["inventory_complete"] is True, "inventory_incomplete")
    _names(packet["siblings"])
    _require(packet["siblings"] == reviewed_siblings, "sibling_membership")
    _require(packet["destination_absent"] is True and packet["collisions"] == []
             and type(packet["collisions"]) is list, "destination_collision")
    paths = [OLD] + [PARENT + "\\" + n for n in reviewed_siblings]
    records = packet["records"]
    _require(type(records) is list and len(records) == len(paths), "record_membership")
    identities = set()
    volume = None
    token_groups = {}
    for path, record in zip(paths, records, strict=True):
        _fields(record, "path classification preserve coverage before after", "record_shape")
        _require(record["path"] == path and record["preserve"] is True, "protected_path")
        _require(record["classification"] in (
            "vault", "complete_backup", "complete_stage", "complete_receipt", "standalone_backup"
        ), "unknown_or_incomplete_artifact_requires_review")
        _require((record["classification"] == "vault") == (path == OLD), "classification")
        if path != OLD:
            suffix = path[len(PARENT) + 1 + len(PREFIX):]
            pattern = {
                "complete_backup": r"backup-([0-9a-f]{32})",
                "standalone_backup": r"backup-([0-9a-f]{32})",
                "complete_stage": r"completed-stage-([0-9a-f]{32})",
                "complete_receipt": r"complete-([0-9a-f]{32})\.json",
            }[record["classification"]]
            match = re.fullmatch(pattern, suffix)
            _require(match is not None, "unknown_or_incomplete_artifact_requires_review")
            token_groups.setdefault(match.group(1), set()).add(record["classification"])
        _require(record["coverage"] == "all_bytes_names_settings_personal_and_managed",
                 "protected_coverage")
        _observation(record["before"])
        _observation(record["after"])
        _require(record["before"] == record["after"], "observation_drift")
        obs = record["before"]
        volume = volume or obs["volume"]
        _require(obs["volume"] == volume, "volume_mismatch")
        _require(obs["file_id"] not in identities, "identity_alias")
        identities.add(obs["file_id"])
    for group in token_groups.values():
        _require(group in (
            {"standalone_backup"},
            {"complete_backup", "complete_stage", "complete_receipt"},
        ), "incomplete_artifact_triple")
    parents = packet["parents"]
    _require(type(parents) is dict and set(parents) == {PARENT, NEW_PARENT}, "parent_membership")
    for path in (PARENT, NEW_PARENT):
        _observation(parents[path])
        _require(parents[path]["volume"] == volume, "volume_mismatch")
        _require(parents[path]["file_id"] not in identities, "identity_alias")
        identities.add(parents[path]["file_id"])
    _fields(packet["task"], "name state enabled running_instances pending_instances", "task_shape")
    _require(packet["task"] == {
        "name": "HomeHub Obsidian Mirror Refresh", "state": "Disabled", "enabled": False,
        "running_instances": 0, "pending_instances": 0,
    } and type(packet["task"]["enabled"]) is bool
        and type(packet["task"]["running_instances"]) is int
        and type(packet["task"]["pending_instances"]) is int, "task_not_quiescent")
    _fields(packet["quiescence"], "obsidian_closed workers_drained locks pending", "quiescence_shape")
    _require(packet["quiescence"] == {
        "obsidian_closed": True, "workers_drained": True, "locks": [], "pending": []
    } and packet["quiescence"]["obsidian_closed"] is True
        and packet["quiescence"]["workers_drained"] is True, "active_or_pending")
    _bindings(reviewed_bindings)
    _bindings(packet["bindings"])
    _require(packet["bindings"] == reviewed_bindings, "binding_drift")
    _fields(packet["backup"], "independent_snapshot_ids protected_paths verified", "backup_shape")
    backup = packet["backup"]
    ids = backup["independent_snapshot_ids"]
    _require(type(ids) is list and len(ids) == 2 and all(_hex(i) for i in ids)
             and ids[0] != ids[1] and backup["protected_paths"] == paths
             and backup["verified"] is True, "independent_backups")
    _require(type(packet["rollback"]) is dict and packet["rollback"] == {
        "old_path": OLD, "retain_original_bundle_task_and_snapshots": True,
        "stop_on_crash_or_drift": True, "no_auto_delete": True,
        "restore_requires_attended_review": True,
    } and all(packet["rollback"][key] is True for key in (
        "retain_original_bundle_task_and_snapshots", "stop_on_crash_or_drift",
        "no_auto_delete", "restore_requires_attended_review",
    )), "rollback_contract")


def _bindings(value):
    _fields(value, "current proposed", "binding_shape")
    for kind in ("current", "proposed"):
        entry = value[kind]
        _fields(entry, "exe start_in arguments python source_commit exe_sha256 "
                "python_sha256 manifest_sha256 pins_sha256 runtime_sha256 task_xml_sha256",
                "binding_entry_shape")
        root = r"C:\Users\Anthony\AppData\Local\HomeHub\ObsidianMirror" + "\\"
        _require(type(entry["start_in"]) is str and re.fullmatch(
            re.escape(root) + "[0-9a-f]{40}", entry["start_in"]), "bundle_literal")
        _require(type(entry["exe"]) is str and re.fullmatch(
            re.escape(entry["start_in"] + "\\") + r"[A-Za-z0-9_-]+\.exe", entry["exe"]
        ) and entry["arguments"] == "", "action_literal")
        _require(entry["python"] == r"C:\Users\Anthony\AppData\Local\Programs\Python\Python313\python.exe"
                 and _hex(entry["source_commit"], 40), "runtime_literal")
        _require(entry["start_in"].rsplit("\\", 1)[-1] == entry["source_commit"],
                 "release_label_binding")
        for key in ("exe_sha256", "python_sha256", "manifest_sha256", "pins_sha256",
                    "runtime_sha256", "task_xml_sha256"):
            _require(_hex(entry[key]), "binding_hash")
    _require(value["current"]["start_in"] != value["proposed"]["start_in"], "release_collision")


def review_cutover_evidence(packet, *, reviewed_siblings, reviewed_bindings, now):
    """Report first deterministic refusal, or shape consistency. Never authenticate.

    Reviewed inputs and integer epoch seconds are ALSO caller assertions. Before/
    after mean the collection interval, not a move. Unknown records are retained
    by the operator and block review; this function never returns a move list.
    """
    reasons = []
    try:
        _review(packet, reviewed_siblings, reviewed_bindings, now)
    except ValueError as error:
        reasons.append(str(error))
    return {
        "readiness": "OFFLINE_REVIEW_ONLY",
        "packet_consistent": not reasons,
        "reasons": reasons,
        "host_preflight_authorized": False,
        "host_stage_authorized": False,
        "task_update_authorized": False,
        "vault_move_authorized": False,
        "authenticity_verified": False,
        "freshness_verified": False,
        "seal_integrity_verified": False,
        "physical_safety_verified": False,
        "gates": list(GATES),
    }
