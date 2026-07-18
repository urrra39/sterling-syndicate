from __future__ import annotations

"""Lead ingestion — only sources that allow programmatic access + manual paste.

NON-NEGOTIABLE: no Upwork/Fiverr login automation or scrapers for gated pages.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional
from xml.etree import ElementTree

import httpx


@dataclass
class RawLead:
    source: str
    title: str
    raw_text: str
    url: Optional[str] = None
    category: Optional[str] = None


class BaseIngestor(ABC):
    @abstractmethod
    def fetch(self) -> List[RawLead]:
        ...


class ManualPasteIngestor(BaseIngestor):
    """User pastes a job post (including Upwork/Fiverr text they copied themselves)."""

    def __init__(
        self,
        text: str,
        title: str = "",
        url: Optional[str] = None,
        category: Optional[str] = None,
    ) -> None:
        self.text = text.strip()
        self.title = title.strip() or (self.text.split("\n", 1)[0][:120] if self.text else "Untitled")
        self.url = url
        self.category = category

    def fetch(self) -> List[RawLead]:
        if not self.text:
            return []
        return [
            RawLead(
                source="manual",
                title=self.title,
                raw_text=self.text,
                url=self.url,
                category=self.category,
            )
        ]


class RemoteOKIngestor(BaseIngestor):
    """Public RemoteOK JSON API — no auth, terms allow programmatic access."""

    API_URL = "https://remoteok.com/api"

    def __init__(self, limit: int = 20, tags: Optional[List[str]] = None) -> None:
        self.limit = max(1, min(limit, 50))
        self.tags = [t.lower() for t in (tags or [])]

    def fetch(self) -> List[RawLead]:
        headers = {"User-Agent": "The Sterling Syndicate/0.1 (open-source portfolio; +https://github.com/urrra39/sterling-syndicate)"}
        with httpx.Client(timeout=30.0, headers=headers) as client:
            resp = client.get(self.API_URL)
            resp.raise_for_status()
            data = resp.json()

        leads: List[RawLead] = []
        for item in data:
            if not isinstance(item, dict) or "id" not in item:
                continue  # first element is metadata
            tags = [str(t).lower() for t in (item.get("tags") or [])]
            if self.tags and not any(t in tags for t in self.tags):
                continue
            title = str(item.get("position") or item.get("company") or "Remote job")
            desc = str(item.get("description") or "")
            # Strip crude HTML tags without pulling in a parser dep
            plain = re_sub_tags(desc)
            company = item.get("company") or ""
            body = f"{title}\nCompany: {company}\nTags: {', '.join(tags)}\n\n{plain}".strip()
            url = item.get("url") or item.get("apply_url")
            leads.append(
                RawLead(
                    source="remoteok",
                    title=title[:500],
                    raw_text=body[:20000],
                    url=str(url) if url else None,
                    category=tags[0] if tags else None,
                )
            )
            if len(leads) >= self.limit:
                break
        return leads


class WeWorkRemotelyRSSIngestor(BaseIngestor):
    """We Work Remotely public RSS feed."""

    FEED_URL = "https://weworkremotely.com/categories/remote-programming-jobs.rss"

    def __init__(self, limit: int = 20) -> None:
        self.limit = max(1, min(limit, 50))

    def fetch(self) -> List[RawLead]:
        headers = {"User-Agent": "The Sterling Syndicate/0.1 (open-source portfolio)"}
        with httpx.Client(timeout=30.0, headers=headers, follow_redirects=True) as client:
            resp = client.get(self.FEED_URL)
            resp.raise_for_status()
            root = ElementTree.fromstring(resp.text)

        leads: List[RawLead] = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "WWR job").strip()
            link = (item.findtext("link") or "").strip() or None
            desc = re_sub_tags(item.findtext("description") or "")
            leads.append(
                RawLead(
                    source="weworkremotely",
                    title=title[:500],
                    raw_text=f"{title}\n\n{desc}".strip()[:20000],
                    url=link,
                    category="programming",
                )
            )
            if len(leads) >= self.limit:
                break
        return leads


def re_sub_tags(html: str) -> str:
    import re

    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()
