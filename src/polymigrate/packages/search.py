"""Bounded package-registry discovery. Results are untrusted metadata, never install instructions."""
from __future__ import annotations
import json
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from typing import Any


@dataclass(frozen=True)
class PackageCandidate:
    name: str
    version: str | None
    description: str
    registry: str
    url: str
    license: str | None = None
    downloads: int | None = None


@dataclass(frozen=True)
class PackageSearchResult:
    language_id: str
    query: str
    status: str
    candidates: tuple[PackageCandidate, ...]
    warning: str | None = None


class _PyPISearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[PackageCandidate] = []
        self._current: dict[str, str] | None = None
        self._field: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "a" and "package-snippet" in classes:
            href = attributes.get("href") or ""
            if href.startswith("/project/") and "/project/" not in href[9:]:
                self._current = {"url": "https://pypi.org" + href, "name": "", "version": "", "description": ""}
        elif self._current is not None and tag in {"span", "p"}:
            if "package-snippet__name" in classes:
                self._field = "name"
            elif "package-snippet__version" in classes:
                self._field = "version"
            elif "package-snippet__description" in classes:
                self._field = "description"
            if self._field:
                self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._current is not None and self._field:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._current is not None and self._field and tag in {"span", "p"}:
            self._current[self._field] = " ".join("".join(self._buffer).split())
            self._field = None
            self._buffer = []
        if tag == "a" and self._current is not None:
            if self._current.get("name"):
                item = self._current
                self.results.append(PackageCandidate(
                    name=item["name"][:200], version=item.get("version") or None,
                    description=item.get("description", "")[:1000], registry="pypi",
                    url=item["url"], license=None,
                ))
            self._current = None
            self._field = None
            self._buffer = []


