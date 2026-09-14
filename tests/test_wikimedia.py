"""Pure-logic tests for pipeline/wikimedia.py's license filtering -- no
real network calls (mocks requests.get), per CLAUDE.md's testing rules.
"""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from pipeline import wikimedia


def _page(title: str, mime: str, license_name: str, url: str = "https://example.org/x.jpg") -> dict:
    return {
        "title": title,
        "imageinfo": [
            {
                "mime": mime,
                "thumburl": url,
                "url": url,
                "descriptionurl": f"https://commons.wikimedia.org/wiki/{title}",
                "extmetadata": {"LicenseShortName": {"value": license_name}},
            }
        ],
    }


class TestBestLicensedImage(unittest.TestCase):
    def test_public_domain_image_is_accepted(self):
        pages = {"1": _page("File:Bell.jpg", "image/jpeg", "Public domain")}
        result = wikimedia._best_licensed_image(pages)
        self.assertIsNotNone(result)
        self.assertEqual(result["license"], "Public domain")

    def test_cc0_image_is_accepted(self):
        pages = {"1": _page("File:Bell.jpg", "image/jpeg", "CC0")}
        result = wikimedia._best_licensed_image(pages)
        self.assertIsNotNone(result)

    def test_cc_by_requiring_attribution_is_rejected(self):
        """CC-BY/CC-BY-SA are legally usable but need real per-image
        credit this pipeline has no format for -- must be filtered out,
        not silently used unattributed."""
        pages = {"1": _page("File:Bell.jpg", "image/jpeg", "CC BY-SA 4.0")}
        result = wikimedia._best_licensed_image(pages)
        self.assertIsNone(result)

    def test_svg_diagram_is_rejected(self):
        pages = {"1": _page("File:Diagram.svg", "image/svg+xml", "Public domain")}
        result = wikimedia._best_licensed_image(pages)
        self.assertIsNone(result)

    def test_falls_through_to_a_later_page_with_an_accepted_license(self):
        pages = {
            "1": _page("File:Restricted.jpg", "image/jpeg", "CC BY-SA 4.0"),
            "2": _page("File:Free.jpg", "image/jpeg", "CC0"),
        }
        result = wikimedia._best_licensed_image(pages)
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "File:Free.jpg")

    def test_no_pages_returns_none(self):
        self.assertIsNone(wikimedia._best_licensed_image({}))


class TestSearchCommonsImage(unittest.TestCase):
    def test_empty_subject_returns_none_without_a_network_call(self):
        with patch.object(wikimedia.requests, "get") as mock_get:
            result = wikimedia.search_commons_image("")
        self.assertIsNone(result)
        mock_get.assert_not_called()

    def test_network_error_is_treated_as_no_image_available(self):
        """Fail soft -- a Wikimedia outage must not raise out of an
        optional supplemental-beat lookup."""
        with patch.object(wikimedia.requests, "get", side_effect=wikimedia.requests.RequestException("boom")):
            result = wikimedia.search_commons_image("Oxford Electric Bell")
        self.assertIsNone(result)

    def test_successful_response_is_parsed_into_the_best_licensed_image(self):
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "query": {"pages": {"1": _page("File:Bell.jpg", "image/jpeg", "Public domain")}}
        }
        with patch.object(wikimedia.requests, "get", return_value=mock_response):
            result = wikimedia.search_commons_image("Oxford Electric Bell")
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "File:Bell.jpg")


if __name__ == "__main__":
    unittest.main()
