import csv
import inspect
import os
from pathlib import Path
import pytest
from scripts import apple_music_local_artist_review as m
from backend.services import apple_music_daily_join_audit as reader

HEADER = ['Track Description', 'Date Played', 'Play Count', 'Play Duration Milliseconds']


@pytest.fixture(autouse=True)
def synthetic_local_gate(monkeypatch, request):
    # Production's Windows-only location guard must remain active. On Linux
    # CI, only CSVs created inside THIS test's temporary folder may pass it.
    if os.name != 'nt' and 'tmp_path' in request.fixturenames:
        temporary = request.getfixturevalue('tmp_path')
        actual_gate = m._require_local_file

        def checked_synthetic(path):
            candidate = Path(path)
            if candidate.parent == temporary and candidate.name == m.BASENAME:
                return
            return actual_gate(path)

        monkeypatch.setattr(m, '_require_local_file', checked_synthetic)


def fixture(tmp_path, rows, encoding='utf-8-sig'):
    path = tmp_path / m.BASENAME
    with path.open('w', newline='', encoding=encoding) as stream:
        writer = csv.writer(stream)
        writer.writerow(HEADER)
        writer.writerows(rows)
    return path


def row(label='Fiction - Song', day='20260101', plays='1', duration='100'):
    return [label, day, plays, duration]


def test_canonical_duplicates_collisions(tmp_path):
    rows = [row(), row(), row('Fiction - Other'), row(day='20260102'),
            row('Alpha - Shared'), row('Beta - Shared'),
            row('Conflict - Tune'), row('Conflict - Tune', plays='2'),
            row('Ambiguous - Many - Parts'), row(day='bad')]
    session = m.read_selected_source(fixture(tmp_path, rows))
    assert session.candidates == [('fiction', '2-3 days')]
    assert session.summary['counts']['candidate_artist_label_days'] == 2
    assert session.summary['artist_label_day_histogram']['2_to_3_days'] == 1
    assert 'fiction' not in repr(session)
    session.actions['0'] = 'Reject label'
    session.discard()
    assert session.candidates == [] and session.actions == {} and session.summary is None


@pytest.mark.parametrize('count,band', [(1,'1 day'), (3,'2-3 days'), (9,'4-9 days'), (10,'10+ days')])
def test_bands(tmp_path, count, band):
    session = m.read_selected_source(fixture(tmp_path, [row(day=f'202601{n:02}') for n in range(1,count+1)]))
    assert session.candidates == [('fiction', band)]


@pytest.mark.parametrize('text', ['Evil\u202e - Tune', 'Evil\x00 - Tune', 'Evil\u200b - Tune',
                                 'Evil\tName - Tune', 'Evil\nName - Tune',
                                 'Evil\rName - Tune', 'Evil\x85Name - Tune'])
def test_deceptive_labels_fail_closed(tmp_path, text, capsys):
    with pytest.raises(m.ReviewRejected) as error:
        m.read_selected_source(fixture(tmp_path, [row(text)]))
    assert str(error.value) == m.SAFE_ERROR
    assert capsys.readouterr() == ('','')


def test_bom_multiline_and_normalization(tmp_path):
    session = m.read_selected_source(fixture(tmp_path, [row('ＦＩＣＴＩＯＮ - Song\nName')]))
    assert session.candidates == [('fiction','1 day')]


@pytest.mark.parametrize('kind', ['schema','decode','field','columns','row','size','unstable'])
def test_shared_reader_protection(tmp_path, monkeypatch, kind):
    path = fixture(tmp_path, [row()])
    if kind == 'schema':
        path.write_text('secret\nsecret\n')
    elif kind == 'decode':
        path.write_bytes(b'\xff')
    elif kind == 'field':
        path = fixture(tmp_path, [row('X'*8193)])
    elif kind == 'columns':
        path.write_text(','.join(['X']*257))
    elif kind == 'row':
        monkeypatch.setattr(reader,'MAX_ROWS',0)
    elif kind == 'size':
        monkeypatch.setattr(reader,'MAX_BYTES',10)
    else:
        real = reader.os.fstat
        calls = []
        def changed(fd):
            value = real(fd)
            calls.append(1)
            if len(calls) == 2:
                from types import SimpleNamespace
                return SimpleNamespace(st_size=value.st_size+1, st_mtime_ns=value.st_mtime_ns)
            return value
        monkeypatch.setattr(reader.os,'fstat',changed)
    with pytest.raises(m.ReviewRejected, match=m.SAFE_ERROR):
        m.read_selected_source(path)


