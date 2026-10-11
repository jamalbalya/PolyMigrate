"""Package registry discovery tests use mock HTTP responses only."""
import json
import unittest
from unittest.mock import patch
from polymigrate.packages.search import PackageRegistrySearcher


class FakeResponse:
    def __init__(self, body): self.body=body
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self, limit): return self.body[:limit]


class PackageSearchTests(unittest.TestCase):
    def test_npm_search_uses_fixed_registry_and_normalizes_candidate(self):
        body=json.dumps({"objects":[{"package":{"name":"date-helper","version":"1.2.3",
             "description":"Date utilities","license":"MIT"}}]}).encode()
        with patch("polymigrate.packages.search.urlopen",return_value=FakeResponse(body)) as open_url:
            result=PackageRegistrySearcher().search("typescript","date utilities",limit=5)
        self.assertEqual(result.status,"available")
        self.assertEqual(result.candidates[0].name,"date-helper")
        self.assertEqual(result.candidates[0].registry,"npm")
        self.assertTrue(open_url.call_args.args[0].full_url.startswith("https://registry.npmjs.org/"))
        self.assertEqual(open_url.call_args.kwargs["timeout"],8.0)

    def test_crates_search_uses_crates_registry(self):
        body=json.dumps({"crates":[{"id":"date-utils","max_version":"0.4.0","description":"Date utilities","downloads":50}]}).encode()
        with patch("polymigrate.packages.search.urlopen",return_value=FakeResponse(body)) as open_url:
            result=PackageRegistrySearcher().search("rust","date utilities")
        self.assertEqual(result.candidates[0].name,"date-utils")
        self.assertTrue(open_url.call_args.args[0].full_url.startswith("https://crates.io/api/v1/crates?"))

    def test_pypi_search_parses_package_snippets(self):
        html=b'<a class="package-snippet" href="/project/date-utils/"><span class="package-snippet__name">date-utils</span><span class="package-snippet__version">1.0</span><p class="package-snippet__description">Date helpers</p></a>'
        with patch("polymigrate.packages.search.urlopen",return_value=FakeResponse(html)):
            result=PackageRegistrySearcher().search("python","date helpers")
        self.assertEqual(result.candidates[0].name,"date-utils")
        self.assertEqual(result.candidates[0].version,"1.0")
        self.assertEqual(result.candidates[0].url,"https://pypi.org/project/date-utils/")

    def test_unsupported_language_is_explicit(self):
        result=PackageRegistrySearcher().search("unknown","some package")
        self.assertEqual(result.status,"unsupported")
        self.assertEqual(result.candidates,())

    def test_registry_errors_degrade_without_claiming_success(self):
        from urllib.error import URLError
        with patch("polymigrate.packages.search.urlopen",side_effect=URLError("offline")):
            result=PackageRegistrySearcher().search("rust","date utilities")
        self.assertEqual(result.status,"unavailable")
        self.assertEqual(result.candidates,())
        self.assertIn("no package was installed",result.warning)

    def test_query_and_limit_are_bounded(self):
        with self.assertRaises(ValueError):
            PackageRegistrySearcher().search("rust","")
        with self.assertRaises(ValueError):
            PackageRegistrySearcher().search("rust","query",limit=100)

    def test_github_fallback_does_not_mislabel_stars_as_downloads(self):
        body=json.dumps({"items":[{"full_name":"org/date-utils","description":"Date helpers",
                                   "html_url":"https://github.com/org/date-utils","stargazers_count":123}]}).encode()
        with patch("polymigrate.packages.search.urlopen",return_value=FakeResponse(body)):
            result=PackageRegistrySearcher().search("go","date helpers")
        self.assertEqual(result.candidates[0].downloads,None)
        self.assertIn("GitHub stars: 123",result.candidates[0].description)


if __name__ == "__main__":
    unittest.main()
