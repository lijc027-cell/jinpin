from __future__ import annotations

from bs4 import BeautifulSoup
import httpx

from jingyantai.tools.contracts import PageData


class HttpPageExtractor:
    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.http_client = http_client

    def extract(self, url: str) -> PageData:
        headers = {"User-Agent": "jingyantai/0.1.0"}
        if self.http_client is None:
            response = httpx.get(url, timeout=self.timeout_seconds, headers=headers, follow_redirects=True)
        else:
            response = self.http_client.get(url, timeout=self.timeout_seconds, headers=headers, follow_redirects=True)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else url
        text = " ".join(soup.stripped_strings)
        excerpt = text[:280]
        return PageData(url=url, title=title, text=text[:4000], excerpt=excerpt)