def test_candidate_cap(tmp_path):
    with pytest.raises(m.ReviewRejected):
        m.read_selected_source(fixture(tmp_path, [row(f'Fiction {n} - Song {n}') for n in range(5001)]))


def test_mismatch_fails(tmp_path, monkeypatch):
    original = m.preview_artist_label_days
    def wrong(rows):
        value = original(rows)
        value['counts']['candidate_artist_label_days'] += 1
        return value
    monkeypatch.setattr(m,'preview_artist_label_days',wrong)
    with pytest.raises(m.ReviewRejected):
        m.read_selected_source(fixture(tmp_path,[row()]))


@pytest.mark.parametrize('args', [['private-path.csv'], ['--csv','private-path.csv'], ['--local-review','private-path.csv'], ['--local','private-path.csv']])
def test_cli_redaction(args, capsys):
    with pytest.raises(SystemExit) as error:
        m.main(args)
    assert error.value.code == 2
    assert capsys.readouterr() == ('', 'Local review arguments rejected.\n')


def test_inert(monkeypatch):
    monkeypatch.setattr(m,'LocalReviewWindow',lambda root: pytest.fail('GUI started'))
    assert m.main([]) == 0


@pytest.fixture
def window():
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError as error:
        if 'display' in str(error).lower():
            pytest.skip('Tk display unavailable')
        raise
    root.withdraw()
    app = m.LocalReviewWindow(root)
    yield app
    app.close()


def test_consent_and_single_read(window, tmp_path, monkeypatch):
    path = fixture(tmp_path,[row()])
    reads = []
    original = m.read_selected_source
    def read(path):
        reads.append(1)
        return original(path)
    monkeypatch.setattr(m,'read_selected_source',read)
    assert not reads
    window.pick = lambda **kw: ''
    window.select()
    window.pick = lambda **kw: str(path)
    window.confirm = lambda *a, **kw: False
    window.select()
    assert not reads and not window.used and not window.session.candidates
    window.confirm = lambda *a, **kw: True
    window.select()
    window.select()
    assert reads == [1]
    assert len(window.tree.get_children()) == 1
    window.tree.selection_set('0')
    window.review('Reject label')
    assert window.session.actions['0'] == 'Reject label'
    window.review('Reset')
    assert window.session.actions['0'] == 'Unreviewed'


@pytest.mark.parametrize('mode',['button','external','protocol','callback'])
def test_cleanup(window, mode, capsys):
    window.session.candidates.append(('fiction','1 day'))
    window.session.summary = {'count':1}
    window.alert = lambda *a, **kw: None
    if mode == 'external':
        window.root.destroy()
    elif mode == 'callback':
        window.callback_error(ValueError, ValueError('PRIVATE'), None)
    elif mode == 'protocol':
        window.root.tk.call(window.root.protocol('WM_DELETE_WINDOW'))
    else:
        window.close()
    assert window.session.candidates == [] and window.session.summary is None
    assert capsys.readouterr() == ('','')


def test_unexpected_read_redacted(window, monkeypatch, capsys):
    window.pick = lambda **kw: 'PRIVATE'
    window.confirm = lambda *a, **kw: True
    def broken(path):
        raise RuntimeError('PRIVATE')
    monkeypatch.setattr(m,'read_selected_source',broken)
    alerts = []
    window.alert = lambda title, message, **kw: alerts.append(message)
    window.select()
    assert alerts == [m.SAFE_ERROR]
    assert capsys.readouterr() == ('','')


