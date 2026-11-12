"""Fake-only targeted phonebook checks; no real number is sent to any service."""

import asyncio
from pathlib import Path
import sys
import unittest
import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge"))
from bridge import presence
from bridge.contacts import PhonebookResolver
from test_presence import ACK, Response, Session, auth_responses, field, message, myinfo


NUMBER = "+441234567890"  # Synthetic fixture, never submitted externally.


def contact(number=NUMBER, first="Example", last="Caller", company="Example Ltd", extras=b""):
    value = field(2, first.encode()) + field(3, last.encode()) + field(7, company.encode())
    if number is not None:
        value += field(4, number.encode())
    return message(240, field(1, value + extras))


def directory_contact(extension="271", first="DirectoryGiven", last="Example", contact_type=0, dn_type=1):
    return message(240, field(1, field(2, first.encode()) + field(3, last.encode())
                             + field(4, b"+441234567899") + field(5, extension.encode())
                             + field(6, contact_type) + field(24, dn_type)
                             + field(13, b"private-directory-email@example.invalid")))


class ContactWireTests(unittest.TestCase):
    def test_internal_exact_lookup_only_searches_local_extension_mask(self):
        request = presence.encode_extension_lookup("271")
        self.assertEqual(list(presence._fields(presence._message(request, 193))),
                         [(1, 2, b"271"), (2, 0, 1), (3, 0, 0), (4, 0, 0), (5, 0, 0), (6, 0, 0)])
        for invalid in ("", "+271", "27 1", "271\n", "٢٧١", "1" * 7, 271):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                presence.encode_extension_lookup(invalid)

    def test_directory_matches_extensionnumber_not_mobile_and_keeps_actual_firstname(self):
        result = presence.decode_extension_lookup(directory_contact(), "271")
        self.assertEqual(result, {"number": "271", "name": "DirectoryGiven Example", "first_name": "DirectoryGiven"})
        self.assertNotIn("private", repr(result))
        self.assertNotIn("+44", repr(result))

    def test_directory_does_not_accept_other_extensions_phonebooks_or_system_dns(self):
        for raw in (directory_contact(extension="272"), directory_contact(contact_type=1),
                    directory_contact(contact_type=3), directory_contact(dn_type=2),
                    directory_contact(first=""), directory_contact(first="271"), contact(number="271")):
            with self.subTest(raw=raw):
                self.assertIsNone(presence.decode_extension_lookup(raw, "271"))

    def test_exact_lookup_contains_only_target_number_and_visible_book_flags(self):
        request = presence.encode_contact_lookup(NUMBER)
        fields = list(presence._fields(presence._message(request, 193)))
        self.assertEqual(fields, [(1, 2, NUMBER.encode()), (2, 0, 0),
                                  (3, 0, 1), (4, 0, 1), (5, 0, 0), (6, 0, 1)])
        for invalid in ("", "200", "anonymous", "++441234567890", "+44\r\n1234567890", "1" * 16, "+٤٤١٢٣٤٥٦٧٨٩٠"):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                presence.encode_contact_lookup(invalid)

    def test_whitelist_normalizes_exact_number_and_drops_other_contact_data(self):
        extras = field(13, b"private@example.invalid") + field(22, b"private-crm-payload") + field(25, b"https://private.invalid")
        result = presence.decode_contact_lookup(contact(number="01234 567890", extras=extras), NUMBER)
        self.assertEqual(result, {"number": NUMBER, "name": "Example Caller"})
        self.assertNotIn("private", repr(result))
        self.assertEqual(presence.decode_contact_lookup(contact(first="", last=""), NUMBER)["name"], "Example Ltd")

    def test_missing_mismatched_suffix_only_or_nameless_contact_is_not_a_match(self):
        for response in (contact(number=None), contact(number="+449934567890"),
                         contact(first="", last="", company=""), message(240, b"")):
            with self.subTest(response=response):
                self.assertIsNone(presence.decode_contact_lookup(response, NUMBER))

    def test_exact_business_home_mobile2_and_other_phone_fields_match(self):
        for phone_field in (4, 8, 9, 11, 12, 14):
            with self.subTest(phone_field=phone_field):
                extra = b"" if phone_field == 4 else field(phone_field, b"01234 567890")
                response = contact(number=NUMBER if phone_field == 4 else "+441234567899", extras=extra)
                self.assertEqual(presence.decode_contact_lookup(response, NUMBER),
                                 {"number": NUMBER, "name": "Example Caller"})
                self.assertNotIn("+441234567899", repr(presence.decode_contact_lookup(response, NUMBER)))
        self.assertEqual(presence.decode_contact_lookup(contact(number=None, extras=field(11, NUMBER.encode())), NUMBER),
                         {"number": NUMBER, "name": "Example Caller"})

    def test_email_title_company_crm_and_links_can_never_supply_a_phone_match(self):
        for not_phone in (7, 10, 13, 18, 19, 22, 25):
            with self.subTest(field=not_phone):
                # Company7 is already included by the fixture, so replace it.
                response = (message(240, field(1, field(2, b"Example") + field(7, NUMBER.encode())))
                            if not_phone == 7 else contact(number=None, extras=field(not_phone, NUMBER.encode())))
                self.assertIsNone(presence.decode_contact_lookup(response, NUMBER))

    def test_other_phone_field_still_requires_exact_normalized_number(self):
        for phone_field in (8, 9, 11, 12, 14):
            with self.subTest(phone_field=phone_field):
                response = contact(number=None, extras=field(phone_field, b"+449934567890"))
                self.assertIsNone(presence.decode_contact_lookup(response, NUMBER))

    def test_duplicate_and_malformed_names_are_rejected(self):
        for response in (contact(extras=field(2, b"second")), contact(first="bad\nname"),
                         message(240, field(1, b"\xff")), message(240, field(1, b"") + field(1, b""))):
            with self.subTest(response=response), self.assertRaises(presence.PresenceError):
                presence.decode_contact_lookup(response, NUMBER)


