"""Pure #489 candidate templates: no filesystem, subprocess, or network access."""
from __future__ import annotations

from hashlib import sha1, sha256
import json
import re

USER = r"C:\Users\Anthony"
VAULT = USER + r"\Documents\HomeHub Vault Storage\HomeHub Knowledge Vault"
RELEASE_ID = "relocation-489-template-v1"
BUNDLE = USER + r"\AppData\Local\HomeHub\ObsidianMirror" + "\\" + RELEASE_ID
# These are deliberately non-executable data templates, not patched legacy runtime.
TEMPLATES = {
    "runtime.template.json": b'{"source_commit":"PENDING_PUBLISHED_COMMIT","runtime_manifest":"PENDING_REVIEWED_PIN","status":"NOT_INSTALLABLE"}',
    "launcher.template.json": b'{"arguments":"","bundle":"PENDING_FINAL_BUNDLE","manifest_sha256":"PENDING_FINAL_PIN","status":"NOT_INSTALLABLE"}',
}
FILES = frozenset(TEMPLATES)


def digest(data):
    return sha256(data).hexdigest()


def canonical(spec):
    return json.dumps(spec, sort_keys=True, separators=(",", ":")).encode("ascii")


def candidate_spec():
    """Return fresh deterministic review data; release ID is NOT a Git SHA."""
    return {"schema": 1, "release_id": RELEASE_ID, "source_commit": None,
            "status": "template_only", "bundle": BUNDLE, "vault": VAULT,
            "files": {name: digest(data) for name, data in TEMPLATES.items()}}


def preview(spec, blobs, *, reviewed_manifest_sha256, reviewed_files):
    """Check only supplied bytes. No path resolution or link following is possible.

    File inputs must be exact bytes, never paths/link descriptors. This cannot
    certify filesystem links, ACLs, token identity, publication, or runtime safety.
    """
    if type(spec) is not dict or spec != candidate_spec():
        raise ValueError("candidate_binding")
    if (type(blobs) is not dict or set(blobs) != FILES
            or reviewed_files != spec["files"]):
        raise ValueError("source_membership_or_review")
    for name, data in blobs.items():
        if type(data) is not bytes or data != TEMPLATES[name]:
            raise ValueError("source_drift_or_non_bytes")
        if digest(data) != reviewed_files[name]:
            raise ValueError("source_pin")
    manifest = canonical(spec)
    anchor = digest(manifest)
    if anchor != reviewed_manifest_sha256:
        raise ValueError("manifest_pin")
    return {"status": "source_only_final_pin_required", "installable": False,
            "release_id": RELEASE_ID, "source_commit": None,
            "manifest_preview": manifest.decode("ascii"),
            "manifest_sha256": anchor, "vault": VAULT, "bundle": BUNDLE,
            "gates": ["implement_and_review_new_runtime_and_launcher",
                      "commit_publish_source", "finalize_distinct_release_and_pins",
                      "independent_review", "separate_host_authorization"]}


def validate_future_action(action, *, reviewed_executable, reviewed_bundle):
    """Refuse activation: templates have no executable or final runtime pins."""
    raise ValueError("candidate_has_no_installable_action")


# Fixed release LABEL, never a claim about a historical Git tree.
NEW_RELEASE = sha1(b"HomeHub-489-vault-storage-20261104").hexdigest()
OLD_RELEASE = "5fbc1ddbe2d42d6a1540704b58da75a921b1e7f5"
NEW_BUNDLE = USER + r"\AppData\Local\HomeHub\ObsidianMirror" + "\\" + NEW_RELEASE
PYTHON = USER + r"\AppData\Local\Programs\Python\Python313\python.exe"
OLD_ANCHOR = "073e5bd74df5c99ab29edb3e5c5504b6abaa1f7bd0283c7f6b2f04fe1c892b70"
OLD_PINS_SHA256 = "20c774e360bff84d94942f0600219806e5919564e97c7e02264dddc808f31f62"  # reviewed Windows CRLF bytes
OLD_PINS_LF_SHA256 = "6ce36d97fafda905cdced30cd4b6f0131d69fb952a689c0036dce28fe357cfc7"  # reviewed Git LF blob
OLD_NATIVE_SHA256 = "4372e4d9f982f828bfbab79f308abbd83982130d3a548e24b9f27a7b7ebcac69"
MODULE_FILES = frozenset({
    "create_obsidian_pilot.py", "launch_obsidian_mirror.py", "manage_obsidian_vault.py",
    "obsidian_github_docs_source.py", "obsidian_raw_blob_transport.py",
    "obsidian_simple_mirror.py", "obsidian_source_verifier.py",
    "obsidian_verified_stage.py", "run_obsidian_simple_mirror.py",
})


