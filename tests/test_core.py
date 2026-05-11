import unittest

from llm_client import LLMClient
from source_identity import stable_source_id


class SourceIdentityTests(unittest.TestCase):
    def test_stable_source_id_is_deterministic_and_js_safe(self):
        first = stable_source_id("https://news.ycombinator.com/rss", "rss")
        second = stable_source_id("https://news.ycombinator.com/rss", "rss")

        self.assertEqual(first, second)
        self.assertLess(first, 2**53)

    def test_stable_source_id_uses_namespace(self):
        rss_id = stable_source_id("example", "rss")
        web_id = stable_source_id("example", "web")

        self.assertNotEqual(rss_id, web_id)


class LLMClientTests(unittest.TestCase):
    def test_normalize_base_url(self):
        self.assertEqual(
            LLMClient._normalize_base_url("http://localhost:1234/api/v1"),
            "http://localhost:1234",
        )
        self.assertEqual(
            LLMClient._normalize_base_url("http://localhost:1234/v1/"),
            "http://localhost:1234",
        )

    def test_extract_native_text_from_string_content(self):
        data = {"output": [{"type": "message", "content": "ok"}]}

        self.assertEqual(LLMClient._extract_native_text(data), "ok")

    def test_extract_native_text_from_block_content(self):
        data = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "hello"}],
                }
            ]
        }

        self.assertEqual(LLMClient._extract_native_text(data), "hello")


if __name__ == "__main__":
    unittest.main()