class PackageRegistrySearcher:
    """Searches fixed public registry endpoints with strict result and response limits."""
    def __init__(self, timeout: float = 8.0, max_response_bytes: int = 2_000_000) -> None:
        if timeout <= 0 or max_response_bytes < 1:
            raise ValueError("timeout and response byte limit must be positive")
        self.timeout = timeout
        self.max_response_bytes = max_response_bytes

    @staticmethod
    def _candidate(name: Any, version: Any, description: Any, registry: str, url: Any,
                   license_name: Any = None, downloads: Any = None) -> PackageCandidate | None:
        if not isinstance(name, str) or not name.strip():
            return None
        if not isinstance(url, str) or not url.startswith("https://"):
            return None
        return PackageCandidate(
            name=name.strip()[:200],
            version=version[:100] if isinstance(version, str) else None,
            description=description[:1000] if isinstance(description, str) else "",
            registry=registry, url=url[:1000],
            license=license_name[:200] if isinstance(license_name, str) else None,
            downloads=downloads if isinstance(downloads, int) and downloads >= 0 else None,
        )

    def _fetch(self, url: str, accept: str = "application/json") -> bytes:
        request = Request(url, headers={"User-Agent": "PolyMigrate/0.1 package discovery", "Accept": accept})
        with urlopen(request, timeout=self.timeout) as response:
            data = response.read(self.max_response_bytes + 1)
        if len(data) > self.max_response_bytes:
            raise ValueError("Package registry response exceeded configured size limit")
        return data

    def search(self, language_id: str, query: str, limit: int = 10) -> PackageSearchResult:
        if not isinstance(language_id, str) or not language_id.strip() or len(language_id) > 50:
            raise ValueError("language_id must be a non-empty string of at most 50 characters")
        language = language_id.strip().lower()
        if not isinstance(query, str) or not query.strip() or len(query) > 200:
            raise ValueError("query must be a non-empty string of at most 200 characters")
        if not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20")
        try:
            if language in {"javascript", "typescript"}:
                candidates = self._search_npm(query, limit)
            elif language == "rust":
                candidates = self._search_crates(query, limit)
            elif language in {"java", "kotlin"}:
                candidates = self._search_maven(query, limit)
            elif language == "csharp":
                candidates = self._search_nuget(query, limit)
            elif language == "ruby":
                candidates = self._search_rubygems(query, limit)
            elif language == "php":
                candidates = self._search_packagist(query, limit)
            elif language == "python":
                candidates = self._search_pypi(query, limit)
                if not candidates:
                    candidates = self._search_github(query, "Python", limit)
            elif language == "go":
                candidates = self._search_github(query, "Go", limit)
            elif language == "c":
                candidates = self._search_github(query, "C", limit)
            elif language == "cpp":
                candidates = self._search_github(query, "C++", limit)
            elif language == "swift":
                candidates = self._search_github(query, "Swift", limit)
            else:
                return PackageSearchResult(language, query, "unsupported", (), f"No package search adapter is configured for {language}")
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            return PackageSearchResult(language, query, "unavailable", (),
                                       f"Package search failed ({type(exc).__name__}); no package was installed.")
        return PackageSearchResult(language, query, "available" if candidates else "empty", tuple(candidates[:limit]),
                                   None if candidates else "No candidates were returned; consider a custom implementation or architectural alternative.")

    def _search_npm(self, query: str, limit: int) -> list[PackageCandidate]:
        url = "https://registry.npmjs.org/-/v1/search?" + urlencode({"text": query, "size": limit})
        data = json.loads(self._fetch(url))
        items = data.get("objects", []) if isinstance(data, dict) else []
        out = []
        for item in items:
            package = item.get("package", {}) if isinstance(item, dict) else {}
            name = package.get("name")
            candidate = self._candidate(name, package.get("version"), package.get("description"), "npm",
                                        "https://www.npmjs.com/package/" + quote(name, safe="/@") if isinstance(name, str) else None,
                                        package.get("license"))
            if candidate:
                out.append(candidate)
        return out

    def _search_crates(self, query: str, limit: int) -> list[PackageCandidate]:
        url = "https://crates.io/api/v1/crates?" + urlencode({"q": query, "per_page": limit})
        data = json.loads(self._fetch(url))
        items = data.get("crates", []) if isinstance(data, dict) else []
        out = []
        for item in items:
            name = item.get("id")
            candidate = self._candidate(name, item.get("max_version"), item.get("description"), "crates.io",
                                        "https://crates.io/crates/" + quote(name, safe="") if isinstance(name, str) else None,
                                        item.get("license"), item.get("downloads"))
            if candidate:
                out.append(candidate)
        return out

    def _search_maven(self, query: str, limit: int) -> list[PackageCandidate]:
        url = "https://search.maven.org/solrsearch/select?" + urlencode({"q": query, "rows": limit, "wt": "json"})
        data = json.loads(self._fetch(url))
        response = data.get("response", {}) if isinstance(data, dict) else {}
        out = []
        for item in response.get("docs", []):
            name = item.get("id")
            candidate = self._candidate(name, item.get("latestVersion"), item.get("description"), "maven-central",
                                        "https://search.maven.org/search?" + urlencode({"q": "g:" + name.split(":")[0] + " AND a:" + name.split(":")[-1]}) if isinstance(name, str) and ":" in name else "https://search.maven.org/",
                                        item.get("license"))
            if candidate:
                out.append(candidate)
        return out

    def _search_nuget(self, query: str, limit: int) -> list[PackageCandidate]:
        url = "https://azuresearch-usnc.nuget.org/query?" + urlencode({"q": query, "take": limit, "prerelease": "false"})
        data = json.loads(self._fetch(url))
        out = []
        for item in data.get("data", []) if isinstance(data, dict) else []:
            name = item.get("id")
            candidate = self._candidate(name, item.get("version"), item.get("description"), "nuget",
                                        "https://www.nuget.org/packages/" + quote(name, safe="") if isinstance(name, str) else None,
                                        None, item.get("totalDownloads"))
            if candidate:
                out.append(candidate)
        return out

    def _search_rubygems(self, query: str, limit: int) -> list[PackageCandidate]:
        url = "https://rubygems.org/api/v1/search.json?" + urlencode({"query": query})
        data = json.loads(self._fetch(url))
        out = []
        for item in data[:limit] if isinstance(data, list) else []:
            name = item.get("name")
            candidate = self._candidate(name, item.get("version"), item.get("info"), "rubygems",
                                        "https://rubygems.org/gems/" + quote(name, safe="") if isinstance(name, str) else None,
                                        None, item.get("downloads"))
            if candidate:
                out.append(candidate)
        return out

    def _search_packagist(self, query: str, limit: int) -> list[PackageCandidate]:
        url = "https://packagist.org/search.json?" + urlencode({"q": query, "per_page": limit})
        data = json.loads(self._fetch(url))
        out = []
        for item in data.get("results", []) if isinstance(data, dict) else []:
            name = item.get("name")
            candidate = self._candidate(name, item.get("version"), item.get("description"), "packagist",
                                        "https://packagist.org/packages/" + quote(name, safe="/") if isinstance(name, str) else None)
            if candidate:
                out.append(candidate)
        return out

    def _search_pypi(self, query: str, limit: int) -> list[PackageCandidate]:
        url = "https://pypi.org/search/?" + urlencode({"q": query})
        html = self._fetch(url, accept="text/html").decode("utf-8", errors="replace")
        parser = _PyPISearchParser()
        parser.feed(html)
        return parser.results[:limit]

    def _search_github(self, query: str, language: str, limit: int) -> list[PackageCandidate]:
        url = "https://api.github.com/search/repositories?" + urlencode({
            "q": f"{query} language:{language}", "sort": "stars", "order": "desc", "per_page": limit,
        })
        data = json.loads(self._fetch(url))
        out = []
        for item in data.get("items", []) if isinstance(data, dict) else []:
            name = item.get("full_name")
            description = item.get("description") if isinstance(item.get("description"), str) else ""
            stars = item.get("stargazers_count")
            if isinstance(stars, int) and stars >= 0:
                description = f"{description} [GitHub stars: {stars}]".strip()
            candidate = self._candidate(name, None, description, "github-repositories", item.get("html_url"))
            if candidate:
                out.append(candidate)
        return out
