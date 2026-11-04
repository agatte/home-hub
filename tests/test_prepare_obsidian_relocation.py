"""Pure template contract tests. All bytes are synthetic; no Vault access."""
import base64
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare_obsidian_relocation as prep


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.spec = prep.candidate_spec()
        self.blobs = dict(prep.TEMPLATES)
        self.pins = dict(self.spec["files"])
        self.anchor = prep.digest(prep.canonical(self.spec))

    def preview(self):
        return prep.preview(self.spec, self.blobs,
                            reviewed_manifest_sha256=self.anchor,
                            reviewed_files=self.pins)

    def test_deterministic_new_location_and_non_installable(self):
        result = self.preview()
        self.assertEqual(result, self.preview())
        self.assertFalse(result["installable"])
        self.assertIsNone(result["source_commit"])
        self.assertEqual(result["bundle"], prep.BUNDLE)
        self.assertEqual(result["vault"], prep.VAULT)

    def test_reject_old_or_arbitrary_paths_and_forged_commit(self):
        for key, value in [
            ("vault", prep.USER + r"\Documents\HomeHub Knowledge Vault"),
            ("bundle", prep.USER + r"\AppData\Local\HomeHub\ObsidianMirror\5fbc1ddbe2d42d6a1540704b58da75a921b1e7f5"),
            ("bundle", prep.BUNDLE + r"\..\elsewhere"),
            ("release_id", "arbitrary"), ("source_commit", "a" * 40),
        ]:
            with self.subTest(key=key, value=value):
                self.setUp()
                self.spec[key] = value
                with self.assertRaises(ValueError):
                    self.preview()

    def test_reject_wrong_manifest_pin(self):
        self.anchor = "0" * 64
        with self.assertRaises(ValueError):
            self.preview()

    def test_reject_wrong_file_pins_even_if_manifest_resealed(self):
        name = next(iter(prep.FILES))
        self.spec["files"][name] = "0" * 64
        self.pins = copy.deepcopy(self.spec["files"])
        self.anchor = prep.digest(prep.canonical(self.spec))
        with self.assertRaises(ValueError):
            self.preview()

    def test_reject_drift_links_paths_missing_extra(self):
        name = next(iter(prep.FILES))
        cases = [dict(self.blobs, **{name: b"drift"}),
                 dict(self.blobs, **{name: {"symlink": "elsewhere"}}),
                 dict(self.blobs, **{name: Path("synthetic-only")}),
                 {k: v for k, v in self.blobs.items() if k != name},
                 dict(self.blobs, **{"../escape": b"x"}),
                 dict(self.blobs, **{"extra": b"x"})]
        for blobs in cases:
            with self.subTest(blobs=repr(blobs)):
                self.blobs = blobs
                with self.assertRaises(ValueError):
                    self.preview()

    def test_reject_review_mismatch_and_activation(self):
        self.pins = {}
        with self.assertRaises(ValueError):
            self.preview()
        with self.assertRaises(ValueError):
            prep.validate_future_action({}, reviewed_executable="anything",
                                        reviewed_bundle=prep.BUNDLE)


class BundleRecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.old_pins = (root / 'scripts/obsidian_launcher_pins.json').read_bytes()
        cls.original = {name: (root / 'scripts' / name).read_bytes()
                        for name in prep.MODULE_FILES}
        cls.native = base64.b64decode((root / 'tests/obsidian_hidden_launcher_baseline.b64').read_text(encoding='ascii'), validate=True)

    def setUp(self):
        self.modules = dict(self.original)
        self.identity = {'user_root': prep.USER, 'python': prep.PYTHON,
                         'sid': 'S-1-5-21-111-222-333-1001', 'python_sha256': 'a' * 64}

    def recipe(self, **kwargs):
        return prep.bundle_recipe(self.modules, self.old_pins, self.native,
                                  self.identity, **kwargs)

    def test_exact_recipe_and_runtime_bytes(self):
        import ast
        import json
        result = self.recipe()
        self.assertEqual(result, self.recipe())
        self.assertFalse(result['installable'])
        self.assertEqual(prep.NEW_RELEASE, '4fd42377c69901d5f7145857b3da3ef728e45107')
        self.assertEqual(result['files']['launch_obsidian_mirror.py'],
                         'c1f6b6d975d2d3c166b7a01219131f15c8175b6d06424386130b7ff69b2e391a')
        self.assertEqual(result['pins_sha256'],
                         '9d8b4652a78a4c687cab1cfaf7567adac0daa553c0d478524d4934356e83bab7')
        self.assertEqual(result['manifest_sha256'],
                         '99baa0912d01a1fe38bf1190db25ed9e291bf408dc3e97d40439ccd3f43ae099')
        self.assertEqual(len(result['files']), 9)
        manifest = json.loads(result['manifest'])
        self.assertEqual(set(manifest), {'source_commit', 'user_root', 'sid', 'bundle',
                                       'python', 'python_sha256', 'vault', 'files'})
        self.assertEqual(manifest['source_commit'], prep.NEW_RELEASE)
        self.assertEqual(manifest['bundle'], prep.NEW_BUNDLE)
        self.assertEqual(manifest['vault'], prep.VAULT)
        self.assertEqual(prep.digest(result['manifest']), result['manifest_sha256'])
        self.assertEqual(prep.canonical(manifest), result['manifest'])
        self.assertEqual(json.loads(result['pins'])['files'], result['files'])
        for name, old in self.original.items():
            new = result['modules'][name]
            self.assertEqual(prep.digest(new), result['files'][name])
            if name == 'launch_obsidian_mirror.py':
                self.assertEqual(new.replace(prep.NEW_RELEASE.encode(), prep.OLD_RELEASE.encode()), old)
                constants = [node.value.value for node in ast.parse(new).body
                             if isinstance(node, ast.Assign)
                             and any(isinstance(t, ast.Name) and t.id == 'SOURCE_COMMIT'
                                     for t in node.targets)]
                self.assertEqual(constants, [prep.NEW_RELEASE])
            else:
                self.assertEqual(new, old)

    def test_generated_runtime_validates_new_manifest_without_launching(self):
        """Import verified generated bytes as an inert module, never call main()."""
        import json
        from types import ModuleType

        result = self.recipe()
        runtime = ModuleType("obsidian_489_review_only")
        code = compile(result['modules']['launch_obsidian_mirror.py'],
                       "<synthetic-reviewed-launcher>", "exec")
        exec(code, runtime.__dict__)  # __name__ is not __main__; main() stays OFF.
        spec = json.loads(result['manifest'])
        self.assertEqual(runtime.validate_spec(spec), spec)
        for bad in (dict(spec, source_commit=prep.OLD_RELEASE),
                    dict(spec, bundle=prep.NEW_BUNDLE.replace(
                        prep.NEW_RELEASE, prep.OLD_RELEASE)),
                    dict(spec, python=prep.PYTHON + r'\\..\\python.exe')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                runtime.validate_spec(bad)

    def test_exact_native_substitutions_and_quotes(self):
        result = self.recipe()
        old_bundle = prep.NEW_BUNDLE.rsplit('\\', 1)[0] + '\\' + prep.OLD_RELEASE
        expected = self.native.replace(old_bundle.encode(), prep.NEW_BUNDLE.encode()).replace(
            prep.OLD_ANCHOR.encode(), result['manifest_sha256'].encode())
        self.assertEqual(result['launcher_source'], expected)
        self.assertIn(('Bundle = @"' + prep.NEW_BUNDLE + '";').encode(), expected)
        self.assertIn(b'args.Length != 0', expected)
        self.assertIn(b'"-I -B \\"', expected)
        self.assertIn(b'HiddenProcess.Run(Python, arguments, Bundle)', expected)
        self.assertEqual(prep.digest(expected), result['launcher_source_sha256'])

    def test_membership_and_each_module_tamper(self):
        for name in self.original:
            for value in (b'tampered', Path('data-only'), {'symlink': 'elsewhere'}):
                self.modules = dict(self.original, **{name: value})
                with self.assertRaises(ValueError):
                    self.recipe()
            self.modules = {k: v for k, v in self.original.items() if k != name}
            with self.assertRaises(ValueError):
                self.recipe()
        for name in ('extra.py', '../escape.py', 'LAUNCH_OBSIDIAN_MIRROR.py'):
            self.modules = dict(self.original, **{name: b'x'})
            with self.assertRaises(ValueError):
                self.recipe()

    def test_missing_duplicate_constant_and_other_native_drift(self):
        literal = ('SOURCE_COMMIT = "' + prep.OLD_RELEASE + '"').encode()
        for data in (b'no constant', literal + b'\n' + literal):
            with self.assertRaisesRegex(ValueError, 'literal_count'):
                prep.replace_once(data, literal, b'new')
            self.modules = dict(self.original, **{'launch_obsidian_mirror.py': data})
            with self.assertRaises(ValueError):
                self.recipe()
        self.modules = dict(self.original)
        self.native += b'\n// drift'
        with self.assertRaisesRegex(ValueError, 'old_native_pin'):
            self.recipe()

    def test_old_pins_cannot_be_resealed_by_caller(self):
        import json
        pins = json.loads(self.old_pins)
        pins['files']['launch_obsidian_mirror.py'] = '0' * 64
        self.old_pins = prep.canonical(pins)
        with self.assertRaisesRegex(ValueError, 'reviewed_old_pins'):
            self.recipe()

    def test_release_and_target_refusals(self):
        for kwargs in ({'release': prep.OLD_RELEASE}, {'release': 'f' * 40},
                       {'bundle': prep.NEW_BUNDLE.replace(prep.NEW_RELEASE, prep.OLD_RELEASE)},
                       {'bundle': prep.NEW_BUNDLE + r'\..\escape'},
                       {'vault': prep.USER + r'\Documents\HomeHub Knowledge Vault'},
                       {'vault': r'C:\Work\home-hub-project\worktrees\vault'},
                       {'vault': prep.VAULT.lower()}, {'vault': prep.VAULT + '\\'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.recipe(**kwargs)

    def test_identity_data_refusals(self):
        for key, value in [('user_root', r'C:\Users\Other'),
                           ('user_root', prep.USER + r'\..\Anthony'),
                           ('python', prep.PYTHON.lower()),
                           ('python', prep.USER + r'\worktrees\python.exe'),
                           ('python', prep.USER + r'\AppData\Local\Programs\Python\Python312\python.exe'),
                           ('sid', 'S-1-5-21-0-2-3-4'), ('sid', 'S-1-5-21-4294967296-2-3-4'),
                           ('sid', 'S-1-5-21-1-2-3-4\n'),
                           ('python_sha256', 'A' * 64), ('python_sha256', 'a' * 63),
                           ('python_sha256', None)]:
            with self.subTest(key=key, value=value):
                self.setUp()
                self.identity[key] = value
                with self.assertRaises(ValueError):
                    self.recipe()
        self.setUp()
        self.identity['extra'] = 'x'
        with self.assertRaises(ValueError):
            self.recipe()


if __name__ == "__main__":
    unittest.main()
