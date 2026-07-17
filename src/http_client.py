from __future__ import annotations

from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


class HttpClient:
    def __init__(self, user_agent: str, timeout: float) -> None:
        self._client = httpx.Client(
            headers={
                "User-Agent": user_agent,
                "Accept": "*/*",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            },
            timeout=timeout,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3))
    def get_text(self, url: str, referer: str | None = None) -> str:
        headers = {"Referer": referer} if referer else None
        response = self._client.get(url, headers=headers)
        response.raise_for_status()
        response.encoding = response.encoding or "utf-8"
        return response.text

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3))
    def get_bytes(self, url: str, referer: str | None = None) -> bytes:
        headers = {"Referer": referer} if referer else None
        response = self._client.get(url, headers=headers)
        response.raise_for_status()
        return response.content

    def get_json(self, url: str) -> object:
        response = self._client.get(url)
        response.raise_for_status()
        return response.json()
