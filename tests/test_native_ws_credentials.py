from __future__ import annotations

import ast
import ctypes
import logging
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from backend.services.pc_agent import native_ws_credentials as native

TOKEN = 'a' * 32 + '.' + 'b' * 43


@pytest.fixture(autouse=True)
def no_real_credentials(monkeypatch):
    monkeypatch.setattr(native.sys, 'platform', 'win32')
    monkeypatch.setattr(native, '_read_windows', lambda target: None)


@pytest.mark.parametrize('profile', ['windows_desktop', 'desktop_notifier'])
def test_fixed_profile_fresh_read(monkeypatch, profile):
    calls = []
    def read(target):
        calls.append(target)
        return TOKEN
    monkeypatch.setattr(native, '_read_windows', read)
    for _ in range(2):
        options = native.connection_options(profile, 'wss://configured.example/ws')
        assert options['additional_headers'] == {'Authorization': 'Bearer ' + TOKEN}
        assert options['logger'].getEffectiveLevel() > logging.CRITICAL
    assert calls == [native._TARGETS[profile] + '/configured.example:443/ws'] * 2


def test_unknown_profile_no_read(monkeypatch):
    monkeypatch.setattr(native, '_read_windows', lambda _: pytest.fail('unexpected read'))
    with pytest.raises(native.NativeCredentialError, match='profile denied'):
        native.connection_options('owner_browser', 'wss://configured.example/ws')


@pytest.mark.parametrize('platform', ['linux', 'win32'])
@pytest.mark.parametrize('scheme', ['ws', 'wss'])
def test_legacy_absence(monkeypatch, platform, scheme):
    monkeypatch.setattr(native.sys, 'platform', platform)
    if platform != 'win32':
        monkeypatch.setattr(native, '_read_windows', lambda _: pytest.fail('non-Windows read'))
    assert 'additional_headers' not in native.connection_options(
        'windows_desktop', scheme + '://192.168.86.210:8000/ws')


@pytest.mark.parametrize('token', ['', 'bad', TOKEN + '\n', TOKEN.upper(), TOKEN + '\x00'])
def test_invalid_secret_sanitized(monkeypatch, token):
    monkeypatch.setattr(native, '_read_windows', lambda _: token)
    with pytest.raises(native.NativeCredentialError) as error:
        native.connection_options('desktop_notifier', 'wss://configured.example/ws')
    assert str(error.value) == 'credential invalid'


@pytest.mark.parametrize('url', ['ws://127.0.0.1/ws', 'ws://192.168.86.210/ws'])
def test_no_plaintext_bearer(monkeypatch, url):
    monkeypatch.setattr(native, '_read_windows', lambda _: pytest.fail('plaintext read'))
    assert 'additional_headers' not in native.connection_options('windows_desktop', url)


@pytest.mark.parametrize('url', [
    'wss://user:secret@configured.example/ws', 'wss://configured.example/ws?token=secret',
    'wss://configured.example/ws#secret', 'https://configured.example/ws',
    'wss://configured.example:bad/ws', 'wss://[bad/ws', 'wss://configured.example/\nws',
])
def test_bad_url_no_read(monkeypatch, url):
    monkeypatch.setattr(native, '_read_windows', lambda _: pytest.fail('unexpected read'))
    with pytest.raises(native.NativeCredentialError) as error:
        native.connection_options('desktop_notifier', url)
    assert str(error.value) == 'endpoint denied'
    assert error.value.__suppress_context__


def test_provider_error_discarded(monkeypatch):
    def read(_):
        raise RuntimeError(TOKEN)
    monkeypatch.setattr(native, '_read_windows', read)
    with pytest.raises(native.NativeCredentialError) as error:
        native.connection_options('desktop_notifier', 'wss://configured.example/ws')
    assert TOKEN not in str(error.value)
    assert error.value.__context__ is None


@pytest.mark.parametrize('invalid', [None, 'size', 'profile', 'destination', 'decode'])
def test_mock_windows_api_frees(monkeypatch, invalid):
    # Exercise actual ctypes structure/pointer ownership without loading a DLL.
    raw = TOKEN.encode('utf-16-le') if invalid != 'decode' else b'\x00\xd8' * 76
    blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    target = native._TARGETS['windows_desktop'] + '/configured.example:443/ws'
    stored_target = target
    if invalid == 'profile':
        stored_target = target.replace('windows_desktop', 'desktop_notifier')
    elif invalid == 'destination':
        stored_target = target.replace('configured.example', 'attacker.example')
    credential = native._Credential(Type=1, TargetName=stored_target,
        CredentialBlobSize=2 if invalid == 'size' else len(raw), CredentialBlob=blob)
    freed = []
    def read(name, kind, flags, output):
        assert (name, kind, flags) == (target, 1, 0)
        ctypes.cast(output, ctypes.POINTER(ctypes.POINTER(native._Credential)))[0] = ctypes.pointer(credential)
        return True
    class Function:
        def __init__(self, fn):
            self.fn = fn
        def __call__(self, *args):
            return self.fn(*args)
    api = SimpleNamespace(CredReadW=Function(read), CredFree=Function(freed.append))
    def load(name, **kwargs):
        assert name == 'Advapi32.dll'
        assert kwargs == {'use_last_error': True, 'winmode': 0x800}
        return api
    monkeypatch.setattr(ctypes, 'WinDLL', load, raising=False)
    # Recover original implementation, replaced by the autouse mock.
    namespace = {'__name__': 'synthetic_native'}
    exec(compile(Path(native.__file__).read_text(encoding='utf-8-sig'), native.__file__, 'exec'), namespace)
    if invalid:
        with pytest.raises((namespace['NativeCredentialError'], UnicodeDecodeError)):
            namespace['_read_windows'](target)
    else:
        assert namespace['_read_windows'](target) == TOKEN
    assert len(freed) == 1


