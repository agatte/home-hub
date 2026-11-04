"""Synthetic-only fixtures. Assertions never render incoming objects."""
import ast
import json
import unittest
from pathlib import Path
from backend.services import hue_ack_summary as subject

SECRET = "SYNTHETIC_SECRET_SENTINEL"
IDENT = "00000000-0000-4000-8000-000000000001"
PRIVATE = (SECRET, IDENT, "192.0.2.123", "SYNTHETIC_USER_PATH")


class Exotic:
    def __repr__(self):
        raise AssertionError("repr invoked")

    def __eq__(self, other):
        raise AssertionError("comparison invoked")


class DictSubclass(dict):
    def items(self):
        raise AssertionError("subclass invoked")


def v1(reply=None, command=None, ident=SECRET):
    if reply is None:
        reply = [[{"success": {"/lights/" + SECRET + "/state/on": False}}]]
    return subject.summarize_v1(reply, {"on": False} if command is None else command, ident)


def v2(status=200, data=None, errors=None):
    return subject.summarize_v2(status, {
        "errors": [] if errors is None else errors,
        "data": [{"rid": IDENT, "rtype": "light"}] if data is None else data,
    }, IDENT, "light")


class Tests(unittest.TestCase):
    def check(self, result, accepted=False, shape=None):
        rendered = json.dumps(result, allow_nan=False)
        self.assertTrue(all(s not in rendered for s in PRIVATE), "privacy failure")
        self.assertEqual(set(result), set(subject._base("V1")), "schema failure")
        self.assertEqual(result["remote_outcome"], "UNKNOWN")
        self.assertEqual(result["acceptance"],
                         "ACCEPTED_NOT_PHYSICAL" if accepted else "INCOMPLETE_OR_UNKNOWN")
        self.assertTrue(set(result["requested_properties"]) <= set(subject.PROPERTIES))
        self.assertTrue(set(result["acknowledged_properties"]) <= set(subject.PROPERTIES))
        if shape:
            self.assertEqual(result["shape"], shape)

    def test_v1_complete(self):
        self.check(v1(), True, "COMPLETE")

    def test_v1_all_allowed_properties(self):
        command = {"on": False, "bri": 0, "hue": 1, "sat": 254, "transitiontime": 2}
        reply = [[{"success": {"/lights/" + SECRET + "/state/" + k: v}}
                  for k, v in command.items()]]
        self.check(v1(reply, command), True)

    def test_v1_ct(self):
        self.check(v1([[{"success": {"/lights/" + SECRET + "/state/ct": 153}}]],
                      {"ct": 153}), True)

    def test_v1_ct_with_forced_sat_zero(self):
        # HomeHub HueService emits sat=0 then ct when setting color temperature.
        command = {"sat": 0, "ct": 400}
        reply = [[
            {"success": {"/lights/" + SECRET + "/state/sat": 0}},
            {"success": {"/lights/" + SECRET + "/state/ct": 400}},
        ]]
        self.check(v1(reply, command), True)

    def test_v1_ct_with_nonzero_sat_rejected(self):
        command = {"sat": 50, "ct": 400}
        reply = [[
            {"success": {"/lights/" + SECRET + "/state/sat": 50}},
            {"success": {"/lights/" + SECRET + "/state/ct": 400}},
        ]]
        self.check(v1(reply, command), False)

    def test_v1_has_no_transport_http_evidence(self):
        self.assertEqual(v1()["http_result"], "UNAVAILABLE")

    def test_v1_missing_property(self):
        self.check(v1(command={"on": False, "bri": 10}), shape="PARTIAL")

    def test_v2_malformed_envelopes(self):
        for response in (None, [], {}, {"errors": [], "data": [], SECRET: SECRET},
                         {"errors": {}, "data": []}, {"errors": [], "data": {}}):
            self.check(subject.summarize_v2(200, response, IDENT, "light"),
                       shape="MALFORMED")

    def test_privacy_for_all_argument_positions(self):
        for value in (Exotic(), SECRET, "192.0.2.123", "SYNTHETIC_USER_PATH"):
            self.check(subject.summarize_v1(value, value, value))
            self.check(subject.summarize_v2(value, value, value, value))

    def test_v2_complete(self):
        self.check(v2(), True)

    def test_v2_207(self):
        self.check(v2(207), True)

    def test_v2_scene(self):
        self.check(subject.summarize_v2(200, {"errors": [], "data": [
            {"rid": IDENT, "rtype": "scene"}]}, IDENT, "scene"), True)

    def test_decoder_duplicates(self):
        for raw in ('{"data":[],"data":[]}', '{"x":{"a":1,"a":2}}'):
            self.assertTrue(subject.decode_json(raw) is None, "duplicate accepted")

    def test_decoder_invalid(self):
        for raw in (Exotic(), "[", "x" * 16385, "[NaN]", "[Infinity]", "[" * 2000):
            self.assertTrue(subject.decode_json(raw) is None, "invalid accepted")

    def test_decoder_valid(self):
        decoded = subject.decode_json('{"errors":[],"data":[]}')
        self.check(subject.summarize_v2(200, decoded, IDENT, "light"))

    def test_cycles(self):
        cycle = []
        cycle.append(cycle)
        self.check(v1(cycle), shape="MALFORMED")

    def test_no_io_imports(self):
        tree = ast.parse(Path(subject.__file__).read_text(encoding="utf-8"))
        imports = [n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)]
        self.assertEqual(imports, ["json"])
        self.assertFalse(any(isinstance(n, ast.ImportFrom) for n in ast.walk(tree)))


