"""GitHub Issues (demand: feature requests, complaints, workarounds) and repositories (supply:
open-source alternatives). Works without a token at 10 req/min; GITHUB_TOKEN raises limits."""

from __future__ import annotations

import re

from ..core.settings import get_settings
from ..core.timeutil import days_ago, parse_datetime, utcnow
from .base import BaseAdapter, Engagement, FetchResult, RawProduct, RawSignal, SearchQuery
from .http import client, get_json

API = "https://api.github.com"


_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_CHECKBOX = re.compile(r"^\s*[-*]\s*\[[ xX]\]\s*.*$", re.MULTILINE)
_TEMPLATE_HEADING = re.compile(
    r"^\s*#{1,6}\s*(preflight checklist|checklist|is there an existing issue.*|steps to reproduce|expected behavior|actual behavior|environment|version|additional context|screenshots?)\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)


def strip_issue_template(body: str) -> str:
    """Remove issue-template boilerplate (HTML comments, checkboxes, template headings, code blocks) so the
    pain filter sees what the person actually wrote."""
    text = _HTML_COMMENT.sub(" ", body)
    text = _CODE_BLOCK.sub(" ", text)
    text = _CHECKBOX.sub(" ", text)
    text = _TEMPLATE_HEADING.sub(" ", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = get_settings().github_token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class GitHubIssuesAdapter(BaseAdapter):
    adapter_id = "github_issues"
    type = "demand"

    def search(self, query: SearchQuery) -> FetchResult:
        since = days_ago(query.window_days).strftime("%Y-%m-%d")
        q = f"{query.text} is:issue created:>={since}"
        result = FetchResult()
        with client(headers=_headers()) as c:
            data = get_json(
                c,
                f"{API}/search/issues",
                params={"q": q, "sort": "reactions", "order": "desc", "per_page": min(100, query.limit)},
            )
            for item in data.get("items", []) if isinstance(data, dict) else []:
                body = strip_issue_template(item.get("body") or "")
                title = (item.get("title") or "").strip()
                if not title:
                    continue
                repo = "/".join(item.get("repository_url", "").split("/")[-2:])
                reactions = item.get("reactions") or {}
                result.signals.append(
                    RawSignal(
                        external_id=str(item.get("id")),
                        source=self.id,
                        adapter=self.adapter_id,
                        url=item.get("html_url", ""),
                        title=title,
                        content=(body or title)[:6000],
                        author=(item.get("user") or {}).get("login"),
                        author_id=(item.get("user") or {}).get("login"),
                        created_at=parse_datetime(item.get("created_at")),
                        fetched_at=utcnow(),
                        engagement=Engagement(
                            votes=int(reactions.get("+1") or 0) + int(reactions.get("heart") or 0),
                            comments=int(item.get("comments") or 0),
                        ),
                        metadata={
                            "repo": repo,
                            "labels": [lb.get("name") for lb in item.get("labels", [])],
                            "state": item.get("state"),
                        },
                    )
                )
        return result


class GitHubReposAdapter(BaseAdapter):
    adapter_id = "github_repos"
    type = "supply"

    def search(self, query: SearchQuery) -> FetchResult:
        result = FetchResult()
        with client(headers=_headers()) as c:
            data = get_json(
                c,
                f"{API}/search/repositories",
                params={
                    "q": f"{query.text} in:name,description,readme",
                    "sort": "stars",
                    "order": "desc",
                    "per_page": min(50, query.limit),
                },
            )
            for repo in data.get("items", []) if isinstance(data, dict) else []:
                result.products.append(
                    RawProduct(
                        external_id=str(repo.get("id")),
                        source=self.id,
                        adapter=self.adapter_id,
                        name=repo.get("full_name", ""),
                        slug=repo.get("name"),
                        tagline=(repo.get("description") or "")[:200],
                        description=repo.get("description"),
                        url=repo.get("html_url", ""),
                        website=repo.get("homepage") or None,
                        categories=list(repo.get("topics") or [])[:8],
                        votes=int(repo.get("stargazers_count") or 0),
                        comments=int(repo.get("open_issues_count") or 0),
                        launched_at=parse_datetime(repo.get("created_at")),
                        makers=[{"name": (repo.get("owner") or {}).get("login")}],
                        credibility={
                            "forks": repo.get("forks_count"),
                            "license": (repo.get("license") or {}).get("spdx_id"),
                            "pushed_at": repo.get("pushed_at"),
                        },
                        pricing="open_source",
                        pricing_origin="api",
                        raw={"language": repo.get("language"), "archived": repo.get("archived")},
                        fetched_at=utcnow(),
                    )
                )
        return result
