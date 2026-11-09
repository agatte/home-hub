"""Invented fixtures only: offline parsing grants no transfer authority."""
import dataclasses
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.services import apple_music_offline_raw_ingress as module
from backend.services.apple_music_ephemeral_review_receiver import ERROR, ReviewRefused


def fixture(label="Fictional Moon Teapot Ensemble"):
    return dict(artist_label=label, source="apple_daily_tracks",
                evidence="unverified_artist_label_day_exposure",
                identity_status="unverified", preference_eligible="false",
                session_proven="false", cross_source_independent="false",
                actuation_eligible="false")


def wire(body=None):
    return json.dumps(fixture() if body is None else body,
                      ensure_ascii=True, separators=(",", ":")).encode("ascii")


class RawIngressTests(unittest.TestCase):
    def refused(self, raw):
        with self.assertRaises(ReviewRefused) as caught:
            module.parse_offline_artist_raw_body(raw)
        error = caught.exception
        self.assertEqual(str(error), ERROR)
        self.assertEqual(repr(error), "ReviewRefused(" + repr(ERROR) + ")")
        self.assertIsNone(error.__context__)
        self.assertIsNone(error.__cause__)

    def test_valid_exact_bytes_and_immutable_redacted_result(self):
        review = module.parse_offline_artist_raw_body(wire())
        self.assertEqual(review.artist_label, fixture()["artist_label"])
        self.assertEqual(review.source, "apple_daily_tracks")
        self.assertEqual(review.evidence, fixture()["evidence"])
        self.assertEqual(review.identity_status, "unverified")
        self.assertEqual(repr(review), "EphemeralReview(<redacted>)")
        self.assertEqual(str(review), "EphemeralReview(<redacted>)")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            review.artist_label = "Fictional Other Teapot"

    def test_only_exact_bytes(self):
        class BytesSubclass(bytes):
            pass
        for bad in (None, "fictional", bytearray(wire()), memoryview(wire()),
                    BytesSubclass(wire()), {}, 1, True):
            self.refused(bad)

    def test_empty_and_whitespace(self):
        for bad in (b"", b" ", b"\t\r\n"):
            self.refused(bad)

    def test_raw_length_boundary_includes_whitespace(self):
        raw = wire()
        padded = b" " * (2048 - len(raw)) + raw
        self.assertEqual(len(padded), 2048)
        module.parse_offline_artist_raw_body(padded)
        self.refused(padded + b" ")
        self.refused(b" " * 2049)

    def test_raw_limit_checked_before_decoder(self):
        with patch.object(module.json, "loads", side_effect=AssertionError("decoded")):
            self.refused(wire() + b" " * 2048)

    def test_valid_unicode_raw_and_escaped(self):
        label = "Fictional Caf\u00e9 \u6708 \U0001f680"
        for raw in (wire(fixture(label)),
                    json.dumps(fixture(label), ensure_ascii=False).encode("utf-8")):
            self.assertEqual(module.parse_offline_artist_raw_body(raw).artist_label, label)

    def test_invalid_utf8_bom_and_surrogates(self):
        for raw in (b"\xef\xbb\xbf" + wire(), b" " + b"\xef\xbb\xbf" + wire(),
                    wire().replace(b"Fictional", b"\xff"),
                    wire().replace(b"Fictional", b"\xed\xa0\x80"),
                    wire(fixture("Fictional \ud800")), wire(fixture("Fictional \udfff"))):
            self.refused(raw)

    def test_control_unicode_categories_and_invalid_labels(self):
        for label in ("", " Fictional", "Fictional ", "Fictional\nTeapot",
                      "Fictional\x00", "Fictional\x7f", "Fictional\u0085",
                      "Fictional\u200d", "Fictional\ue000", "Fictional\ufeff",
                      "Fictional\uffff"):
            self.refused(wire(fixture(label)))
        self.refused(wire().replace(b"Fictional", b"Fictional\x01"))
        self.refused(wire() + b"\x00")

    def test_label_byte_and_character_limits(self):
        module.parse_offline_artist_raw_body(wire(fixture("Fictional" + "x" * 247)))
        self.refused(wire(fixture("Fictional" + "x" * 248)))
        # 11 ASCII + 167 three-byte scalars = exactly 512 UTF-8 bytes.
        module.parse_offline_artist_raw_body(wire(fixture("Fictionalxx" + "\u6708" * 167)))
        self.refused(wire(fixture("Fictionalxx" + "\u6708" * 168)))

    def test_top_level_duplicate_and_escaped_equivalent_keys(self):
        for key in (b'"artist_label"', b'"artist_\\u006cabel"'):
            self.refused(wire()[:-1] + b"," + key + b':"Fictional Other"}')

    def test_nested_duplicates_in_objects_and_arrays(self):
        for value in (b'{"fiction":1,"fiction":2}',
                      b'[{"fiction":"a","fict\\u0069on":"b"}]'):
            # String values keep rejection attributable to the duplicate hook.
            value = value.replace(b":1", b':"a"').replace(b":2", b':"b"')
            with patch.object(module, "_validate_body", side_effect=AssertionError("validated")):
                self.refused(wire()[:-1] + b',"fiction_nested":' + value + b"}")

    def test_numbers_nonfinite_and_extreme_tokens(self):
        for token in (b"NaN", b"Infinity", b"-Infinity", b"0", b"-1", b"1.5",
                      b"1e999999999", b"9" * 1500, b"1e-999999999"):
            self.refused(token)
            self.refused(wire().replace(b'"false"', token, 1))

    def test_unsupported_shapes_and_value_types(self):
        for body in ([], [fixture()], None, True, "Fictional Teapot", {},
                     dict(fixture(), artist_label={"fiction": "nested"}),
                     dict(fixture(), artist_label=["Fictional Teapot"])):
            self.refused(wire(body) if body is not None else b"null")
        for value in (False, True, None, [], {}):
            self.refused(wire(dict(fixture(), session_proven=value)))

    def test_exact_fields_and_fixed_semantics(self):
        for key in fixture():
            body = fixture()
            del body[key]
            self.refused(wire(body))
            if key != "artist_label":
                self.refused(wire(dict(fixture(), **{key: "fiction-changed"})))
        for key in ("Origin", "Host", "X-Forwarded-Host", "transport_verified",
                    "version", "fiction_unknown", "fiction\u0000"):
            self.refused(wire(dict(fixture(), **{key: "false"})))

    def test_malformed_trailing_and_deep_nesting(self):
        for raw in (wire()[:-1], wire() + b"{}", wire() + b"fiction",
                    b'{"fiction":}', b'{"fiction":"\\x00"}',
                    b"[" * 1000 + b"0" + b"]" * 1000,
                    b'{"fiction":' * 100 + b"null" + b"}" * 100):
            self.refused(raw)

    def test_decoder_exceptions_are_fixed_without_context(self):
        for failure in (ValueError("fiction-secret"), RecursionError("fiction-secret"),
                        OverflowError("fiction-secret"), TypeError("fiction-secret")):
            with patch.object(module.json, "loads", side_effect=failure):
                self.refused(wire())

    def test_repeat_calls_have_no_state_or_io(self):
        raw = wire()
        with patch("builtins.open", side_effect=AssertionError("I/O")), \
                patch("socket.socket", side_effect=AssertionError("network")), \
                patch("sqlite3.connect", side_effect=AssertionError("DB")):
            first = module.parse_offline_artist_raw_body(raw)
            self.refused(b"fiction-invalid")
            second = module.parse_offline_artist_raw_body(raw)
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertEqual(raw, wire())

    def test_fresh_import_no_application_io_or_randomness(self):
        guard = '''
import builtins, importlib, os, pathlib, secrets, socket, sqlite3, logging
def blocked(*args, **kwargs):
    raise AssertionError("Forbidden application side effect")
builtins.open = os.open = pathlib.Path.open = blocked
socket.socket = sqlite3.connect = secrets.token_urlsafe = os.urandom = blocked
logging.Logger._log = blocked
target = importlib.import_module("backend.services.apple_music_offline_raw_ingress")
assert callable(target.parse_offline_artist_raw_body)
'''
        result = subprocess.run([sys.executable, "-B", "-c", guard],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
