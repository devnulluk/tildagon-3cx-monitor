"""Behavioural regression tests for call classification and trustworthy BLFs."""
import copy
import math
import unittest

from bridge.config import validate_config
from bridge.model import build_state, normalize_number


def settings(**changes):
    value = {
        "own_extension": "200", "own_name": "Mark",
        "team": [{"extension": "223", "name": "TB"},
                 {"extension": "268", "name": "PD"},
                 {"extension": "214", "name": "JH"},
                 {"extension": "277", "name": "SM"}],
        "priority_callers": ["07700900123"],
        "priority_extensions": ["223", "268", "214", "277", "247", "244", "234", "303"],
        "contacts": {"07700900123": "Partner"},
        "internal_extensions": {"223": "Tim", "268": "Paul", "214": "Jordon",
                                "277": "Sorrell", "247": "Kev", "244": "Sarah B",
                                "234": "Steve", "303": "Mark H"},
        "queues": {"800": "Support"},
        "ddis": {"01376555000": "Mark direct", "01376555001": "Priority line"},
        "priority_ddis": ["01376555001"],
        "trunk_dns": ["10000"],
    }
    value.update(changes)
    return validate_config(value)


def leg(callid=1, identifier=1, status="Ringing", **changes):
    value = {"id": identifier, "callid": callid, "status": status,
             "party_dn": "10000", "party_caller_id": "+441632960999",
             "party_caller_name": "Example caller", "party_dn_type": "Wexternalline"}
    value.update(changes)
    return value


def dn(number, participants=(), registered=True, kind="Wextension"):
    return {"dn": number, "type": kind, "devices": [{"device_id": "phone"}] if registered else [],
            "participants": list(participants)}