def replace_once(data, old, new):
    """Byte substitution only; refuse ambiguous or missing source literals."""
    if type(data) is not bytes or data.count(old) != 1:
        raise ValueError("literal_count")
    before, after = data.split(old)
    result = before + new + after
    if result[:len(before)] != before or result[len(before) + len(new):] != after:
        raise ValueError("unexpected_byte_drift")
    return result


def bundle_recipe(old_modules, old_pins, old_native, identity, *,
                  release=NEW_RELEASE, bundle=NEW_BUNDLE, vault=VAULT):
    """Memory-only source recipe. Identity is untrusted, independently supplied DATA.

    No reads, staging, execution, token probes, attestation, or installation API.
    Old pins and native source are independently fixed by reviewed byte hashes.
    """
    if release != NEW_RELEASE or bundle != NEW_BUNDLE or vault != VAULT:
        raise ValueError("release_or_target")
    # Only these two independently reviewed exact byte forms are allowed.
    # Git stores LF while the approved Windows checkout has CRLF; no general
    # newline normalization or caller-provided digest is trusted here.
    if type(old_pins) is not bytes or digest(old_pins) not in (OLD_PINS_SHA256, OLD_PINS_LF_SHA256):
        raise ValueError("reviewed_old_pins")
    pins = json.loads(old_pins)
    if (set(pins) != {"source_commit", "files"}
            or pins["source_commit"] != OLD_RELEASE or set(pins["files"]) != MODULE_FILES
            or type(old_modules) is not dict or set(old_modules) != MODULE_FILES):
        raise ValueError("exact_module_membership")
    for name, data in old_modules.items():
        if type(data) is not bytes or digest(data) != pins["files"][name]:
            raise ValueError("old_module_pin")
    if type(old_native) is not bytes or digest(old_native) != OLD_NATIVE_SHA256:
        raise ValueError("old_native_pin")
    if (type(identity) is not dict
            or set(identity) != {"user_root", "python", "sid", "python_sha256"}
            or any(type(value) is not str for value in identity.values())
            or identity["user_root"] != USER or identity["python"] != PYTHON
            or not re.fullmatch(r"S-1-5-21-(?:[1-9][0-9]{0,9}-){3}[1-9][0-9]{0,9}", identity["sid"])
            or any(int(part) > 4294967295 for part in identity["sid"].split("-")[4:])
            or not re.fullmatch(r"[0-9a-f]{64}", identity["python_sha256"])):
        raise ValueError("identity_data_binding")
    modules = dict(old_modules)
    modules["launch_obsidian_mirror.py"] = replace_once(
        modules["launch_obsidian_mirror.py"],
        ('SOURCE_COMMIT = "' + OLD_RELEASE + '"').encode("ascii"),
        ('SOURCE_COMMIT = "' + NEW_RELEASE + '"').encode("ascii"))
    files = {name: digest(data) for name, data in sorted(modules.items())}
    spec = dict(identity, source_commit=NEW_RELEASE, bundle=NEW_BUNDLE, vault=VAULT, files=files)
    manifest = canonical(spec)
    anchor = digest(manifest)
    old_bundle = USER + r"\AppData\Local\HomeHub\ObsidianMirror" + "\\" + OLD_RELEASE
    native = replace_once(
        old_native, ('private const string Bundle = @"' + old_bundle + '";').encode("ascii"),
        ('private const string Bundle = @"' + NEW_BUNDLE + '";').encode("ascii"))
    native = replace_once(
        native, ('private const string Anchor = "' + OLD_ANCHOR + '";').encode("ascii"),
        ('private const string Anchor = "' + anchor + '";').encode("ascii"))
    new_pins = canonical({"source_commit": NEW_RELEASE, "files": files})
    return {"status": "source recipe ready, no host-specific attestation, not installable yet",
            "installable": False, "modules": modules, "manifest": manifest,
            "manifest_sha256": anchor, "launcher_source": native,
            "launcher_source_sha256": digest(native), "pins": new_pins,
            "pins_sha256": digest(new_pins), "files": files}
