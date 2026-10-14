"""Disposable synthetic tests for #399 fail-closed refresh mutex."""

from pathlib import Path
import json
import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from obsidian_refresh_lock import exclusive_refresh_lock, RefreshBusy  # noqa: E402


def test_acquire_releases_exact_lock_but_preserves_all_vault_files(tmp_path):
    vault = tmp_path / 'Permanent Vault'
    vault.mkdir()
    (vault / 'Personal Note.md').write_bytes(b'private')
    (vault / '.obsidian').mkdir()
    (vault / '.obsidian' / 'app.json').write_bytes(b'{}')
    with exclusive_refresh_lock(vault, expected_vault=vault) as lock:
        assert lock.parent == tmp_path
        assert lock.exists()
        contents = json.loads(lock.read_text())
        assert contents['schema'] == 1 and len(contents['token']) == 32
        assert (vault / 'Personal Note.md').read_bytes() == b'private'
    assert not lock.exists()
    assert (vault / 'Personal Note.md').read_bytes() == b'private'
    assert (vault / '.obsidian' / 'app.json').read_bytes() == b'{}'


def test_concurrent_lock_refuses_without_replacing_first(tmp_path):
    vault = tmp_path / 'Vault'
    vault.mkdir()
    with exclusive_refresh_lock(vault, expected_vault=vault) as lock:
        first = lock.read_bytes()
        with pytest.raises(RefreshBusy, match='already_exists_or_stale'):
            with exclusive_refresh_lock(vault, expected_vault=vault):
                raise AssertionError('entered second lock')
        assert lock.read_bytes() == first
    assert not lock.exists()


def test_preexisting_stale_lock_not_removed(tmp_path):
    vault = tmp_path / 'Vault'
    vault.mkdir()
    lock = tmp_path / '.Vault-homehub-refresh.lock'
    lock.write_text('stale process may be alive')
    with pytest.raises(RefreshBusy):
        with exclusive_refresh_lock(vault, expected_vault=vault):
            raise AssertionError('entered')
    assert lock.read_text() == 'stale process may be alive'


def test_exceptions_release_only_owned_lock(tmp_path):
    vault = tmp_path / 'Vault'
    vault.mkdir()
    with pytest.raises(KeyError):
        with exclusive_refresh_lock(vault, expected_vault=vault):
            raise KeyError('synthetic executor error')
    assert not (tmp_path / '.Vault-homehub-refresh.lock').exists()


def test_mutated_lock_contents_refuses_cleanup(tmp_path):
    vault = tmp_path / 'Vault'
    vault.mkdir()
    with pytest.raises(RuntimeError, match='ownership_changed_preserved'):
        with exclusive_refresh_lock(vault, expected_vault=vault) as lock:
            lock.write_text('{"token": "someone-else"}')
    assert lock.exists()


def test_invalid_vault_and_relative_path_rejected_without_side_effects(tmp_path):
    missing = tmp_path / 'missing'
    for location in (missing, Path('relative-vault'), tmp_path.parent.parent / '__not_a_real_vault__'):
        with pytest.raises(ValueError):
            with exclusive_refresh_lock(location, expected_vault=location):
                pass
    assert not (tmp_path / '.missing-homehub-refresh.lock').exists()


def test_symlinked_vault_refused_when_supported(tmp_path):
    vault = tmp_path / 'Vault'
    vault.mkdir()
    link = tmp_path / 'Link'
    try:
        link.symlink_to(vault, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('link fixture unsupported')
    with pytest.raises(ValueError, match='Refusing linked path'):
        with exclusive_refresh_lock(link, expected_vault=link):
            pass
    assert not (tmp_path / '.Link-homehub-refresh.lock').exists()


def test_refuses_unexpected_vault_even_if_both_directories_exist(tmp_path):
    approved = tmp_path / 'Intended Vault'
    wrong = tmp_path / 'Other Vault'
    approved.mkdir()
    wrong.mkdir()
    with pytest.raises(ValueError, match='unexpected_or_invalid_vault_path'):
        with exclusive_refresh_lock(wrong, expected_vault=approved):
            raise AssertionError('wrong vault accepted')
    assert list(tmp_path.glob('*.lock')) == []


def test_second_process_fails_to_acquire_while_owned(tmp_path):
    import subprocess
    import os

    vault = tmp_path / 'Vault'
    vault.mkdir()
    code = (
        'from pathlib import Path; from obsidian_refresh_lock import exclusive_refresh_lock, '
        'RefreshBusy; import sys; p=Path(sys.argv[1]); '
        'x=exclusive_refresh_lock(p, expected_vault=p); '
        'x.__enter__(); print("UNEXPECTED_OWNERSHIP")'
    )
    with exclusive_refresh_lock(vault, expected_vault=vault):
        env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'scripts')}
        child = subprocess.run([sys.executable, '-c', code, str(vault)],
                               capture_output=True, text=True, env=env, timeout=10)
        assert child.returncode != 0
        assert 'RefreshBusy' in child.stderr
        assert 'UNEXPECTED_OWNERSHIP' not in child.stdout


def test_crashed_process_lock_remains_for_manual_recovery(tmp_path):
    import subprocess
    import os

    vault = tmp_path / 'Vault'
    vault.mkdir()
    code = (
        'from pathlib import Path; from obsidian_refresh_lock import exclusive_refresh_lock; '
        'import os,sys; p=Path(sys.argv[1]); '
        'x=exclusive_refresh_lock(p, expected_vault=p); x.__enter__(); os._exit(0)'
    )
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'scripts')}
    child = subprocess.run([sys.executable, '-c', code, str(vault)],
                           capture_output=True, text=True, env=env, timeout=10)
    assert child.returncode == 0
    lock = tmp_path / '.Vault-homehub-refresh.lock'
    assert lock.exists()
    before = lock.read_bytes()
    with pytest.raises(RefreshBusy):
        with exclusive_refresh_lock(vault, expected_vault=vault):
            raise AssertionError('crashed lock was ignored')
    assert lock.read_bytes() == before