class ModelTests(unittest.TestCase):
    def state(self, participants=(), extra=(), config=None, **changes):
        args = {"connected": True, "age_seconds": 0.1}
        args.update(changes)
        return build_state(config or settings(), [dn("200", participants), dn("223"), *extra], **args)

    def test_external_caller_does_not_imply_called_ddi(self):
        call = self.state([leg()])["alert"]
        self.assertEqual("external", call["kind"])
        self.assertEqual("", call["ddi"])

    def test_only_known_ddi_is_classified(self):
        unknown = self.state([leg(party_did="01376555998")])["alert"]
        known = self.state([leg(party_did="+44 1376 555000")])["alert"]
        self.assertEqual("external", unknown["kind"])
        self.assertEqual("ddi", known["kind"])
        self.assertEqual("Mark direct", known["ddi_name"])

    def test_queue_routing_precedes_direct_ddi_but_preserves_it(self):
        alert = self.state([leg(referred_by_dn="800", party_did="01376555000")])["alert"]
        self.assertEqual("queue", alert["kind"])
        self.assertEqual("Support", alert["queue_name"])
        self.assertEqual("+441376555000", alert["ddi"])

    def test_queue_correlates_same_call_legs(self):
        alert = self.state([leg(callid=80)], [dn("800", [leg(callid=80)], kind="Wqueue")])["alert"]
        self.assertEqual("queue", alert["kind"])

    def test_queue_does_not_correlate_other_call(self):
        alert = self.state([leg(callid=80)], [dn("800", [leg(callid=81)], kind="Wqueue")])["alert"]
        self.assertEqual("external", alert["kind"])

    def test_missing_or_zero_callid_never_correlates_queue(self):
        for callid in (None, 0, "0"):
            with self.subTest(callid=callid):
                alert = self.state([leg(callid=callid)],
                                   [dn("800", [leg(callid=callid)], kind="Wqueue")])["alert"]
                self.assertEqual("external", alert["kind"])

    def test_missing_participant_and_call_ids_do_not_merge_distinct_calls(self):
        first = leg(callid=None, party_caller_name="Caller one")
        second = leg(callid=None, party_caller_name="Caller two")
        del first["id"]
        del second["id"]
        state = self.state([first, second])
        self.assertEqual(2, len(state["own"]["calls"]))
        self.assertEqual({"Caller one", "Caller two"},
                         {call["peer_name"] for call in state["own"]["calls"]})

    def test_trunk_correlation_recovers_known_ddi(self):
        alert = self.state([leg(callid=44)],
                           [dn("10000", [leg(callid=44, party_did="01376555000")], kind="Wexternalline")])["alert"]
        self.assertEqual("ddi", alert["kind"])
        self.assertEqual("+441376555000", alert["ddi"])

    def test_unconfigured_trunk_cannot_supply_ddi(self):
        alert = self.state([leg(callid=44)],
                           [dn("10001", [leg(callid=44, party_did="01376555000")], kind="Wexternalline")])["alert"]
        self.assertEqual("external", alert["kind"])

    def test_priority_mobile_matches_national_and_international_formats(self):
        for number in ("07700 900123", "+44 7700 900123", "00447700900123", "447700900123", "tel:+447700900123"):
            with self.subTest(number=number):
                alert = self.state([leg(party_caller_id=number)])["alert"]
                self.assertTrue(alert["priority"])
                self.assertEqual("Partner", alert["peer_name"])
                self.assertEqual("external", alert["kind"])

    def test_explicit_initials_follow_contact_across_number_formats_on_own_and_team_calls(self):
        config = settings(initials={"07700900123": "KZ", "223": "TB"})
        for number in ("07700 900123", "+44 7700 900123", "00447700900123", "447700900123"):
            with self.subTest(number=number):
                result = self.state([leg(party_caller_id=number)], config=config,
                                    extra=[dn("268", [leg(callid=2, status="Connected", party_caller_id=number)])])
                self.assertEqual(result["alert"]["peer_initials"], "KZ")
                self.assertEqual(result["own"]["calls"][0]["peer_initials"], "KZ")
                self.assertEqual(result["team"][1]["calls"][0]["peer_initials"], "KZ")
                self.assertEqual(result["team"][1]["calls"][0]["peer_name"], "Partner")

    def test_explicit_internal_initials_override_display_names_but_preserve_full_identity(self):
        config = settings(initials={"223": "TB"},
                          team=[{"extension": "223", "name": "Tim Brown"}])
        result = self.state([leg(party_dn="223", party_caller_id="223", party_dn_type="Wextension")], config=config)
        self.assertEqual(result["alert"]["peer_initials"], "TB")
        self.assertEqual(result["alert"]["peer_name"], "Tim")
        self.assertEqual(result["alert"]["peer_number"], "223")

    def test_priority_internal_keeps_underlying_call_type(self):
        for extension, name in (("223", "Tim"), ("247", "Kev"), ("303", "Mark H")):
            with self.subTest(extension=extension):
                alert = self.state([leg(party_dn=extension, party_caller_id=extension,
                                       party_dn_type="Wextension")])["alert"]
                self.assertTrue(alert["priority"])
                self.assertEqual("internal", alert["kind"])
                self.assertEqual(name, alert["peer_name"])

    def test_internal_priority_uses_number_when_dn_absent(self):
        alert = self.state([leg(party_dn="", party_caller_id="223", party_dn_type="Wextension")])["alert"]
        self.assertTrue(alert["priority"])
        self.assertEqual("Tim", alert["peer_name"])

    def test_internal_extension_and_first_name_are_separate_from_initials(self):
        config = settings(initials={"223": "TB"}, internal_extensions={"223": "Tim Brown"},
                          contacts={"223": "TB"})
        call = self.state([leg(party_dn="223", party_caller_id="223", party_dn_type="Wextension",
                               party_caller_name="TB")], config=config)["alert"]
        self.assertEqual(call["peer_extension"], "223")
        self.assertEqual(call["peer_first_name"], "Tim")
        self.assertEqual(call["peer_initials"], "TB")
        self.assertEqual(call["peer_number"], "223")

    def test_unknown_internal_extension_uses_actual_pbx_first_name(self):
        call = self.state([leg(party_dn="355", party_caller_id="355", party_dn_type="Wextension",
                               party_caller_name="Alex Example")])["alert"]
        self.assertEqual((call["peer_extension"], call["peer_first_name"]), ("355", "Alex"))

    def test_targeted_directory_firstname_fills_unknown_live_internal_callee(self):
        config = settings()
        config["directory_names"] = {"271": "DirectoryGiven"}
        call = self.state([leg(party_dn="271", party_caller_id="271", party_dn_type="Wextension",
                               party_caller_name="")], config=config)["alert"]
        self.assertEqual((call["peer_extension"], call["peer_first_name"]), ("271", "DirectoryGiven"))

    def test_explicit_internal_name_precedes_targeted_directory_name(self):
        config = settings()
        config["directory_names"] = {"223": "Different"}
        call = self.state([leg(party_dn="223", party_caller_id="223", party_dn_type="Wextension",
                               party_caller_name="TB")], config=config)["alert"]
        self.assertEqual(call["peer_first_name"], "Tim")

    def test_directory_actual_firstname_and_pbx_fullname_allow_capitalized_short_names(self):
        for directory, caller_name in (({"271": "IAN"}, ""), ({}, "IAN Example")):
            config = settings()
            config["directory_names"] = directory
            call = self.state([leg(party_dn="271", party_caller_id="271", party_dn_type="Wextension",
                                   party_caller_name=caller_name)], config=config)["alert"]
            self.assertEqual(call["peer_first_name"], "IAN")

    def test_internal_names_are_taken_from_pbx_when_config_contains_only_an_alias(self):
        config = settings(internal_extensions={"223": "TB"}, initials={"223": "TB"})
        call = self.state([leg(party_dn="223", party_caller_id="223", party_dn_type="Wextension",
                               party_caller_name="Tim Brown")], config=config)["alert"]
        self.assertEqual(call["peer_first_name"], "Tim")

    def test_number_unknown_and_initials_never_pretend_to_be_first_names(self):
        for caller_name in ("355", "Unknown", "anonymous", "", None, "JH", "T.B.", "355: Tim", "Me"):
            with self.subTest(caller_name=caller_name):
                call = self.state([leg(party_dn="355", party_caller_id="355", party_dn_type="Wextension",
                                       party_caller_name=caller_name)])["alert"]
                self.assertEqual(call["peer_extension"], "355")
                self.assertEqual(call["peer_first_name"], "")

    def test_team_card_internal_call_has_callee_extension_and_first_name(self):
        call = self.state(extra=[dn("268", [leg(status="Connected", party_dn="223", party_caller_id="223",
                                               party_dn_type="Wextension", party_caller_name="TB")])])["team"][1]["calls"][0]
        self.assertEqual((call["peer_extension"], call["peer_first_name"]), ("223", "Tim"))

    def test_external_contact_and_short_cid_never_supply_internal_display_fields(self):
        for caller_id in ("223", "+441632960999", "07700900123"):
            with self.subTest(caller_id=caller_id):
                call = self.state([leg(party_caller_id=caller_id)])["alert"]
                self.assertEqual((call["peer_extension"], call["peer_first_name"]), ("", ""))

    def test_absent_internal_dn_uses_explicit_extension_typed_caller_id(self):
        call = self.state([leg(party_dn="", party_caller_id="223", party_dn_type="Wextension")])["alert"]
        self.assertEqual((call["peer_extension"], call["peer_first_name"]), ("223", "Tim"))

    def test_external_caller_cannot_impersonate_internal_priority_by_short_cid(self):
        alert = self.state([leg(party_dn="10000", party_caller_id="223", party_dn_type="Wexternalline")])["alert"]
        self.assertFalse(alert["priority"])
        self.assertEqual("external", alert["kind"])

    def test_priority_ddi_can_apply_to_queue_call(self):
        alert = self.state([leg(party_did="01376555001", on_behalf_of_dn="800")])["alert"]
        self.assertTrue(alert["priority"])
        self.assertEqual("queue", alert["kind"])

    def test_multi_device_ringing_collapses_one_call(self):
        state = self.state([leg(identifier=1), leg(identifier=2)])
        self.assertEqual(1, len(state["own"]["calls"]))
        self.assertEqual("ringing", state["own"]["state"])
        self.assertIsNotNone(state["alert"])

    def test_answered_sibling_stops_incoming_alert(self):
        state = self.state([leg(identifier=1), leg(identifier=2, status="Connected")])
        self.assertIsNone(state["alert"])
        self.assertEqual("busy", state["own"]["state"])
        self.assertEqual(1, len(state["own"]["calls"]))

    def test_separate_waiting_call_still_alerts_while_connected(self):
        state = self.state([leg(callid=1, status="Connected"), leg(callid=2, identifier=2)])
        self.assertIsNotNone(state["alert"])
        self.assertEqual("2", state["alert"]["id"])
        self.assertEqual(2, len(state["own"]["calls"]))

    def test_priority_waiting_call_wins_alert(self):
        state = self.state([leg(callid=1), leg(callid=2, identifier=2, party_caller_id="07700900123")])
        self.assertEqual("Partner", state["alert"]["peer_name"])

    def test_api_ringback_never_alerts_as_incoming(self):
        state = self.state([leg(party_dn="MakeCall", party_caller_id="MakeCall")])
        self.assertIsNone(state["alert"])
        self.assertEqual("outbound", state["own"]["calls"][0]["direction"])

    def test_transport_direction_memory_survives_connected_snapshot(self):
        call = self.state([leg(status="Connected", _direction="outbound")])["own"]["calls"][0]
        self.assertEqual("outbound", call["direction"])

    def test_connected_first_seen_without_direction_is_unknown(self):
        call = self.state([leg(status="Connected")])["own"]["calls"][0]
        self.assertEqual("unknown", call["direction"])

    def test_stale_disconnected_and_nonfinite_snapshots_hide_all_call_data(self):
        for connected, age in ((False, 0.1), (True, 5.01), (True, math.inf), (True, math.nan), (True, -math.inf)):
            with self.subTest(connected=connected, age=age):
                state = self.state([leg()], extra=[dn("268", [leg(status="Connected")])],
                                   connected=connected, age_seconds=age)
                self.assertFalse(state["connected"])
                self.assertIsNone(state["alert"])
                for member in [state["own"], *state["team"]]:
                    self.assertEqual("unknown", member["state"])
                    self.assertEqual([], member["calls"])

    def test_idle_requires_known_registered_dn(self):
        state = self.state(extra=[dn("268", registered=False)])
        self.assertEqual("idle", state["team"][0]["state"])
        self.assertEqual("unknown", state["team"][1]["state"])
        self.assertEqual("unknown", state["team"][2]["state"])

    def test_undefined_participant_is_not_idle(self):
        state = self.state([leg(status="Undefined")])
        self.assertEqual("unknown", state["own"]["state"])
        self.assertIsNone(state["alert"])

    def test_dialing_hold_and_held_are_busy(self):
        for status in ("Dialing", "Connected", "Hold", "Held"):
            with self.subTest(status=status):
                state = self.state([leg(status=status)])
                self.assertEqual("busy", state["own"]["state"])
                self.assertIsNone(state["alert"])

    def test_private_unselected_dns_are_not_exposed(self):
        state = self.state(extra=[dn("999", [leg(party_caller_name="Private colleague")])])
        self.assertNotIn("Private colleague", str(state))
        self.assertNotIn("999", [member["extension"] for member in state["team"]])

    def test_snapshot_is_not_mutated(self):
        config = settings()
        snapshot = [dn("200", [leg()]), dn("223")]
        before = copy.deepcopy(snapshot)
        build_state(config, snapshot, True, 0.1)
        self.assertEqual(before, snapshot)

    def test_display_fields_remove_controls_and_bound_length(self):
        state = self.state([leg(party_caller_name="Bad\nName\x00" + "x" * 500)])
        name = state["alert"]["peer_name"]
        self.assertNotIn("\n", name)
        self.assertNotIn("\x00", name)
        self.assertLessEqual(len(name), 100)


