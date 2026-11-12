"""Partner decoration uses exact configured numbers; all fixtures are synthetic."""
import copy
import importlib.util
from pathlib import Path
import unittest


PATH = Path(__file__).resolve().parents[1] / "badge/love.py"
spec = importlib.util.spec_from_file_location("love_under_test", PATH)
love = importlib.util.module_from_spec(spec)
spec.loader.exec_module(love)

NUMBER = "+447700900123"  # Reserved UK drama number, never a live destination.
CONFIG = {"partner_numbers": [NUMBER], "partner_name": "Partner"}


def call(number=NUMBER, state="ringing", **values):
    return dict(peer_number=number, state=state, **values)


class NumberMatchingTests(unittest.TestCase):
    def test_national_international_and_formatted_numbers_match_the_same_full_number(self):
        variants = (NUMBER, "07700900123", "00447700900123", "+44 7700 900123",
                    "(07700) 900-123", "tel:+44 7700 900123", "TEL:07700.900.123")
        for value in variants:
            with self.subTest(value=value):
                self.assertEqual(love.normalise(value), NUMBER)
                self.assertTrue(love.partner_call(call(value), CONFIG))

    def test_configured_national_format_also_matches_an_international_caller(self):
        self.assertTrue(love.partner_call(call(), {"partner_numbers": ["07700 900123"]}))
        self.assertTrue(love.partner_call(call(), {"partner_numbers": ("00447700900123",)}))

    def test_substrings_prefixes_and_similar_numbers_never_match(self):
        for value in ("+447700900124", "+4477009001234", "+44770090012", "7700900123",
                      "+17700900123", "447700900123"):
            with self.subTest(value=value):
                self.assertFalse(love.partner_call(call(value), CONFIG))

    def test_sip_addresses_extensions_or_embedded_number_text_are_not_phone_matches(self):
        for value in ("sip:" + NUMBER, NUMBER + "@example.invalid", "Partner " + NUMBER,
                      NUMBER + ";ext=123", "123", "07700/900123", "07700\n900123",
                      "++447700900123", "+44+7700900123", "０７７００９００１２３"):
            with self.subTest(value=value):
                self.assertIsNone(love.normalise(value))
                self.assertFalse(love.partner_call(call(value), CONFIG))

    def test_wrong_types_empty_and_overlong_numbers_are_unknown(self):
        for value in (None, False, 7700900123, b"07700900123", [], {}, "", " ", "0" * 81):
            with self.subTest(value=value):
                self.assertIsNone(love.normalise(value))
                self.assertFalse(love.partner_call(call(value), CONFIG))

    def test_name_initials_and_priority_cannot_spoof_a_live_partner_match(self):
        for values in ({"peer_name": "Partner"}, {"peer_initials": "KZ"},
                       {"priority": True}, {"peer_name": NUMBER, "peer_initials": "KZ"}):
            with self.subTest(values=values):
                self.assertFalse(love.partner_call(call("+447700900124", **values), CONFIG))

    def test_initials_shortcut_is_limited_to_active_synthetic_demo_calls(self):
        synthetic = call("DEMO", peer_initials="KZ")
        self.assertTrue(love.partner_call(synthetic, {}, demo=True))
        self.assertFalse(love.partner_call(synthetic, {}, demo=False))
        self.assertFalse(love.partner_call(call("DEMO", "ended", peer_initials="KZ"), {}, demo=True))

    def test_partner_decoration_stops_for_ended_and_unknown_calls(self):
        for state in ("ended", "completed", "disconnected", "failed", "unknown", "", None):
            with self.subTest(state=state):
                self.assertFalse(love.partner_call(call(state=state), CONFIG))
        for state in ("ringing", "dialing", "connected", "busy", "hold", "held", "CONNECTED"):
            with self.subTest(state=state):
                self.assertTrue(love.partner_call(call(state=state), CONFIG))

    def test_missing_or_malformed_configuration_cannot_enable_a_match(self):
        for config in (None, [], "Partner", {}, {"partner_numbers": NUMBER},
                       {"partner_numbers": {NUMBER: "Partner"}}, {"partner_numbers": [None, {}]}):
            with self.subTest(config=config):
                self.assertFalse(love.partner_call(call(), config))


class OwnCallGuardsTests(unittest.TestCase):
    def test_only_live_own_calls_enable_partner_heartbeat(self):
        payload = {"own": {"calls": [call()]}, "team": []}
        self.assertTrue(love.partner_active(payload, True, CONFIG))
        for live in (False, None, 0):
            with self.subTest(live=live):
                self.assertFalse(love.partner_active(payload, live, CONFIG))
        self.assertFalse(love.partner_active({"own": {"calls": []},
                                            "team": [{"calls": [call()]}]}, True, CONFIG))

    def test_missing_or_malformed_payload_and_own_member_fail_closed(self):
        for payload in (None, [], "unexpected", {}, {"own": None}, {"own": 1},
                        {"own": "unexpected"}, {"own": []}):
            with self.subTest(payload=payload):
                self.assertFalse(love.partner_active(payload, True, CONFIG))

    def test_missing_or_malformed_calls_collection_never_crashes_or_matches(self):
        for calls in (None, 1, True, "unexpected", {"peer_number": NUMBER},
                      {"0": call()}):
            with self.subTest(calls=calls):
                self.assertFalse(love.partner_active({"own": {"calls": calls}}, True, CONFIG))
        self.assertFalse(love.partner_active({"own": {}}, True, CONFIG))

    def test_malformed_individual_calls_are_ignored_without_losing_a_valid_own_call(self):
        calls = [None, "unexpected", 1, [], {}, call("+447700900124"), call()]
        self.assertTrue(love.partner_active({"own": {"calls": calls}}, True, CONFIG))
        self.assertTrue(love.partner_active({"own": {"calls": tuple(calls)}}, True, CONFIG))
        self.assertFalse(love.partner_active({"own": {"calls": calls[:-1]}}, True, CONFIG))

    def test_matching_does_not_modify_snapshot_or_private_configuration(self):
        payload = {"own": {"calls": [call("tel:07700 900123")]}, "team": []}
        config = copy.deepcopy(CONFIG)
        before_payload, before_config = copy.deepcopy(payload), copy.deepcopy(config)
        self.assertTrue(love.partner_active(payload, True, config))
        self.assertEqual(payload, before_payload)
        self.assertEqual(config, before_config)


if __name__ == "__main__":
    unittest.main()