class ContactProviderTests(unittest.IsolatedAsyncioTestCase):
    def provider(self, responses, session_type=Session):
        session = session_type(responses)
        provider = presence.MyPhonePresenceProvider("https://pbx.invalid", refresh_token="own-refresh", session=session)
        self.addAsyncCleanup(provider.close)
        return provider, session

    async def test_lookup_verifies_own_identity_before_one_read_only_request(self):
        provider, session = self.provider(auth_responses() + [Response(myinfo()), Response(contact())])
        result = await provider.lookup_contact("01234 567890")
        self.assertEqual(result, {"number": NUMBER, "name": "Example Caller"})
        self.assertEqual(session.calls[-2][1]["data"], presence.GET_MY_INFO)
        self.assertEqual(session.calls[-1][1]["data"], presence.encode_contact_lookup(NUMBER))
        self.assertEqual(session.calls[-1][1]["headers"]["MyPhoneSession"], "own-session")
        self.assertEqual(len(session.calls), 4)

    async def test_internal_directory_lookup_verifies_own_identity_and_posts_one_exact_read(self):
        provider, session = self.provider(auth_responses() + [Response(myinfo()), Response(directory_contact())])
        self.assertEqual((await provider.lookup_extension("271"))["first_name"], "DirectoryGiven")
        self.assertEqual(session.calls[-2][1]["data"], presence.GET_MY_INFO)
        self.assertEqual(session.calls[-1][1]["data"], presence.encode_extension_lookup("271"))
        self.assertEqual(len(session.calls), 4)

    async def test_existing_verified_session_does_not_requery_identity_for_each_number(self):
        provider, session = self.provider(auth_responses() + [Response(myinfo()), Response(contact()), Response(message(240, b""))])
        await provider.get_presence()
        self.assertIsNotNone(await provider.lookup_contact(NUMBER))
        self.assertIsNone(await provider.lookup_contact("+441234567891"))
        self.assertEqual(sum(call[1].get("data") == presence.GET_MY_INFO for call in session.calls), 1)

    async def test_wrong_own_identity_prevents_phonebook_request(self):
        provider, session = self.provider(auth_responses() + [Response(myinfo(number="201"))])
        with self.assertRaises(presence.PresenceAuthError):
            await provider.lookup_contact(NUMBER)
        self.assertEqual(len(session.calls), 3)

    async def test_identity_only_read_allows_contacts_when_presence_profile_is_unfamiliar(self):
        provider, session = self.provider(auth_responses() + [Response(myinfo(current=999)), Response(contact())])
        self.assertIsNotNone(await provider.lookup_contact(NUMBER))

    async def test_acknowledged_async_contact_uses_its_own_ws_queue(self):
        class AsyncContacts(Session):
            def post(self, url, **kwargs):
                response = super().post(url, **kwargs)
                if kwargs.get("data") == presence.encode_contact_lookup(NUMBER):
                    self.sockets[-1].put(aiohttp.WSMsgType.BINARY, myinfo(current=3))
                    self.sockets[-1].put(aiohttp.WSMsgType.BINARY, contact())
                return response
        provider, session = self.provider(auth_responses() + [Response(myinfo()), Response(ACK)], AsyncContacts)
        self.assertEqual((await provider.lookup_contact(NUMBER))["name"], "Example Caller")
        self.assertFalse(provider._ws_frames.empty())
        self.assertTrue(provider._contact_frames.empty())

    async def test_timeout_is_sanitized_and_releases_presence_lock(self):
        provider, session = self.provider(auth_responses() + [Response(myinfo()), Response(ACK), Response(myinfo())])
        with self.assertRaises(presence.PresenceError) as error:
            await provider.lookup_contact(NUMBER, timeout=0.05)
        self.assertEqual(str(error.exception), "Own-user phonebook lookup is unavailable")
        self.assertFalse(provider._lock.locked())
        self.assertEqual((await provider.get_presence())["state"], "available")

    async def test_lookup_waiting_for_controls_has_bounded_lock_wait_and_no_request(self):
        provider, session = self.provider([])
        await provider._lock.acquire()
        try:
            with self.assertRaises(presence.PresenceError):
                await provider.lookup_contact(NUMBER, timeout=0.05)
        finally:
            provider._lock.release()
        self.assertEqual(session.calls, [])

    async def test_http_errors_cannot_expose_session_or_caller_data(self):
        provider, session = self.provider(auth_responses() + [Response(myinfo()),
            aiohttp.ClientError("https://pbx.invalid?pass=private-secret&number=" + NUMBER)])
        with self.assertRaises(presence.PresenceError) as error:
            await provider.lookup_contact(NUMBER)
        self.assertEqual(str(error.exception), "Own-user phonebook lookup is unavailable")


