"""No writes, no live network, fake exact validated bundle only."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256, sha1
import unittest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from obsidian_refresh_policy import assess_refresh
from obsidian_github_docs_source import VerifiedDocs
from obsidian_source_verifier import DocBlob

OLD = 'a' * 40
NEW = 'b' * 40
FILES = {
    'AGENTS.md': b'hello\n',
    'docs/PROJECT_SPEC.md': b'spec\n',
    'docs/PROJECT_ADMIN_HUB.md': b'hub\n',
    'docs/README.md': b'readme\n',
}

def bundle(contents=None, commit=NEW):
    data = dict(FILES if contents is None else contents)
    docs = tuple(DocBlob(name, sha1(b'blob '+str(len(raw)).encode()+b'\x00'+raw).hexdigest(), '100644', len(raw)) for name, raw in sorted(data.items()))
    return VerifiedDocs(commit=commit, tree='c'*40, files=docs, contents=data)

def manifest():
    return {'schema':1, 'source_commit':OLD, 'sha256': {**{name:sha256(raw).hexdigest() for name,raw in FILES.items()},'00-START-HERE.md':'0'*64,'SNAPSHOT.md':'0'*64}}

def assess(**changes):
    args={'current_manifest':manifest(),'sealed_old_source_verified':True, 'docs':bundle(), 'history':'forward', 'app_state':'closed', 'source_identity_verified':True}
    args.update(changes)
    return assess_refresh(**args)

class PolicyTests(unittest.TestCase):
    def test_positive_is_plan_not_write(self):
        result=assess()
        self.assertEqual(result.state,'eligible_for_authorized_host_preflight')
        self.assertFalse(result.refresh_authorized)
        self.assertEqual(result.paths, {'added':(), 'modified':(), 'removed':()})
    def test_new_modified_and_removed_files(self):
        m=manifest()
        m['sha256']['docs/OLD.md'] = sha256(b'old').hexdigest()
        docs=bundle({**FILES, 'docs/NEW.md':b'new', 'docs/PROJECT_SPEC.md':b'new spec'})
        result=assess(docs=docs, current_manifest=m)
        self.assertEqual(result.paths['added'],('docs/NEW.md',))
        self.assertEqual(result.paths['removed'],('docs/OLD.md',))
        self.assertEqual(result.paths['modified'],('docs/PROJECT_SPEC.md',))
    def test_open_deferred(self):
        self.assertEqual(assess(app_state='open').reason,'obsidian_not_proven_closed')
    def test_unknown_deferred(self):
        self.assertEqual(assess(app_state='unknown').state,'deferred')
    def test_missing_app_state_deferred(self):
        self.assertEqual(assess(app_state='').state,'deferred')
    def test_corrupt_old_seal_refused(self):
        self.assertEqual(assess(sealed_old_source_verified=False).state,'refused')
    def test_unverified_source_identity_refused(self):
        self.assertEqual(assess(source_identity_verified=False).state,'refused')
    def test_diverged_refused(self):
        self.assertEqual(assess(history='diverged').reason,'no_verified_forward_ancestry')
    def test_missing_history_refused(self):
        self.assertEqual(assess(history='').state,'refused')
    def test_invalid_manifest_refused(self):
        m = manifest()
        m['source_commit'] = 'not-sha'
        self.assertEqual(assess(current_manifest=m).state,'refused')
    def test_invalid_hash_index_refused(self):
        m = manifest()
        m.pop('sha256')
        self.assertEqual(assess(current_manifest=m).reason,'invalid_existing_manifest')
    def test_noop(self):
        result=assess(docs=bundle(commit=OLD),history='identical',app_state='open')
        self.assertEqual(result.state,'no_change')
        self.assertFalse(result.refresh_authorized)
    def test_matching_sha_but_different_docs_refused(self):
        altered_manifest = manifest()
        altered_manifest['sha256']['AGENTS.md'] = '0' * 64
        result = assess(docs=bundle(commit=OLD), history='identical', current_manifest=altered_manifest)
        self.assertEqual(result.reason,'same_sha_document_content_mismatch')
    def test_noop_mismatched_history_refused(self):
        self.assertEqual(assess(docs=bundle(commit=OLD)).reason,'inconsistent_noop_ancestry')
    def test_missing_required_document_rejected(self):
        bad={k:v for k,v in FILES.items() if k!='docs/PROJECT_SPEC.md'}
        with self.assertRaisesRegex(ValueError,'required_homehub_docs_missing'):
            assess(docs=bundle(bad))
    def test_unsafe_document_path_rejected(self):
        with self.assertRaisesRegex(ValueError,'unsafe_markdown_path'):
            assess(docs=bundle({**FILES,'docs/CON.md':b'no'}))
    def test_tampered_new_blob_rejected(self):
        b = bundle()
        bad = replace(b, contents={**FILES, 'AGENTS.md': b'tampered'})
        with self.assertRaisesRegex(ValueError,'git_blob'):
            assess(docs=bad)

if __name__=='__main__': unittest.main()
