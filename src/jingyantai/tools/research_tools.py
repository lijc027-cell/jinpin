from __future__ import annotations

import inspect
from time import perf_counter
from typing import Callable
from urllib.parse import urlparse, urlunparse

from jingyantai.tools.contracts import (
    GitHubSignalsClient,
    PageData,
    PageExtractor,
    ResearchToolset,
    SearchClient,
    ToolExecutionMetrics,
)


class ResearchTools(ResearchToolset):
    URL_PRECHECK_TIMEOUT_CAP_SECONDS = 3.0

    def __init__(
        self,
        search_client: SearchClient,
        page_extractor: PageExtractor,
        github_signals: GitHubSignalsClient,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.search_client = search_client
        self.page_extractor = page_extractor
        self.github_signals = github_signals
        self._clock = clock or perf_counter
        self._last_metrics = ToolExecutionMetrics()
        self._search_cache: dict[tuple[str, int], list] = {}
        self._page_cache: dict[str, PageData] = {}
        self._page_failure_cache: dict[str, Exception] = {}
        self._primary_page_resolution_cache: dict[str, tuple[PageData, dict[str, str]]] = {}
        self._github_cache: dict[str, list[dict[str, str | int]]] = {}
        self._runtime_deadline_at: float | None = None

    def _domain_identity(self, url: str) -> str:
        domain = urlparse(url).netloc.removeprefix("www.").lower()
        labels = [label for label in domain.split(".") if label]
        if not labels:
            return ""
        if len(labels) == 1:
            return labels[0]
        if len(labels) >= 3 and labels[-2] in {"co", "com", "org", "net", "gov", "edu"}:
            return labels[-3]
        return labels[-2]

    def _normalize_url(self, url: str) -> str:
        parsed = urlparse(url.strip())
        scheme = (parsed.scheme or "https").lower()
        domain = parsed.netloc.removeprefix("www.").lower()
        path = parsed.path or ""

        if domain == "github.com":
            segments = [segment for segment in path.split("/") if segment]
            if len(segments) >= 2:
                owner = segments[0]
                repo = segments[1].removesuffix(".git")
                path = f"/{owner}/{repo}"
            else:
                path = "/" + "/".join(segments) if segments else ""
        elif path in {"", "/"}:
            path = ""
        else:
            path = path.rstrip("/")

        return urlunparse((scheme, domain, path, "", "", ""))

    def _reset_metrics(self) -> None:
        self._last_metrics = ToolExecutionMetrics()

    def set_runtime_deadline(self, deadline_at: float | None) -> None:
        self._runtime_deadline_at = deadline_at

    def clear_runtime_deadline(self) -> None:
        self._runtime_deadline_at = None

    def _remaining_timeout_seconds(self) -> float | None:
        if self._runtime_deadline_at is None:
            return None
        return max(self._runtime_deadline_at - self._clock(), 0.0)

    def _note(self, message: str) -> None:
        self._last_metrics.notes.append(message)

    def _call_with_optional_timeout(
        self,
        fn: Callable,
        *args,
        timeout_seconds: float | None = None,
        **kwargs,
    ):
        if timeout_seconds is None:
            return fn(*args, **kwargs)

        try:
            parameters = inspect.signature(fn).parameters.values()
        except (TypeError, ValueError):
            return fn(*args, **kwargs)

        accepts_timeout = any(parameter.name == "timeout_seconds" for parameter in parameters) or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters
        )
        if accepts_timeout:
            return fn(*args, timeout_seconds=timeout_seconds, **kwargs)
        return fn(*args, **kwargs)

    def _timed_fetch(
        self,
        metric_name: str,
        fn: Callable,
        *args,
        timeout_cap_seconds: float | None = None,
        **kwargs,
    ):
        remaining_timeout = self._remaining_timeout_seconds()
        if remaining_timeout is not None and remaining_timeout <= 0:
            message = "phase runtime deadline exceeded before external fetch"
            self._note(message)
            raise TimeoutError(message)

        effective_timeout = remaining_timeout
        if timeout_cap_seconds is not None:
            effective_timeout = timeout_cap_seconds if effective_timeout is None else min(
                effective_timeout,
                timeout_cap_seconds,
            )

        started_at = self._clock()
        try:
            return self._call_with_optional_timeout(
                fn,
                *args,
                timeout_seconds=effective_timeout,
                **kwargs,
            )
        finally:
            elapsed_ms = max(int((self._clock() - started_at) * 1000), 0)
            self._last_metrics.external_fetches += 1
            self._last_metrics.fetch_breakdown[metric_name] = (
                self._last_metrics.fetch_breakdown.get(metric_name, 0) + 1
            )
            self._last_metrics.timings_ms[metric_name] = self._last_metrics.timings_ms.get(metric_name, 0) + elapsed_ms

    def consume_last_metrics(self) -> ToolExecutionMetrics:
        metrics = ToolExecutionMetrics(
            external_fetches=self._last_metrics.external_fetches,
            fetch_breakdown=dict(self._last_metrics.fetch_breakdown),
            timings_ms=dict(self._last_metrics.timings_ms),
            notes=list(self._last_metrics.notes),
        )
        self._reset_metrics()
        return metrics

    def _search(self, query: str, max_results: int) -> list:
        cache_key = (query, max_results)
        if cache_key in self._search_cache:
            return list(self._search_cache[cache_key])
        hits = self._timed_fetch("search", self.search_client.search, query, max_results)
        self._search_cache[cache_key] = list(hits)
        return list(hits)

    def _clone_exception(self, error: Exception) -> Exception:
        try:
            return type(error)(*getattr(error, "args", ()))
        except Exception:
            return RuntimeError(str(error))

    def _extract_page(self, url: str, *, timeout_cap_seconds: float | None = None) -> PageData:
        cache_key = self._normalize_url(url)
        if cache_key in self._page_cache:
            return self._page_cache[cache_key]
        if cache_key in self._page_failure_cache:
            raise self._clone_exception(self._page_failure_cache[cache_key])
        try:
            page = self._timed_fetch(
                "page_extract",
                self.page_extractor.extract,
                url,
                timeout_cap_seconds=timeout_cap_seconds,
            )
        except Exception as exc:
            if not isinstance(exc, TimeoutError):
                self._page_failure_cache[cache_key] = self._clone_exception(exc)
            raise
        self._page_cache[cache_key] = page
        return page

    def _lookup_github(self, query: str) -> list[dict[str, str | int]]:
        if query in self._github_cache:
            return list(self._github_cache[query])
        hits = self._timed_fetch("github_lookup", self.github_signals.lookup, query)
        self._github_cache[query] = list(hits)
        return list(hits)

    def _search_or_empty(self, query: str, max_results: int, *, note_prefix: str) -> list:
        try:
            return self._search(query=query, max_results=max_results)
        except Exception as exc:
            self._note(f"{note_prefix} failed: {exc}")
            return []

    def _github_or_empty(self, query: str, *, note_prefix: str) -> list[dict[str, str | int]]:
        try:
            return self._lookup_github(query)
        except Exception as exc:
            self._note(f"{note_prefix} failed: {exc}")
            return []

    def _is_docs_like(self, url: str) -> bool:
        parsed = urlparse(url)
        domain = parsed.netloc.removeprefix("www.").lower()
        segments = [segment.lower() for segment in parsed.path.split("/") if segment]
        if any(domain.startswith(prefix) for prefix in ("docs.", "blog.", "help.", "news.", "community.")):
            return True
        return bool(segments and segments[0] in {"docs", "blog", "help", "news", "changelog", "learn"})

    def _is_article_like(self, url: str) -> bool:
        parsed = urlparse(url)
        domain = parsed.netloc.removeprefix("www.").lower()
        segments = {segment.lower() for segment in parsed.path.split("/") if segment}
        if domain in {"medium.com", "dev.to", "substack.com"}:
            return True
        return bool(
            {
                "article",
                "articles",
                "comparison",
                "comparisons",
                "news",
                "ranking",
                "rankings",
                "research",
                "resource",
                "resources",
                "review",
                "reviews",
            }
            & segments
        )

    def _safe_precheck_url(self, url: str) -> tuple[str, str]:
        try:
            page = self._extract_page(url, timeout_cap_seconds=self.URL_PRECHECK_TIMEOUT_CAP_SECONDS)
        except Exception as exc:
            self._note(f"url precheck failed for {url}: {exc}")
            return "failed", url
        return "ok", page.url

    def _github_activity_score(self, candidate: dict[str, str | int]) -> tuple:
        latest_release_tag = str(candidate.get("latest_release_tag", ""))
        latest_commit_at = str(candidate.get("latest_commit_at", ""))
        updated_at = str(candidate.get("updated_at", ""))
        return (
            0 if latest_release_tag else 1,
            0 if latest_commit_at or updated_at else 1,
            -int(candidate.get("stars", 0)),
        )

    def _candidate_rank_key(self, candidate: dict[str, str | int]) -> tuple:
        url = str(candidate["canonical_url"])
        parsed = urlparse(url)
        depth = len([segment for segment in parsed.path.split("/") if segment])
        source = str(candidate["source"])
        if source == "web":
            candidate_quality = candidate.get("candidate_quality", {})
            url_precheck = "skipped"
            if isinstance(candidate_quality, dict):
                url_precheck = str(candidate_quality.get("url_precheck", "skipped"))
            precheck_penalty = 0 if url_precheck == "ok" else 1
            return (0, precheck_penalty, 1 if self._is_docs_like(url) else 0, depth, str(candidate["name"]).lower())
        return (1, *self._github_activity_score(candidate), depth, str(candidate["name"]).lower())

    def search_competitor_candidates(
        self,
        target: str,
        hypothesis: str,
        source_mix: list[str],
        max_results: int = 5,
    ) -> list[dict[str, str]]:
        self._reset_metrics()
        candidates: list[dict[str, str | int]] = []
        source_set = set(source_mix)
        seen_urls: set[str] = set()
        seen_web_identities: set[str] = set()
        web_candidates_by_identity: dict[str, dict[str, str | int]] = {}

        if "web" in source_set:
            def merge_web_hits(hits) -> bool:
                accepted_any = False
                for hit in hits:
                    normalized_url = self._normalize_url(hit.url)
                    if self._is_article_like(normalized_url):
                        continue
                    domain = urlparse(normalized_url).netloc
                    domain_root = self._domain_identity(normalized_url)
                    precheck_status, resolved_url = self._safe_precheck_url(normalized_url)
                    if precheck_status != "ok" and self._is_docs_like(normalized_url):
                        continue
                    candidate = {
                        "candidate_id": "",
                        "name": hit.title or domain or "candidate",
                        "canonical_url": normalized_url,
                        "why_candidate": hit.snippet,
                        "source": "web",
                        "domain": domain,
                        "candidate_quality": {
                            "url_precheck": precheck_status,
                            "resolved_url": resolved_url,
                        },
                    }
                    if not domain_root:
                        if normalized_url in seen_urls:
                            continue
                        seen_urls.add(normalized_url)
                        candidates.append(candidate)
                        accepted_any = True
                        continue
                    seen_web_identities.add(domain_root)
                    previous = web_candidates_by_identity.get(domain_root)
                    if previous is None or self._candidate_rank_key(candidate) < self._candidate_rank_key(previous):
                        web_candidates_by_identity[domain_root] = candidate
                        accepted_any = True
                return accepted_any

            web_queries = [f"{target} competitor {hypothesis}"]
            fallback_query = hypothesis.strip()
            if fallback_query and fallback_query not in web_queries:
                web_queries.append(fallback_query)

            for query in web_queries:
                hits = self._search_or_empty(query=query, max_results=max_results, note_prefix="web search")
                if merge_web_hits(hits):
                    break

            for candidate in web_candidates_by_identity.values():
                normalized_url = str(candidate["canonical_url"])
                if normalized_url in seen_urls:
                    continue
                seen_urls.add(normalized_url)
                candidates.append(candidate)

        if "github" in source_set:
            query = f"{target} {hypothesis}"
            github_hits = self._github_or_empty(query=query, note_prefix="github lookup")
            for hit in github_hits[:max_results]:
                repo = str(hit.get("repo", ""))
                if not repo:
                    continue
                normalized_url = self._normalize_url(f"https://github.com/{repo}")
                if normalized_url in seen_urls:
                    continue
                repo_owner, repo_name = (repo.lower().split("/", 1) + [""])[:2]
                if repo_owner in seen_web_identities or repo_name in seen_web_identities:
                    continue
                seen_urls.add(normalized_url)
                candidates.append(
                    {
                        "candidate_id": "",
                        "name": repo,
                        "canonical_url": normalized_url,
                        "why_candidate": f"GitHub stars: {hit.get('stars', 0)}",
                        "source": "github",
                        "domain": "github.com",
                        "stars": int(hit.get("stars", 0)),
                        "updated_at": str(hit.get("updated_at", "")),
                        "latest_release_tag": str(hit.get("latest_release_tag", "")),
                        "latest_commit_at": str(hit.get("latest_commit_at", "")),
                    }
                )

        candidates.sort(key=self._candidate_rank_key)
        for index, candidate in enumerate(candidates, start=1):
            candidate["candidate_id"] = f"cand-{index}"
        return [dict(candidate) for candidate in candidates]

    def _evidence_from_page(self, subject: str, page: PageData, dimension: str) -> dict[str, str]:
        return {
            "subject": subject,
            "dimension": dimension,
            "source_url": page.url,
            "summary": page.text[:600],
            "page_title": page.title,
            "page_excerpt": page.excerpt,
        }

    def collect_positioning_evidence(self, subject: str, url: str) -> dict[str, str]:
        self._reset_metrics()
        page = self._extract_page(url)
        return self._evidence_from_page(subject=subject, page=page, dimension="positioning")

    def collect_workflow_evidence(self, subject: str, url: str) -> dict[str, str]:
        self._reset_metrics()
        page = self._extract_page(url)
        return self._evidence_from_page(subject=subject, page=page, dimension="workflow")

    def collect_pricing_access_evidence(self, subject: str, url: str) -> dict[str, str]:
        self._reset_metrics()
        page = self._extract_page(url)
        return self._evidence_from_page(subject=subject, page=page, dimension="pricing or access")

    def collect_github_ecosystem_signals(self, subject: str) -> list[dict[str, str | int]]:
        self._reset_metrics()
        return self._github_or_empty(subject, note_prefix="github ecosystem lookup")

    def _search_hits(self, subject: str, max_results: int) -> list:
        return self._search(query=subject, max_results=max_results)

    def _market_heat_from_hits(self, subject: str, search_hits, github_hits: list[dict[str, str | int]]) -> dict[str, object]:
        search = [
            {"title": hit.title, "url": self._normalize_url(hit.url), "snippet": hit.snippet}
            for hit in search_hits
        ]
        web_signals: list[dict[str, str]] = []
        for hit in search_hits:
            try:
                page = self._extract_page(hit.url)
                web_signals.append(
                    {
                        "source_url": page.url,
                        "title": hit.title,
                        "snippet": hit.snippet,
                        "page_title": page.title,
                        "page_excerpt": page.excerpt,
                    }
                )
            except Exception:
                web_signals.append(
                    {
                        "source_url": hit.url,
                        "title": hit.title,
                        "snippet": hit.snippet,
                        "page_title": hit.title,
                        "page_excerpt": "page extraction unavailable",
                    }
                )

        signal_count = len(web_signals) + len(github_hits)
        summary = f"{subject}: {search_hits[0].snippet}" if search_hits else f"{subject} has no search summary."
        return {
            "subject": subject,
            "summary": summary,
            "search": search,
            "web_signals": web_signals,
            "github": github_hits,
            "signal_count": signal_count,
        }

    def collect_market_heat_signals(self, subject: str, max_results: int = 3) -> dict[str, object]:
        self._reset_metrics()
        search_hits = self._search_or_empty(query=subject, max_results=max_results, note_prefix="market heat search")
        github_hits = self._github_or_empty(subject, note_prefix="market heat github lookup")
        return self._market_heat_from_hits(subject=subject, search_hits=search_hits, github_hits=github_hits)

    def _try_extract_from_hits(
        self,
        *,
        requested_url: str,
        hits,
        resolved_via: str,
        fallback_reason: str,
    ) -> tuple[PageData, dict[str, str]] | None:
        resolved_label = resolved_via.replace("_", " ")
        for hit in hits:
            if self._normalize_url(hit.url) == self._normalize_url(requested_url):
                continue
            try:
                page = self._extract_page(hit.url)
                self._note(f"{fallback_reason}; fallback to {resolved_label} {self._normalize_url(hit.url)}")
                return page, {
                    "requested_url": self._normalize_url(requested_url),
                    "resolved_url": page.url,
                    "resolved_via": resolved_via,
                    "fallback_reason": fallback_reason,
                }
            except Exception:
                continue
        return None

    def _clone_primary_resolution(
        self,
        resolution: tuple[PageData, dict[str, str]],
    ) -> tuple[PageData, dict[str, str]]:
        page, diagnostics = resolution
        return page, dict(diagnostics)

    def _resolve_primary_page(self, subject: str, url: str, search_hits) -> tuple[PageData, dict[str, str]]:
        cache_key = self._normalize_url(url)
        cached_resolution = self._primary_page_resolution_cache.get(cache_key)
        if cached_resolution is not None:
            return self._clone_primary_resolution(cached_resolution)
        try:
            page = self._extract_page(url)
            return page, {
                "requested_url": self._normalize_url(url),
                "resolved_url": page.url,
                "resolved_via": "primary",
                "fallback_reason": "",
            }
        except Exception as primary_error:
            fallback_reason = f"primary extract failed: {primary_error}"
            resolved = self._try_extract_from_hits(
                requested_url=url,
                hits=search_hits,
                resolved_via="search_hit",
                fallback_reason=fallback_reason,
            )
            if resolved is not None:
                self._primary_page_resolution_cache[cache_key] = self._clone_primary_resolution(resolved)
                return self._clone_primary_resolution(resolved)
            github_hits = self._search_or_empty(
                query=f"{subject} github",
                max_results=3,
                note_prefix="github focused fallback search",
            )
            resolved = self._try_extract_from_hits(
                requested_url=url,
                hits=github_hits,
                resolved_via="github_search_hit",
                fallback_reason=fallback_reason,
            )
            if resolved is not None:
                self._primary_page_resolution_cache[cache_key] = self._clone_primary_resolution(resolved)
                return self._clone_primary_resolution(resolved)
            raise primary_error

    def _pick_dimension_page(
        self,
        *,
        dimension: str,
        primary_page: PageData,
        search_hits,
    ) -> tuple[PageData, str]:
        if dimension == "positioning":
            return primary_page, "primary_url"

        keyword_map = {
            "workflow": (["docs", "documentation", "guide", "quickstart"], "workflow_search_hit"),
            "pricing or access": (["pricing", "plans", "billing"], "pricing_search_hit"),
        }
        keywords, source_label = keyword_map.get(dimension, ([], "search_hit"))
        primary_normalized_url = self._normalize_url(primary_page.url)

        for hit in search_hits:
            normalized_url = self._normalize_url(hit.url)
            if normalized_url == primary_normalized_url:
                continue
            lowered_url = normalized_url.lower()
            if not any(keyword in lowered_url for keyword in keywords):
                continue
            try:
                return self._extract_page(hit.url), source_label
            except Exception:
                continue

        return primary_page, "primary_url"

    def build_evidence_bundle(self, subject: str, url: str) -> dict[str, object]:
        self._reset_metrics()
        search_hits = self._search_or_empty(query=subject, max_results=3, note_prefix="subject search")
        primary_page, diagnostics = self._resolve_primary_page(subject=subject, url=url, search_hits=search_hits)
        positioning_page, positioning_source = self._pick_dimension_page(
            dimension="positioning",
            primary_page=primary_page,
            search_hits=search_hits,
        )
        workflow_page, workflow_source = self._pick_dimension_page(
            dimension="workflow",
            primary_page=primary_page,
            search_hits=search_hits,
        )
        pricing_page, pricing_source = self._pick_dimension_page(
            dimension="pricing or access",
            primary_page=primary_page,
            search_hits=search_hits,
        )
        github_hits = self._github_or_empty(subject, note_prefix="subject github lookup")
        diagnostics["dimension_sources"] = {
            "positioning": positioning_source,
            "workflow": workflow_source,
            "pricing_or_access": pricing_source,
        }
        return {
            "positioning": self._evidence_from_page(subject=subject, page=positioning_page, dimension="positioning"),
            "workflow": self._evidence_from_page(subject=subject, page=workflow_page, dimension="workflow"),
            "pricing_or_access": self._evidence_from_page(subject=subject, page=pricing_page, dimension="pricing or access"),
            "github": github_hits,
            "heat": self._market_heat_from_hits(subject=subject, search_hits=search_hits, github_hits=github_hits),
            "diagnostics": diagnostics,
        }
