import unittest
from unittest.mock import Mock, patch

import bot


class ScannerTests(unittest.TestCase):
    def test_all_seven_listing_sources_are_configured(self):
        self.assertEqual(len(bot.SOURCES), 7)
        self.assertEqual(len({s["host"] for s in bot.SOURCES}), 7)

    def test_event_links_reject_other_hosts_and_keep_configured_event_paths(self):
        source = {"url": "https://example.test/events", "host": "example.test", "paths": ("/event/",)}
        links = bot.event_links(source, '<a href="/event/race-1">race</a><a href="https://evil.test/event/no">x</a><a href="/blog/event/post">x</a>')
        self.assertEqual(links, ["https://example.test/event/race-1"])

    def test_event_requires_original_image_and_registration_link(self):
        source = {"name": "Example"}
        page = '<meta property="og:title" content="City Run 2027"><meta property="og:image" content="/original.jpg"><a href="https://register.test/r1">Register now</a>'
        with patch.object(bot, "get", return_value=page):
            event = bot.event_from_page(source, "https://example.test/event/city-run")
        self.assertIsNotNone(event)
        self.assertEqual(event.image_url, "https://example.test/original.jpg")
        self.assertEqual(event.registration_url, "https://register.test/r1")

    def test_event_without_artwork_or_registration_is_skipped(self):
        page = '<meta property="og:title" content="City Run"><a href="https://example.test/event/city-run">Details</a>'
        with patch.object(bot, "get", return_value=page):
            self.assertIsNone(bot.event_from_page({"name": "Example"}, "https://example.test/event/city-run"))

    @patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "42"})
    @patch.object(bot.requests, "post")
    def test_telegram_uses_sendphoto_with_original_image_and_registration_link(self, post):
        post.return_value = Mock(status_code=200, json=lambda: {"ok": True})
        event = bot.Event("key", "City Run", "https://example.test/e", "https://register.test/e", "https://example.test/original.jpg", "Example")
        bot.send_telegram(event)
        url, kwargs = post.call_args.args[0], post.call_args.kwargs
        self.assertTrue(url.endswith("/sendPhoto"))
        self.assertEqual(kwargs["data"]["photo"], event.image_url)
        self.assertEqual(kwargs["data"]["caption"], event.registration_url)


if __name__ == "__main__":
    unittest.main()