class ConfigTests(unittest.TestCase):
    def test_numeric_extension_values_normalize_to_strings(self):
        config = validate_config({"own_extension": 200, "team": [{"extension": 223, "name": "TB"}]})
        self.assertEqual("200", config["own_extension"])
        self.assertEqual("223", config["team"][0]["extension"])

    def test_duplicate_team_member_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_config({"own_extension": "200", "team": [{"extension": "223"}, {"extension": 223}]})

    def test_refresh_must_fit_within_stale_window(self):
        with self.assertRaises(ValueError):
            settings(refresh_interval_seconds=5, stale_after_seconds=5)

    def test_bad_priority_list_is_rejected(self):
        for value in ("223", [223], None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                settings(priority_extensions=value)

    def test_nonfinite_refresh_and_stale_intervals_are_rejected(self):
        for field in ("refresh_interval_seconds", "stale_after_seconds"):
            for value in (math.nan, math.inf, -math.inf):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    settings(**{field: value})

    def test_non_number_does_not_match_priority(self):
        for value in (None, "anonymous", "withheld", "07700900123@spoof"):
            self.assertEqual("", normalize_number(value))

    def test_speed_dial_digit_bounds_match_action_destinations(self):
        for number in ("12", "+12", "1234567890123456", "+1234567890123456"):
            with self.subTest(number=number):
                config = settings(speed_dials=[{"id": "valid_target", "number": number}])
                self.assertEqual(config["speed_dials"][0]["number"], number)
        for number in ("1", "+1", "12345678901234567", "+12345678901234567", "", "+"):
            with self.subTest(number=number), self.assertRaises(ValueError):
                settings(speed_dials=[{"id": "target", "number": number}])

    def test_speed_dial_numbers_reject_unicode_dial_codes_and_own_extension(self):
        for number in ("１２３", "١٢٣", "*32", "#32", "200", "++223", "2+23", "22 3", 223, None):
            with self.subTest(number=number), self.assertRaises(ValueError):
                settings(speed_dials=[{"id": "target", "number": number}])

    def test_speed_dial_identifiers_are_unique_bounded_ascii_and_targets_are_explicit(self):
        for identifier in ("", "x" * 25, "with space", "é", "dot.id", None, 123):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                settings(speed_dials=[{"id": identifier, "number": "223"}])
        with self.assertRaises(ValueError):
            settings(speed_dials=[{"id": "tb", "number": "223"}, {"id": "tb", "number": "268"}])
        with self.assertRaises(ValueError):
            settings(speed_dials=[{"id": "tb", "number": "223", "source": "268"}])
        targets = [{"id": "target_" + str(index), "number": str(300 + index)} for index in range(24)]
        self.assertEqual(len(settings(speed_dials=targets)["speed_dials"]), 24)
        with self.assertRaises(ValueError):
            settings(speed_dials=targets + [{"id": "extra", "number": "400"}])


if __name__ == "__main__":
    unittest.main()
