"""#489 OFFLINE stage-plan reviewer. No host/filesystem/network/process access.

Verifies exact recipe result bytes against the reviewed old source inputs and
returns a bounded *non-authorizing* proposed member list. It neither stages
a new bundle nor establishes live Windows identity, ACL or volume evidence.
"""
from __future__ import annotations

import json

from prepare_obsidian_relocation import (
    BUNDLE,  # legacy template, never an accepted new release target
    MODULE_FILES,
    NEW_BUNDLE,
    NEW_RELEASE,
    OLD_RELEASE,
    VAULT,
    bundle_recipe,
    canonical,
    digest,
)

RESULT_FIELDS = frozenset({
    "status", "installable", "modules", "manifest", "manifest_sha256",
    "launcher_source", "launcher_source_sha256", "pins", "pins_sha256", "files",
})
MANIFEST_FIELDS = frozenset({
    "source_commit", "user_root", "sid", "bundle", "python",
    "python_sha256", "vault", "files",
})
MAX_PY_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 16384
EXPECTED_STATUS = "source recipe ready, no host-specific attestation, not installable yet"


def review_offline_stage_plan(old_modules, old_pins, old_native, identity, result):
    """Return exact *data-only* member hashes; always refuse physical acceptance.

    The caller's identity values are untrusted shapes; the recipe itself
    independently checks exact pinned old bytes and fixed new release paths.
    No call performs lstat, file hashing, compilation, mkdir or task access.
    """
    if type(result) is not dict or set(result) != RESULT_FIELDS:
        raise ValueError("unexpected_recipe_fields")
    expected = bundle_recipe(old_modules, old_pins, old_native, identity)
    if (
        result != expected
        or type(result["installable"]) is not bool
        or result["installable"] is not False
        or result["status"] != EXPECTED_STATUS
    ):
        raise ValueError("recipe_output_drift")
    manifest = result["manifest"]
    if type(manifest) is not bytes or len(manifest) > MAX_MANIFEST_BYTES:
        raise ValueError("manifest_size_or_type")
    spec = json.loads(manifest)
    if (
        type(spec) is not dict
        or set(spec) != MANIFEST_FIELDS
        or spec != json.loads(canonical(spec))
        or canonical(spec) != manifest
        or spec["source_commit"] != NEW_RELEASE
        or spec["bundle"] != NEW_BUNDLE
        or spec["vault"] != VAULT
        or spec["files"] != result["files"]
        or spec["source_commit"] == OLD_RELEASE
        or spec["bundle"] == BUNDLE
        or result["manifest_sha256"] != digest(manifest)
        or type(result["modules"]) is not dict
        or set(result["modules"]) != MODULE_FILES
        or set(result["files"]) != MODULE_FILES
    ):
        raise ValueError("release_manifest_binding")
    for name, raw in result["modules"].items():
        if (
            type(raw) is not bytes or len(raw) > MAX_PY_BYTES
            or result["files"][name] != digest(raw)
        ):
            raise ValueError("bundle_module_pin_or_size")
    expected_pins = canonical({"source_commit": NEW_RELEASE, "files": result["files"]})
    if result["pins"] != expected_pins or result["pins_sha256"] != digest(expected_pins):
        raise ValueError("release_pin_mismatch")
    native = result["launcher_source"]
    if (
        type(native) is not bytes or len(native) > MAX_PY_BYTES
        or result["launcher_source_sha256"] != digest(native)
    ):
        raise ValueError("launcher_source_pin")
    members = [
        {"name": name, "sha256": digest(result["modules"][name]),
         "byte_count": len(result["modules"][name])}
        for name in sorted(MODULE_FILES)
    ]
    members.append({"name": "manifest.json", "sha256": digest(manifest),
                    "byte_count": len(manifest)})
    return {
        "status": "OFFLINE_REVIEW_ONLY",
        "installable": False,
        "stage_authorized": False,
        "task_update_authorized": False,
        "vault_move_authorized": False,
        "bundle": NEW_BUNDLE,
        "vault": VAULT,
        "members": members,
        "manifest_sha256": result["manifest_sha256"],
        "pins_sha256": result["pins_sha256"],
        "launcher_source_sha256": result["launcher_source_sha256"],
        "gates": [
            "authenticate_live_identity_and_python_sha256_on_host",
            "prove_absent_exact_directory_and_plain_parent",
            "review_native_gui_compilation_and_executable_hash",
            "independently_verify_exclusive_staging_and_exact_membership",
            "separate_host_staging_authorization",
            "separate_task_quiescence_and_vault_relocation_authorizations",
        ],
    }
