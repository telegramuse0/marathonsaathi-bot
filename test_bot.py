import unittest
from unittest.mock import Mock, patch

import bot


class ScannerTests(unittest.TestCase):
    def test_send_batch_limit_is_three(self):
        self.assertEqual(bot.MAX_SEND_PER_RUN, 3)

    def test_all_seven_listing_sources_are_configured(self):
        self.assertEqual(len(bot.SOURCES), 7)
        self.assertEqual(len({s["host"] for s in bot.SOURCES}), 7)
        self.assertEqual({s["name"] for s in bot.SOURCES}, {"MarathonMitra", "India Running", "MySamay", "fstr", "RunnersDuniya", "MarathonTracks", "runINDIA"})

    def test_event_links_reject_other_hosts_and_keep_configured_event_paths(self):
        source = {"url": "https://example.test/events", "host": "example.test", "paths": ("/event/",)}
        links = bot.event_links(source, '<a href="/event/race-1">race</a><a href="https://evil.test/event/no">x</a><a href="/blog/event/post">x</a>')
        self.assertEqual(links, ["https://example.test/event/race-1"])

    def test_marathontracks_detail_url_keeps_slug_query(self):
        source = {"url": "https://marathontracks.com/marathons.php", "host": "marathontracks.com", "paths": ("/details.php",)}
        links = bot.event_links(source, '<a href="/details.php?slug=hoysala-hustle-2026">Race</a>')
        self.assertEqual(links, ["https://marathontracks.com/details.php?slug=hoysala-hustle-2026"])

    def test_mysamay_accepts_both_event_url_formats(self):
        source = {"url": "https://mysamay.in/", "host": "mysamay.in", "paths": ("/e/", "/event/info/")}
        html = '<a href="/e/mysuru_marathon_26?cmeta=abc">Race</a><a href="/event/info/123?cmeta=xyz">Race info</a>'
        self.assertEqual(bot.event_links(source, html), [
            "https://mysamay.in/e/mysuru_marathon_26?cmeta=abc",
            "https://mysamay.in/event/info/123?cmeta=xyz",
        ])

    def test_india_running_card_requires_original_image_and_register_link(self):
        source = {"name": "India Running", "host": "indiarunning.com", "paths": ("/event/", "/events/"), "registration_hosts": ("registrations.indiarunning.com",)}
        html = '<article><h3>City Run 2027</h3><a href="/events/city-run-2027">Event details</a><img src="/poster.jpg"><a href="https://registrations.indiarunning.com/city-run">Register</a></article>'
        from bs4 import BeautifulSoup
        anchor = BeautifulSoup(html, "html.parser").find("a", string="Register")
        event = bot._card_event(source, anchor, "https://www.indiarunning.com/city/Kolkata")
        self.assertEqual(event.title, "City Run 2027")
        self.assertEqual(event.event_url, "https://indiarunning.com/events/city-run-2027")
        self.assertEqual(event.image_url, "https://www.indiarunning.com/poster.jpg")
        self.assertEqual(event.registration_url, "https://registrations.indiarunning.com/city-run")

    def test_unparseable_source_is_reported_as_scan_error(self):
        source = {"name": "Example", "url": "https://example.test/list", "host": "example.test", "paths": ("/event/",)}
        with patch.object(bot, "SOURCES", [source]), patch.object(bot, "get", return_value="<html><body>No race links</body></html>"):
            self.assertEqual(bot.scan_sources(), [])
        self.assertEqual(bot.SCAN_ERRORS, ["Example: no parseable event links"])

    def test_known_empty_listing_is_warning_only(self):
        source = {"name": "MySamay", "url": "https://example.test/list", "host": "example.test", "paths": ("/event/",), "allow_empty": True}
        with patch.object(bot, "SOURCES", [source]), patch.object(bot, "get", return_value="<html><body>No upcoming events</body></html>"):
            self.assertEqual(bot.scan_sources(), [])
        self.assertEqual(bot.SCAN_ERRORS, [])

    @patch.dict("os.environ", {"DRY_RUN": "true"}, clear=True)
    @patch.object(bot, "scan_sources", return_value=[])
    @patch.object(bot, "load_seen", return_value=set())
    def test_scan_only_does_not_fail_when_source_is_temporarily_unavailable(self, _seen, _scan):
        bot.SCAN_ERRORS[:] = ["Example: temporary network error"]
        self.assertEqual(bot.main(), 0)

    @patch.dict("os.environ", {"DRY_RUN": "true", "SEND_TELEGRAM_REQUESTED": "true", "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}, clear=True)
    @patch.object(bot, "scan_sources", return_value=[])
    @patch.object(bot, "load_seen", return_value=set())
    def test_send_requested_without_secrets_stays_scan_only(self, _seen, _scan):
        bot.SCAN_ERRORS.clear()
        self.assertEqual(bot.main(), 0)

    def test_event_requires_original_image_and_registration_link(self):
        source = {"name": "Example"}
        page = '<meta property="og:title" content="City Run 2027"><meta property="og:image" content="/original.jpg"><a href="https://register.test/r1">Register now</a>'
        with patch.object(bot, "get", return_value=page):
            event = bot.event_from_page(source, "https://example.test/event/city-run")
        self.assertIsNotNone(event)
        self.assertEqual(event.image_url, "https://example.test/original.jpg")
        self.assertEqual(event.registration_url, "https://register.test/r1")

    def test_image_fallback_uses_only_race_identified_source_image(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup('<img alt="Site logo" src="/logo.png"><img alt="City Run 2027 event poster" src="/race.jpg">', "html.parser")
        self.assertEqual(bot._original_event_image(soup, "City Run 2027", "https://example.test/e/1"), "https://example.test/race.jpg")

    def test_event_without_artwork_or_registration_is_skipped(self):
        page = '<meta property="og:title" content="City Run"><a href="https://example.test/event/city-run">Details</a>'
        with patch.object(bot, "get", return_value=page):
            self.assertIsNone(bot.event_from_page({"name": "Example"}, "https://example.test/event/city-run"))

    @patch.dict("os.environ", {"DRY_RUN": "false", "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}, clear=True)
    @patch.object(bot, "scan_sources", return_value=[])
    @patch.object(bot, "load_seen", return_value=set())
    def test_missing_telegram_credentials_fail_closed(self, _seen, _scan):
        bot.SCAN_ERRORS.clear()
        self.assertEqual(bot.main(), 1)

    def test_only_future_events_pass_the_date_filter(self):
        today = bot.date.today().strftime("%d %b %Y")
        event = bot.Event("k", "Run", "https://e", "https://r", "https://i", "test", today)
        self.assertTrue(bot.is_upcoming(event))
        self.assertFalse(bot.is_upcoming(bot.Event("k", "Run", "https://e", "https://r", "https://i", "test")))

    @patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "42"})
    @patch.object(bot.requests, "post")
    def test_telegram_uses_sendphoto_with_original_image_and_registration_link(self, post):
        post.return_value = Mock(status_code=200, json=lambda: {"ok": True})
        event = bot.Event("key", "City Run", "https://example.test/e", "https://register.test/e", "https://example.test/original.jpg", "Example")
        bot.send_telegram(event)
        url, kwargs = post.call_args.args[0], post.call_args.kwargs
        self.assertTrue(url.endswith("/sendPhoto"))
        self.assertEqual(kwargs["data"]["photo"], event.image_url)
        self.assertEqual(kwargs["data"]["caption"], event.event_url)


if __name__ == "__main__":
    unittest.main()

