from __future__ import annotations

from bs4 import BeautifulSoup
import httpx

from jingyantai.tools.contracts import PageData


class HttpPageExtractor:
    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.http_client = http_client

    def extract(self, url: str, timeout_seconds: float | None = None) -> PageData:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        timeout = self.timeout_seconds if timeout_seconds is None else timeout_seconds
        if self.http_client is None:
            response = httpx.get(
                url,
                timeout=timeout,
                headers=headers,
                follow_redirects=True,
                trust_env=False,
            )
        else:
            response = self.http_client.get(url, timeout=timeout, headers=headers, follow_redirects=True)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        final_url = str(response.url)
        title = soup.title.string.strip() if soup.title and soup.title.string else final_url
        text = " ".join(soup.stripped_strings)
        excerpt = text[:280]
        return PageData(url=final_url, title=title, text=text[:4000], excerpt=excerpt)