V1_BAD = [
    [], [{"success": {"/lights/x/state/on": False}}],
    [[{"success": {"/lights/wrong/state/on": False}}]],
    [[{"success": {"/lights/" + SECRET + "/state/on": True}}]],
    [[{"success": {"/lights/" + SECRET + "/state/on": 0}}]],
    [[{"success": {"/lights/" + SECRET + "/state/" + SECRET: False}}]],
    [[{"error": {"description": SECRET, "address": "192.0.2.123"}}]],
    [[{"success": {"/lights/" + SECRET + "/state/on": False}}] * 2],
    [[{"success": {"/lights/" + SECRET + "/state/on": Exotic()}}]],
    [[{"success": {"/lights/" + SECRET + "/state/on": False}},
      {"error": {"description": SECRET}}]],
    [Exotic()], DictSubclass(), [0] * 33, [[{"success": {SECRET: "x" * 513}}]],
]


def add_case(name, function):
    def test(self):
        self.check(function())
    setattr(Tests, name, test)


for index, reply in enumerate(V1_BAD):
    add_case("test_v1_adversarial_%02d" % index, lambda reply=reply: v1(reply))
for index, command in enumerate(({}, {SECRET: 1}, {"bri": True}, {"bri": 255},
                                 {"ct": 152}, {"ct": 153, "hue": 1},
                                 {"on": Exotic()}, {"bri": 1.0})):
    add_case("test_command_invalid_%02d" % index, lambda command=command: v1(command=command))
for index, status in enumerate((True, "200", 0, 600, 500, Exotic())):
    add_case("test_status_invalid_%02d" % index, lambda status=status: v2(status))
for index, data in enumerate(([], [{"rid": SECRET, "rtype": "light"}],
                              [{"rid": IDENT, "rtype": "scene"}],
                              [{"rid": IDENT, "rtype": "light"}] * 2,
                              [{"rid": Exotic(), "rtype": "light"}],
                              [{"rid": IDENT, "rtype": "light", SECRET: SECRET}])):
    add_case("test_v2_data_%02d" % index, lambda data=data: v2(data=data))
for index, errors in enumerate(([{"description": SECRET}], [SECRET],
                                [{"nested": {"SYNTHETIC_USER_PATH": IDENT}}], [Exotic()])):
    add_case("test_v2_errors_%02d" % index, lambda errors=errors: v2(errors=errors))


if __name__ == "__main__":
    unittest.main()
