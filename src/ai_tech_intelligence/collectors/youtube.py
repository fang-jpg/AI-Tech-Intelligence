from __future__ import annotations

import os

import httpx

from ..models import Candidate, SourceTier
from ..utils import parse_date
from .base import SourceAdapter


class YouTubeCollector(SourceAdapter):
    """Collect official video metadata; transcript/ASR is intentionally out of scope."""

    def __init__(self, api_key: str | None = None, timeout: float = 30.0):
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("缺少 YOUTUBE_API_KEY")
        self.client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self.client.close()

    def discover(
        self,
        company: str,
        channel_id: str,
        channel_name: str,
        max_results: int = 10,
        query: str = "AI model",
    ) -> list[Candidate]:
        response = self.client.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "key": self.api_key,
                "part": "snippet",
                "channelId": channel_id,
                "type": "video",
                "order": "date",
                "maxResults": min(max_results, 50),
                "q": query,
            },
        )
        response.raise_for_status()
        output: list[Candidate] = []
        for item in response.json().get("items", []):
            video_id = item.get("id", {}).get("videoId")
            snippet = item.get("snippet", {})
            if not video_id:
                continue
            output.append(
                Candidate(
                    company=company,
                    source_id=f"youtube_{channel_id}",
                    source_name=channel_name,
                    source_type="official_video",
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    title=str(snippet.get("title", "")),
                    published_at=parse_date(snippet.get("publishedAt")),
                    snippet=str(snippet.get("description", "")),
                    tier_hint=SourceTier.B,
                    official_hint=True,
                    metadata={"channel_id": channel_id, "video_id": video_id, "transcript_available": False},
                )
            )
        return output