@pytest.mark.parametrize('module,cls,profile', [
    ('monitor_brightness', 'WsListener', 'windows_desktop'),
    ('desktop_notifier', 'WsWorker', 'desktop_notifier'),
])
def test_worker_reconnect_stop_and_sanitized_logs(monkeypatch, caplog, module, cls, profile):
    # Compile just the worker class: no Qt, logger files, monitors or other device I/O.
    path = Path('backend/services/pc_agent') / (module + '.py')
    tree = ast.parse(path.read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    stop = threading.Event()
    calls = []
    def options(p, url):
        calls.append((p, url))
        return native.connection_options(p, url)
    monkeypatch.setattr(native, '_read_windows', lambda target: TOKEN if target ==
        native._TARGETS[profile] + '/configured.example:443/ws' else None)
    def connect(url, **kwargs):
        assert kwargs['additional_headers']['Authorization'] == 'Bearer ' + TOKEN
        if len(calls) == 2:
            stop.set()
        raise OSError(TOKEN)
    namespace = dict(threading=threading, connection_options=options,
        websockets=SimpleNamespace(sync=SimpleNamespace(client=SimpleNamespace(connect=connect)),
            exceptions=SimpleNamespace(WebSocketException=ValueError)),
        logger=logging.getLogger('synthetic.worker'), _HAS_WS=True,
        RECONNECT_INITIAL_S=0, RECONNECT_MAX_S=0,
        WS_RECONNECT_INITIAL_S=0, WS_RECONNECT_MAX_S=0)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), node], type_ignores=[])), str(path), 'exec'), namespace)
    worker = namespace[cls].__new__(namespace[cls])
    worker._url = 'wss://configured.example/ws'
    worker._stop = stop
    worker.run()
    assert calls == [(profile, worker._url)] * 2
    assert TOKEN not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.parametrize('profile', ['windows_desktop', 'desktop_notifier'])
@pytest.mark.parametrize('url', [
    'wss://attacker.example/ws', 'wss://homehub.example:444/ws',
    'wss://homehub.example.attacker.example/ws',
    'wss://127.0.0.1/ws', 'wss://[::1]/ws',
])
def test_changed_destination_cannot_reuse_token(monkeypatch, profile, url):
    approved = native._TARGETS[profile] + '/homehub.example:443/ws'
    calls = []
    def read(target):
        calls.append(target)
        return TOKEN if target == approved else None
    monkeypatch.setattr(native, '_read_windows', read)
    assert 'additional_headers' not in native.connection_options(profile, url)
    assert calls == [native._TARGETS[profile] + '/' + native._endpoint(url)[1]]
    assert calls[0] != approved
    assert native.connection_options(profile, 'wss://homehub.example/ws')[
        'additional_headers'] == {'Authorization': 'Bearer ' + TOKEN}


def test_profile_binding(monkeypatch):
    approved = native._TARGETS['windows_desktop'] + '/homehub.example:443/ws'
    monkeypatch.setattr(native, '_read_windows', lambda target: TOKEN if target == approved else None)
    assert 'additional_headers' not in native.connection_options(
        'desktop_notifier', 'wss://homehub.example/ws')


@pytest.mark.parametrize('url', [
    'wss://homehub.example/other', 'wss://homehub.example/ws/',
    'wss://homehub.example/%77s', 'wss://homehub.example/ws?',
    'wss://homehub.example/ws#', 'wss://homehub.example./ws',
    'wss://HOMEHUB.example/ws', 'wss://homehub.example:0443/ws',
    'wss://homehub.example:0/ws', 'wss://homehub.example:65536/ws',
    'wss://homehub.example:/ws', 'wss://homehub%2eexample/ws',
    'wss://homehub.example\\attacker.example/ws', 'wss://xn--homehub-9jg.example/ws',
    'wss://h?mehub.example/ws', 'wss://127.1/ws', 'wss://0177.0.0.1/ws',
    'wss://[0:0:0:0:0:0:0:1]/ws', 'wss://[::1%25eth0]/ws',
    'wss://[::FFFF:127.0.0.1]/ws',
])
def test_strict_endpoint_no_lookup(monkeypatch, url):
    monkeypatch.setattr(native, '_read_windows', lambda _: pytest.fail('unexpected read'))
    with pytest.raises(native.NativeCredentialError, match='endpoint denied'):
        native.connection_options('windows_desktop', url)


@pytest.mark.parametrize('authority,target', [
    ('homehub.example', 'homehub.example:443'),
    ('homehub.example:443', 'homehub.example:443'),
    ('homehub.example:8443', 'homehub.example:8443'),
    ('192.168.1.2', '192.168.1.2:443'),
    ('[::1]', '[::1]:443'), ('[2001:db8::1]:8443', '[2001:db8::1]:8443'),
])
def test_exact_canonical_target(monkeypatch, caplog, authority, target):
    calls = []
    def read(name):
        calls.append(name)
        return TOKEN
    monkeypatch.setattr(native, '_read_windows', read)
    assert native.connection_options('windows_desktop', 'wss://' + authority + '/ws')[
        'additional_headers'] == {'Authorization': 'Bearer ' + TOKEN}
    assert calls == [native._TARGETS['windows_desktop'] + '/' + target + '/ws']
    assert not caplog.records
