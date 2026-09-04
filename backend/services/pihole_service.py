"""
Pi-hole integration — fetches and caches DNS stats from a Pi-hole v6 instance.

Authenticates via session-based auth (POST /api/auth) and polls summary stats.
"""
import logging
import time
from typing import Any, NoReturn, Optional

import httpx

logger = logging.getLogger("home_hub.pihole")

SUMMARY_CACHE_TTL = 60  # 1 minute
TOP_BLOCKED_CACHE_TTL = 120  # 2 minutes


class PiholeUnreachableError(Exception):
    """Pi-hole is down, re-authentication failed, or the API key is wrong.

    Distinct from "endpoint returned bad data" — callers should map this
    to a 503 (upstream unavailable) rather than a 500/502. The original
    exception (network error, HTTP error) is preserved as ``__cause__``.
    """


class PiholeService:
    """Cached Pi-hole v6 API client with session-based authentication."""

    def __init__(self, api_url: str, api_key: str) -> None:
        self._api_url = api_url.rstrip("/")
        self._password = api_key
        self._sid: Optional[str] = None
        self._csrf: Optional[str] = None

        # Summary cache
        self._summary_cache: Optional[dict[str, Any]] = None
        self._summary_cache_time: float = 0

        # Top blocked cache
        self._top_blocked_cache: Optional[list[dict[str, Any]]] = None
        self._top_blocked_cache_time: float = 0

        # Suppresses repeat ERROR-level logs while Pi-hole stays down.
        # Reset on the next successful request so a real outage→recovery
        # still leaves a clear pair of log lines.
        self._unreachable_logged: bool = False
        # Live/last-attempt reachability is separate from stale display cache.
        self._reachable: bool = False

    @property
    def connected(self) -> bool:
        """Whether the most recent Pi-hole request path is reachable."""
        return self._reachable

    async def _authenticate(self) -> bool:
        """Authenticate with Pi-hole and store session ID."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self._api_url}/api/auth",
                    json={"password": self._password},
                )
                resp.raise_for_status()
                data = resp.json()
                session = data.get("session", {})
                if session.get("valid"):
                    self._sid = session["sid"]
                    self._csrf = session.get("csrf")
                    logger.info("Pi-hole authenticated")
                    return True
                logger.error("Pi-hole auth response invalid: %s", data)
                return False
        except Exception as e:
            logger.error("Pi-hole auth failed: %s", e)
            return False

    def _auth_headers(self) -> dict[str, str]:
        """Build auth headers for authenticated requests."""
        headers: dict[str, str] = {}
        if self._sid:
            headers["X-FTL-SID"] = self._sid
        if self._csrf:
            headers["X-FTL-CSRF"] = self._csrf
        return headers

    def _raise_unreachable(
        self, message: str, cause: Optional[BaseException],
    ) -> NoReturn:
        """Log the root cause once, then raise ``PiholeUnreachableError``.

        While Pi-hole stays down every poll would otherwise spam the log
        with the same stack. We log at error level only on the transition
        from healthy → unreachable; subsequent failures log at debug
        until the next successful request flips ``_unreachable_logged``
        back to False.
        """
        self._reachable = False
        if not self._unreachable_logged:
            logger.error(
                "Pi-hole unreachable: %s%s",
                message,
                f" ({cause!r})" if cause is not None else "",
                exc_info=cause is not None,
            )
            self._unreachable_logged = True
        else:
            logger.debug("Pi-hole still unreachable: %s (%r)", message, cause)
        err = PiholeUnreachableError(message)
        if cause is not None:
            raise err from cause
        raise err

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
        parse_json: bool = True,
        request_timeout: float = 10.0,
    ) -> dict:
        """Make an authenticated request with 401 retry.

        Raises:
            PiholeUnreachableError: re-authentication failed, the retried
                request still returned 401 (bad credentials), or a
                network-level failure occurred. The original cause is
                attached via ``__cause__``.
        """
        if not self._sid:
            if not await self._authenticate():
                self._raise_unreachable(
                    "initial authentication failed", None,
                )

        try:
            async with httpx.AsyncClient(timeout=request_timeout) as client:
                resp = await client.request(
                    method,
                    f"{self._api_url}{path}",
                    headers=self._auth_headers(),
                    params=params,
                    json=json_body,
                )

                # Session expired — re-authenticate and retry once.
                if resp.status_code == 401:
                    logger.info("Pi-hole session expired, re-authenticating")
                    if not await self._authenticate():
                        self._raise_unreachable(
                            "re-authentication failed after 401", None,
                        )
                    resp = await client.request(
                        method,
                        f"{self._api_url}{path}",
                        headers=self._auth_headers(),
                        params=params,
                        json=json_body,
                    )
                    # Persistent 401 after a successful re-auth means the
                    # credentials are wrong for this endpoint — fail loud
                    # rather than masking with raise_for_status's generic
                    # HTTPStatusError chain.
                    if resp.status_code == 401:
                        self._raise_unreachable(
                            "401 persisted after re-auth — check "
                            "PIHOLE_API_KEY",
                            None,
                        )

                resp.raise_for_status()
                self._reachable = True
                # Success — reset the rate-limit flag so the next outage
                # gets a fresh ERROR log instead of being swallowed.
                self._unreachable_logged = False
                # Some endpoints return empty body (204).
                if resp.status_code == 204 or not resp.content:
                    return {}
                if not parse_json:
                    return {"text": resp.text}
                return resp.json()

        except PiholeUnreachableError:
            raise
        except Exception as e:
            self._raise_unreachable(f"{method} {path} failed", e)
            return {}  # unreachable; satisfies type checker

    async def _get(self, path: str, params: Optional[dict] = None) -> dict:
        """Make an authenticated GET request.

        Raises :class:`PiholeUnreachableError` on hard failure (see
        :meth:`_request`). Returns the decoded JSON body on success.
        """
        return await self._request("GET", path, params=params)

    async def get_summary(self) -> Optional[dict[str, Any]]:
        """
        Get Pi-hole summary stats.

        Returns cached data if fresh (< 60s). On a fresh-fetch failure,
        falls back to whatever stale cache exists. With no cache to
        fall back on, propagates :class:`PiholeUnreachableError` so the
        route can return 503.

        Returns:
            Dict with total_queries, blocked, percent_blocked,
            domains_on_blocklist, status — or stale cache on transient
            failure.
        """
        now = time.time()
        if self._summary_cache and (now - self._summary_cache_time) < SUMMARY_CACHE_TTL:
            return self._summary_cache

        try:
            data = await self._get("/api/stats/summary")
        except PiholeUnreachableError:
            if self._summary_cache:
                return self._summary_cache
            raise

        queries = data.get("queries", {})
        gravity = data.get("gravity", {})
        clients = data.get("clients", {})

        summary = {
            "total_queries": queries.get("total", 0),
            "blocked": queries.get("blocked", 0),
            "percent_blocked": round(queries.get("percent_blocked", 0), 1),
            "unique_domains": queries.get("unique_domains", 0),
            "forwarded": queries.get("forwarded", 0),
            "cached": queries.get("cached", 0),
            "domains_on_blocklist": gravity.get("domains_being_blocked", 0),
            "active_clients": clients.get("active", 0),
            "total_clients": clients.get("total", 0),
            "status": "enabled" if queries.get("total", 0) >= 0 else "unknown",
        }

        self._summary_cache = summary
        self._summary_cache_time = now
        logger.info(
            "Pi-hole stats updated: %d queries, %.1f%% blocked",
            summary["total_queries"],
            summary["percent_blocked"],
        )
        return summary

    async def get_top_blocked(self, count: int = 10) -> Optional[list[dict[str, Any]]]:
        """
        Get the most frequently blocked domains.

        Returns cached data if fresh (< 120s). Falls back to stale cache
        on transient failure; propagates :class:`PiholeUnreachableError`
        when there's no cache to serve.
        """
        now = time.time()
        if (
            self._top_blocked_cache
            and (now - self._top_blocked_cache_time) < TOP_BLOCKED_CACHE_TTL
        ):
            return self._top_blocked_cache

        try:
            data = await self._get("/api/stats/top_blocked", params={"count": count})
        except PiholeUnreachableError:
            if self._top_blocked_cache:
                return self._top_blocked_cache
            raise

        # Pi-hole v6 returns {"top_blocked": [{"domain": "...", "count": N}, ...]}
        raw = data.get("top_blocked", [])
        if isinstance(raw, dict):
            # Some versions return {domain: count} mapping
            top = [{"domain": k, "count": v} for k, v in raw.items()]
        elif isinstance(raw, list):
            top = raw
        else:
            top = []

        self._top_blocked_cache = top
        self._top_blocked_cache_time = now
        return top

    # -----------------------------------------------------------------
    # Local DNS management
    # -----------------------------------------------------------------

    async def get_dns_hosts(self) -> list[dict[str, str]]:
        """Get all custom local DNS records.

        Raises :class:`PiholeUnreachableError` if Pi-hole is down.
        """
        data = await self._get("/api/config/dns/hosts")
        # Pi-hole v6 returns {"config": {"dns": {"hosts": [...]}}}
        # or may return the list directly depending on version
        hosts: Any = data
        if isinstance(data, dict):
            hosts = (
                data.get("config", {}).get("dns", {}).get("hosts", [])
                or data.get("hosts", [])
            )
        if not isinstance(hosts, list):
            return []

        result = []
        for entry in hosts:
            if isinstance(entry, str) and " " in entry:
                ip, hostname = entry.split(" ", 1)
                result.append({"ip": ip, "hostname": hostname})
            elif isinstance(entry, dict):
                result.append(entry)
        return result

    async def add_dns_host(self, ip: str, hostname: str) -> bool:
        """Add a local DNS record.

        Raises :class:`PiholeUnreachableError` if Pi-hole is down.
        Returns True on a successful API call.
        """
        encoded = f"{ip} {hostname}".replace(" ", "%20")
        await self._request("PUT", f"/api/config/dns/hosts/{encoded}")
        logger.info("Pi-hole DNS added: %s → %s", hostname, ip)
        return True

    async def delete_dns_host(self, ip: str, hostname: str) -> bool:
        """Delete a local DNS record.

        Raises :class:`PiholeUnreachableError` if Pi-hole is down.
        Returns True on a successful API call.
        """
        encoded = f"{ip} {hostname}".replace(" ", "%20")
        await self._request("DELETE", f"/api/config/dns/hosts/{encoded}")
        logger.info("Pi-hole DNS removed: %s → %s", hostname, ip)
        return True

    # -----------------------------------------------------------------
    # Blocklist management
    # -----------------------------------------------------------------

    async def get_blocklists(self) -> list[dict[str, Any]]:
        """Get all configured adlists.

        Raises :class:`PiholeUnreachableError` if Pi-hole is down.
        """
        data = await self._get("/api/lists")
        lists = data.get("lists", data) if isinstance(data, dict) else data
        if not isinstance(lists, list):
            return []
        return lists

    async def add_blocklist(self, address: str, enabled: bool = True) -> bool:
        """Add a blocklist URL.

        Raises :class:`PiholeUnreachableError` if Pi-hole is down.
        Returns True on a successful API call.
        """
        await self._request(
            "POST",
            "/api/lists",
            params={"type": "block"},
            json_body={"address": address, "enabled": enabled},
        )
        logger.info("Pi-hole blocklist added: %s", address)
        return True

    async def delete_blocklist(self, address: str) -> bool:
        """Remove a blocklist URL.

        Raises :class:`PiholeUnreachableError` if Pi-hole is down.
        Returns True on a successful API call.
        """
        encoded = address.replace("/", "%2F").replace(":", "%3A")
        await self._request("DELETE", f"/api/lists/{encoded}")
        logger.info("Pi-hole blocklist removed: %s", address)
        return True

    async def refresh_gravity(self) -> bool:
        """Fetch configured lists and atomically rebuild Pi-hole gravity.

        Pi-hole v6 returns a text progress stream for this action, so this
        intentionally bypasses JSON decoding while retaining the normal
        authentication/retry/error handling in :meth:`_request`.
        """
        await self._request(
            "POST",
            "/api/action/gravity",
            parse_json=False,
            request_timeout=300.0,
        )
        logger.info("Pi-hole gravity refresh completed")
        return True

    # -----------------------------------------------------------------
    # Allowlist management (exact-domain exceptions)
    # -----------------------------------------------------------------
    #
    # The bulk allowlist is an allow-type adlist (anudeepND) managed as an
    # antigravity source; these exact entries are the per-domain safety net
    # for one-off false positives (e.g. an email click-tracker a blocklist
    # caught). Pi-hole v6 exposes them at /api/domains/allow/exact.

    async def get_allow_domains(self) -> list[dict[str, Any]]:
        """Get all exact-allow domains.

        Raises :class:`PiholeUnreachableError` if Pi-hole is down.
        """
        data = await self._get("/api/domains/allow/exact")
        # Pi-hole v6 returns {"domains": [{"domain","enabled","comment",...}]}
        domains = data.get("domains", data) if isinstance(data, dict) else data
        if not isinstance(domains, list):
            return []
        return domains

    async def add_allow_domain(
        self, domain: str, comment: Optional[str] = None,
    ) -> bool:
        """Add an exact-allow domain (whitelist a single domain).

        Raises :class:`PiholeUnreachableError` if Pi-hole is down.
        Returns True on a successful API call.
        """
        body: dict[str, Any] = {"domain": domain, "enabled": True}
        if comment:
            body["comment"] = comment
        await self._request("POST", "/api/domains/allow/exact", json_body=body)
        logger.info("Pi-hole allowlist added: %s", domain)
        return True

    async def delete_allow_domain(self, domain: str) -> bool:
        """Remove an exact-allow domain.

        Raises :class:`PiholeUnreachableError` if Pi-hole is down.
        Returns True on a successful API call.
        """
        encoded = domain.replace("/", "%2F")
        await self._request("DELETE", f"/api/domains/allow/exact/{encoded}")
        logger.info("Pi-hole allowlist removed: %s", domain)
        return True
