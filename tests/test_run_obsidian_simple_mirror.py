"""Offline CLI evaluation using only TEMP / Synthetic Vault fixtures."""

from contextlib import ExitStack
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_obsidian_simple_mirror as runner
import test_obsidian_simple_mirror as fixtures
from obsidian_github_docs_source import SourceUnavailable, REPO_PATH
from obsidian_raw_blob_transport import RawBlobUnavailable, github_raw_blob, raw_blob_url
from test_obsidian_raw_blob_transport import FakeOpener, FakeResponse
from test_obsidian_github_docs_source import FILES as SOURCE_FILES


@pytest.fixture
def vault():
    fixture = fixtures.SimpleMirrorTests()
    fixture.setUp()
    try:
        yield fixture
    finally:
        fixture.doCleanups()


def invoke(vault, mode="--check", *, fetch=None, extra=(), expected=None):
    output = StringIO()
    args = [mode, "--vault", str(vault.vault), "--expected-vault",
            str(expected or vault.vault), *extra]
    code = runner.main(args, fetch=fetch or vault.source_api().__getitem__, output=output)
    return code, json.loads(output.getvalue())


def no_writes(stack):
    """Fail on attempted mutation, even if later cleaned up or bytes unchanged."""
    real_open = Path.open

    def read_only(path, mode="r", *args, **kwargs):
        assert not any(c in mode for c in "wax+"), "write open attempted"
        return real_open(path, mode, *args, **kwargs)

    stack.enter_context(patch.object(Path, "open", read_only))
    for name in ("mkdir", "touch", "unlink", "rmdir", "rename", "replace", "chmod"):
        stack.enter_context(patch.object(Path, name, side_effect=AssertionError(name)))
    for module, name in ((os, "replace"), (os, "mkdir"), (tempfile, "mkdtemp"),
                         (tempfile, "mkstemp")):
        stack.enter_context(patch.object(module, name, side_effect=AssertionError(name)))


@pytest.mark.parametrize("commit,code,status", [
    (fixtures.OLD, 0, "no_change"), (fixtures.NEW, 1, "update_available"),
])
def test_check_never_stages_even_new_source(vault, commit, code, status):
    before = vault.snapshot(vault.parent)
    with ExitStack() as stack:
        no_writes(stack)
        with patch.object(runner, "run_once") as writer:
            result = invoke(vault, fetch=vault.source_api(commit).__getitem__)
        writer.assert_not_called()
    assert result == (code, {"status": status, "previous_commit": fixtures.OLD,
                             "commit": commit})
    assert vault.snapshot(vault.parent) == before


@pytest.mark.parametrize("failure", [None, "offline", "http", "redirect", "oversized", "tampered"])
def test_cli_default_raw_check_no_writes_or_rest_fallback(vault, failure):
    api = vault.source_api()
    requests = []

    def fetch(path):
        requests.append(path)
        assert "/git/blobs/" not in path
        return api[path]

    def raw(commit, blob):
        assert commit == fixtures.NEW
        data = SOURCE_FILES[blob.path]
        error = None
        if failure == "offline":
            error = OSError("offline")
        elif failure == "http":
            from urllib.error import HTTPError
            error = HTTPError(raw_blob_url(commit, blob), 429, "limited", {}, None)
        elif failure == "redirect":
            error = RawBlobUnavailable("raw_redirect_refused")
        elif failure == "oversized":
            data += b"extra"
        elif failure == "tampered":
            data = b"x" * len(data)
        opener = FakeOpener(FakeResponse(raw_blob_url(commit, blob), data), error)
        return github_raw_blob(commit, blob, opener=opener)

    before = vault.snapshot(vault.parent)
    output = StringIO()
    with ExitStack() as stack:
        no_writes(stack)
        stack.enter_context(patch.object(runner, "github_json", side_effect=fetch))
        stack.enter_context(patch.object(runner, "github_raw_blob", side_effect=raw))
        writer = stack.enter_context(patch.object(runner, "run_once"))
        code = runner.main(["--check", "--vault", str(vault.vault),
                            "--expected-vault", str(vault.vault)], output=output)
        writer.assert_not_called()
    assert code == (3 if failure else 1)
    assert json.loads(output.getvalue())["status"] == (
        "source_unavailable" if failure else "update_available")
    assert len(requests) == (5 if failure else 6)
    assert vault.snapshot(vault.parent) == before