class FakePhonebook:
    def __init__(self):
        self.calls = []
        self.answer = "Example Caller"
        self.gate = None
    async def lookup_contact(self, number, **kwargs):
        self.calls.append(number)
        if self.gate:
            await self.gate.wait()
        if isinstance(self.answer, Exception):
            raise self.answer
        return {"number": number, "name": self.answer} if self.answer else None
    async def lookup_extension(self, number):
        result = await self.lookup_contact(number)
        if result:
            result["first_name"] = "ActualGiven"
        return result


class ResolverTests(unittest.IsolatedAsyncioTestCase):
    def resolver(self, **kwargs):
        provider = FakePhonebook()
        clock = [100.0]
        resolver = PhonebookResolver(provider, clock=lambda: clock[0], **kwargs)
        self.addAsyncCleanup(resolver.close)
        return resolver, provider, clock

    async def finish(self, resolver):
        if resolver._task:
            await resolver._task

    async def test_observe_is_nonblocking_normalizes_and_deduplicates_current_numbers(self):
        resolver, provider, clock = self.resolver()
        provider.gate = asyncio.Event()
        resolver.observe([NUMBER, "01234 567890", "200", "Unknown", ""])
        resolver.observe([NUMBER])
        await asyncio.sleep(0)
        self.assertEqual(provider.calls, [NUMBER])
        self.assertEqual(resolver.cached_contacts(), {})
        provider.gate.set()
        await self.finish(resolver)
        self.assertEqual(resolver.name_for("01234 567890"), "Example Caller")
        self.assertEqual(resolver.cached_contacts(), {NUMBER: "Example Caller"})

    async def test_directory_and_phonebook_are_narrow_separate_and_share_bounded_cache(self):
        resolver, provider, clock = self.resolver(max_entries=2)
        resolver.observe([NUMBER])
        resolver.observe_extensions(["271", "271", "Unknown", "+271", "٢٧١"])
        await self.finish(resolver)
        self.assertEqual(set(provider.calls), {NUMBER, "271"})
        self.assertEqual(resolver.cached_contacts(), {NUMBER: "Example Caller"})
        self.assertEqual(resolver.cached_extensions(), {"271": "ActualGiven"})
        self.assertEqual(resolver.name_for("271"), "ActualGiven")
        resolver.observe_extensions(["272"])
        await self.finish(resolver)
        self.assertLessEqual(len(resolver._cache), 2)

    async def test_directory_requires_actual_firstname_in_provider_result(self):
        resolver, provider, clock = self.resolver()
        async def only_label(number):
            return {"number": number, "name": "TB"}
        provider.lookup_extension = only_label
        resolver.observe_extensions(["271"])
        await self.finish(resolver)
        self.assertEqual(resolver.cached_extensions(), {})

    async def test_directory_is_not_implicitly_searched_by_external_number_observation(self):
        resolver, provider, clock = self.resolver()
        resolver.observe(["271"])
        await self.finish(resolver)
        self.assertEqual(provider.calls, [])
        resolver.observe_extensions(["271"])
        resolver.observe_extensions([])
        await self.finish(resolver)
        self.assertEqual(provider.calls, [])

    async def test_directory_can_be_explicitly_disabled(self):
        resolver, provider, clock = self.resolver(allow_internal=False)
        resolver.observe_extensions(["271"])
        await self.finish(resolver)
        self.assertEqual(provider.calls, [])

    async def test_positive_and_negative_ttl_limit_queries(self):
        resolver, provider, clock = self.resolver()
        resolver.observe([NUMBER]); await self.finish(resolver)
        clock[0] += 599
        resolver.observe([NUMBER]); await self.finish(resolver)
        self.assertEqual(len(provider.calls), 1)
        clock[0] += 1
        provider.answer = None
        resolver.observe([NUMBER]); await self.finish(resolver)
        self.assertIsNone(resolver.name_for(NUMBER))
        clock[0] += 59
        resolver.observe([NUMBER]); await self.finish(resolver)
        self.assertEqual(len(provider.calls), 2)
        clock[0] += 1
        resolver.observe([NUMBER]); await self.finish(resolver)
        self.assertEqual(len(provider.calls), 3)

    async def test_cache_bounded_and_failures_back_off_without_poisoning_names(self):
        resolver, provider, clock = self.resolver(max_entries=2)
        numbers = ["+441234567891", "+441234567892", "+441234567893"]
        resolver.observe(numbers); await self.finish(resolver)
        self.assertEqual(len(resolver.cached_contacts()), 2)
        provider.answer = RuntimeError("private-payload")
        resolver.observe([NUMBER]); await self.finish(resolver)
        self.assertIsNone(resolver.name_for(NUMBER))
        resolver.observe([NUMBER]); await self.finish(resolver)
        self.assertEqual(provider.calls.count(NUMBER), 1)
        self.assertLessEqual(len(resolver._cache), 2)

    async def test_old_queued_numbers_are_skipped_when_call_list_changes(self):
        resolver, provider, clock = self.resolver()
        resolver.observe([NUMBER])
        resolver.observe([])
        await self.finish(resolver)
        self.assertEqual(provider.calls, [])

    async def test_returned_wrong_number_is_not_cached_as_another_caller(self):
        resolver, provider, clock = self.resolver()
        async def wrong(number, **kwargs):
            return {"number": "+441234567899", "name": "Wrong Person"}
        provider.lookup_contact = wrong
        resolver.observe([NUMBER]); await self.finish(resolver)
        self.assertEqual(resolver.cached_contacts(), {})

    async def test_pending_queue_is_bounded_and_close_cancels_work_and_clears_names(self):
        resolver, provider, clock = self.resolver()
        provider.gate = asyncio.Event()
        resolver.observe(["+44123456%04d" % index for index in range(100)])
        self.assertLessEqual(resolver._queue.qsize(), 32)
        await asyncio.sleep(0)
        await resolver.close()
        self.assertTrue(resolver._task.done())
        self.assertEqual(resolver.cached_contacts(), {})
        self.assertEqual(resolver._pending, set())
        resolver.observe([NUMBER])
        self.assertEqual(resolver._queue.qsize(), 0)


if __name__ == "__main__":
    unittest.main()