def test_no_runtime_integrations():
    import ast
    tree = ast.parse(inspect.getsource(m))
    imports = [node.module for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
    imports += [alias.name for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names]
    assert all(not any(word in name.lower() for word in ('music_taste','bandit','sonos','sqlite','requests','socket','importer')) for name in imports)

@pytest.mark.parametrize('prefix', ['\\\\synthetic-server\\share\\', '\\\\?\\C:\\',
                                    '\\\\.\\C:\\', 'C:', '', '\\', 'C:\\..\\'])
def test_network_syntax_never_queries_or_opens(prefix, monkeypatch, capsys):
    def forbidden(*args):
        pytest.fail('unexpected native query or source open')
    monkeypatch.setattr(m, '_windows_volume_api', forbidden)
    monkeypatch.setattr(m, '_csv_rows', forbidden)
    with pytest.raises(m.ReviewRejected) as error:
        m.read_selected_source(prefix + m.BASENAME)
    assert str(error.value) == m.SAFE_ERROR
    assert capsys.readouterr() == ('', '')


@pytest.mark.parametrize('kind', ['remote', 'file_reparse', 'parent_reparse',
                                  'root_reparse', 'missing', 'directory', 'parent_file'])
def test_native_policy_rejects_before_open(kind, monkeypatch, capsys):
    calls = []
    def drive(root):
        assert root == 'C:\\'
        return 4 if kind == 'remote' else 3
    def attributes(path):
        calls.append(path)
        leaf = path.endswith(m.BASENAME)
        if kind == 'missing' and leaf:
            return 0xFFFFFFFF
        if ((kind == 'file_reparse' and leaf)
                or (kind == 'parent_reparse' and path == 'C:\\synthetic')
                or (kind == 'root_reparse' and path == 'C:\\')):
            return 0x400 | (0 if leaf else 0x10)
        if kind == 'parent_file' and path == 'C:\\synthetic':
            return 0
        return 0x10 if not leaf or kind == 'directory' else 0
    monkeypatch.setattr(m, '_windows_volume_api', lambda: (drive, attributes))
    monkeypatch.setattr(m, '_running_on_windows', lambda: True)
    monkeypatch.setattr(m, '_csv_rows', lambda *a: pytest.fail('source opened'))
    with pytest.raises(m.ReviewRejected) as error:
        m.read_selected_source('C:\\synthetic\\' + m.BASENAME)
    assert str(error.value) == m.SAFE_ERROR
    if kind == 'remote':
        assert calls == []
    if kind == 'parent_reparse':
        assert len(calls) == 2
    assert capsys.readouterr() == ('', '')


def test_trailing_malformed_discards_before_ui(window, tmp_path, capsys):
    path = fixture(tmp_path, [row()])
    with path.open('a', encoding='utf-8') as stream:
        stream.write('"unterminated')
    window.pick = lambda **kw: str(path)
    window.confirm = lambda *a, **kw: True
    alerts = []
    window.alert = lambda title, message, **kw: alerts.append(message)
    children = []
    original = window.tree.delete
    def clear(*items):
        children.extend(window.tree.get_children())
        original(*items)
    window.tree.delete = clear
    window.select()
    assert children == []
    assert window.session.candidates == [] and window.session.summary is None
    assert alerts == [m.SAFE_ERROR]
    assert capsys.readouterr() == ('', '')


def test_insert_failure_clears_partial_tree(window, tmp_path, capsys):
    path = fixture(tmp_path, [row(), row('Other - Tune')])
    window.pick = lambda **kw: str(path)
    window.confirm = lambda *a, **kw: True
    insert = window.tree.insert
    count = []
    def broken(*args, **kwargs):
        if count:
            raise RuntimeError('PRIVATE')
        count.append(1)
        return insert(*args, **kwargs)
    window.tree.insert = broken
    alerts = []
    def alert(title, message, **kw):
        assert window.tree.get_children() == ()
        alerts.append(message)
    window.alert = alert
    window.select()
    assert count == [1]
    assert window.session.candidates == [] and window.session.actions == {}
    assert window.session.summary is None
    assert alerts == [m.SAFE_ERROR]
    assert capsys.readouterr() == ('', '')


def test_success_is_silent(tmp_path, capsys):
    assert m.read_selected_source(fixture(tmp_path, [row()])).candidates
    assert capsys.readouterr() == ('', '')
