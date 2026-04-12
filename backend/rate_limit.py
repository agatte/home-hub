"""
Rate limiter instance — shared across all route modules.

Default: 120 requests/minute per client IP. Individual routes can
apply stricter limits via @limiter.limit("10/minute").
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