def test_injected_fetch_never_selects_live_raw(vault):
    with patch.object(runner, "github_raw_blob", side_effect=AssertionError("network")) as raw:
        assert invoke(vault)[0] == 1
    raw.assert_not_called()


def test_default_apply_passes_raw_transport_to_library(vault):
    with patch.object(runner, "run_once", return_value=Mock(
        state="updated", previous_commit=fixtures.OLD, commit=fixtures.NEW
    )) as writer:
        assert runner.main(["--apply", "--approve-local-evaluation", "--vault",
                            str(vault.vault), "--expected-vault", str(vault.vault)],
                           output=StringIO()) == 0
    assert writer.call_args.kwargs["blob_source"] is runner.github_raw_blob


@pytest.mark.parametrize("mode", ["--check", "--apply"])
@pytest.mark.parametrize("failure", ["offline", "partial", "marker", "tampered"])
def test_refusals_no_writes(vault, mode, failure):
    api = vault.source_api()
    fetch = Mock(side_effect=api.__getitem__)
    if failure == "offline":
        fetch.side_effect = SourceUnavailable("secret must never appear")
    elif failure == "partial":
        api[REPO_PATH + "/git/trees/" + "e" * 40 + "?recursive=1"]["truncated"] = True
    elif failure == "marker":
        (vault.parent / ".Synthetic Vault-homehub-simple.pending").write_bytes(b"partial")
    else:
        (vault.managed / "AGENTS.md").write_bytes(b"tampered")
    before = vault.snapshot(vault.parent)
    with ExitStack() as stack:
        no_writes(stack)
        code, report = invoke(vault, mode, fetch=fetch,
                              extra=("--approve-local-evaluation",) if mode == "--apply" else ())
    assert code == (3 if failure in {"offline", "partial"} else 2)
    assert "secret" not in json.dumps(report)
    if failure in {"marker", "tampered"}:
        fetch.assert_not_called()
    assert vault.snapshot(vault.parent) == before


def test_exact_mismatch_and_missing_approval_refuse_before_call(vault):
    with patch.object(runner, "run_once") as writer:
        fetch = Mock(side_effect=AssertionError("network"))
        assert invoke(vault, "--apply", fetch=fetch)[0] == 2
        assert invoke(vault, "--apply", fetch=fetch, expected=vault.parent / "Other",
                      extra=("--approve-local-evaluation",))[0] == 2
        writer.assert_not_called()
        fetch.assert_not_called()


def test_explicit_apply_calls_library_once(vault):
    with patch.object(runner, "run_once", wraps=runner.run_once) as writer:
        code, report = invoke(vault, "--apply", extra=("--approve-local-evaluation",))
    writer.assert_called_once()
    assert code == 0
    assert report["status"] == "updated"
    vault.assert_personal()


def test_apply_nochange_has_no_writes(vault):
    with ExitStack() as stack:
        no_writes(stack)
        assert invoke(vault, "--apply", fetch=vault.source_api(fixtures.OLD).__getitem__,
                      extra=("--approve-local-evaluation",))[1]["status"] == "no_change"


@pytest.mark.parametrize("error,code", [(OSError("secret"), 2),
                                       (RuntimeError("secret"), 4)])
def test_apply_errors_are_bounded(vault, error, code):
    with patch.object(runner, "run_once", side_effect=error) as writer:
        result = invoke(vault, "--apply", extra=("--approve-local-evaluation",))
    writer.assert_called_once()
    assert result[0] == code
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("raw", ["relative", "C:relative", "C:\\Vault\\..\\Other",
                                "C:\\Vault\\", "C:\\NUL", "\\\\server\\share\\Vault"])
def test_ambiguous_paths(raw):
    with pytest.raises(ValueError):
        runner.exact_path(raw)


def test_no_implicit_mode_or_target():
    with patch.object(runner, "run_once") as writer:
        for args in ([], ["--check"], ["--apply", "--approve-local-evaluation"]):
            with pytest.raises(SystemExit) as error:
                runner.main(args)
            assert error.value.code == 2
        writer.assert_not_called()
