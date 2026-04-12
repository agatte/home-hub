"""
Pi-hole integration — fetches and caches DNS stats from a Pi-hole v6 instance.

Authenticates via session-based auth (POST /api/auth) and polls summary stats.
"""
import logging
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger("home_hub.pihole")

SUMMARY_CACHE_TTL = 60  # 1 minute
TOP_BLOCKED_CACHE_TTL = 120  # 2 minutes


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

    @property
    def connected(self) -> bool:
        """True if we have successfully fetched data at least once."""
        return self._summary_cache is not None

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

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
    ) -> Optional[dict]:
        """Make an authenticated request with 401 retry."""
        if not self._sid:
            if not await self._authenticate():
                return None

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.request(
                    method,
                    f"{self._api_url}{path}",
                    headers=self._auth_headers(),
                    params=params,
                    json=json_body,
                )

                # Session expired — re-authenticate and retry once
                if resp.status_code == 401:
                    logger.info("Pi-hole session expired, re-authenticating")
                    if not await self._authenticate():
                        return None
                    resp = await client.request(
                        method,
                        f"{self._api_url}{path}",
                        headers=self._auth_headers(),
                        params=params,
                        json=json_body,
                    )

                resp.raise_for_status()
                # Some endpoints return empty body (204)
                if resp.status_code == 204 or not resp.content:
                    return {}
                return resp.json()

        except Exception as e:
            logger.error("Pi-hole API %s %s failed: %s", method, path, e)
            return None

    async def _get(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        """Make an authenticated GET request."""
        return await self._request("GET", path, params=params)

    async def get_summary(self) -> Optional[dict[str, Any]]:
        """
        Get Pi-hole summary stats.

        Returns cached data if fresh (< 60s). Otherwise fetches from
        the Pi-hole API.

        Returns:
            Dict with total_queries, blocked, percent_blocked,
            domains_on_blocklist, status — or None on failure.
        """
        now = time.time()
        if self._summary_cache and (now - self._summary_cache_time) < SUMMARY_CACHE_TTL:
            return self._summary_cache

        data = await self._get("/api/stats/summary")
        if data is None:
            if self._summary_cache:
                return self._summary_cache
            return None

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

        Returns cached data if fresh (< 120s).

        Returns:
            List of dicts with domain and count — or None on failure.
        """
        now = time.time()
        if (
            self._top_blocked_cache
            and (now - self._top_blocked_cache_time) < TOP_BLOCKED_CACHE_TTL
        ):
            return self._top_blocked_cache

        data = await self._get("/api/stats/top_blocked", params={"count": count})
        if data is None:
            if self._top_blocked_cache:
                return self._top_blocked_cache
            return None

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

    async def get_dns_hosts(self) -> Optional[list[dict[str, str]]]:
        """Get all custom local DNS records."""
        data = await self._get("/api/config/dns/hosts")
        if data is None:
            return None
        # Pi-hole v6 returns {"config": {"dns": {"hosts": [...]}}}
        # or may return the list directly depending on version
        hosts = data
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
        """Add a local DNS record. Returns True on success."""
        encoded = f"{ip} {hostname}".replace(" ", "%20")
        resp = await self._request("PUT", f"/api/config/dns/hosts/{encoded}")
        if resp is not None:
            logger.info("Pi-hole DNS added: %s → %s", hostname, ip)
            return True
        return False

    async def delete_dns_host(self, ip: str, hostname: str) -> bool:
        """Delete a local DNS record. Returns True on success."""
        encoded = f"{ip} {hostname}".replace(" ", "%20")
        resp = await self._request("DELETE", f"/api/config/dns/hosts/{encoded}")
        if resp is not None:
            logger.info("Pi-hole DNS removed: %s → %s", hostname, ip)
            return True
        return False

    # -----------------------------------------------------------------
    # Blocklist management
    # -----------------------------------------------------------------

    async def get_blocklists(self) -> Optional[list[dict[str, Any]]]:
        """Get all configured adlists."""
        data = await self._get("/api/lists")
        if data is None:
            return None
        lists = data.get("lists", data) if isinstance(data, dict) else data
        if not isinstance(lists, list):
            return []
        return lists

    async def add_blocklist(self, address: str, enabled: bool = True) -> bool:
        """Add a blocklist URL. Returns True on success."""
        resp = await self._request(
            "POST",
            "/api/lists",
            params={"type": "block"},
            json_body={"address": address, "enabled": enabled},
        )
        if resp is not None:
            logger.info("Pi-hole blocklist added: %s", address)
            return True
        return False

    async def delete_blocklist(self, address: str) -> bool:
        """Remove a blocklist URL. Returns True on success."""
        encoded = address.replace("/", "%2F").replace(":", "%3A")
        resp = await self._request("DELETE", f"/api/lists/{encoded}")
        if resp is not None:
            logger.info("Pi-hole blocklist removed: %s", address)
            return True
        return False
