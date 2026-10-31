"""Shared fixed-window limits for expensive public operations.

Reservations count attempts, including failed work. Mongo's unique _id index and
conditional atomic updates enforce limits across processes and restarts.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import logging
import os
import hmac
import ipaddress

from fastapi import HTTPException, Request
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from .database import usage_collection


def configured_limit(name, default):
    try:
        value = int(os.getenv(name, str(default)))
        if value < 0:
            raise ValueError
        return value
    except ValueError as exc:
        raise HTTPException(503, "Live usage limits are not configured correctly.",
                            headers={"X-Error-Code": "usage_unavailable"}) from exc


class UsageLimiter:
    def __init__(self, collection):
        self.collection = collection
        self.index_ready = False

    async def reserve(self, cost=1, now=None, *, visitor_key=None, submission=False):
        if cost < 1:
            raise ValueError("Reservation cost must be positive")
        minute_limit = configured_limit("LIVE_REQUESTS_PER_MINUTE", 12)
        daily_limit = configured_limit("LIVE_REQUESTS_PER_DAY", 100)
        now = now or datetime.now(timezone.utc)
        minute = now.replace(second=0, microsecond=0)
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        windows = []
        if visitor_key is not None:
            # Visitors are checked before shared counters, so blocked visitors
            # cannot continue consuming everybody else's allowance.
            scopes = []
            if submission:
                scopes.append((f"submission:{visitor_key}", "submission", "VISITOR_SUBMISSIONS", 2, 5))
            scopes.append((f"visitor:{visitor_key}", "visitor", "VISITOR_REQUESTS", 4, 20))
            for scope, code, setting, per_minute, per_day in scopes:
                windows.extend([
                    (scope, f"{code}_minute", minute, minute + timedelta(minutes=1),
                     configured_limit(f"{setting}_PER_MINUTE", per_minute),
                     "This network has reached its short-term " + ("submission/retry" if code == "submission" else "live request") + " limit. Please try again shortly."),
                    (scope, f"{code}_day", day, day + timedelta(days=1),
                     configured_limit(f"{setting}_PER_DAY", per_day),
                     "This network has used today's " + ("submission/retry" if code == "submission" else "live request") + " allowance. Try again after midnight UTC."),
                ])
        windows.extend([
            ("global", "minute", minute, minute + timedelta(minutes=1), minute_limit,
             "Live requests are busy. Please try again shortly."),
            ("global", "day", day, day + timedelta(days=1), daily_limit,
             "Today's live allowance is used up. Explore the demo or try again after midnight UTC."),
        ])
        try:
            # Include index initialization and both reservations in one deadline.
            async with asyncio.timeout(5):
                if not self.index_ready:
                    await self.collection.create_index("expires_at", expireAfterSeconds=0)
                    self.index_ready = True
                for scope, label, start, end, limit, message in windows:
                    remaining_seconds = max(1, int((end - now).total_seconds()) + 1)
                    headers = {"Retry-After": str(remaining_seconds),
                               "X-Error-Code": f"{label}_limit"}
                    if cost > limit:
                        raise HTTPException(429, message, headers=headers)
                    query = {"_id": f"{scope}:{label}:{start.isoformat()}",
                             "count": {"$lte": limit - cost}}
                    update = {"$inc": {"count": cost},
                              "$setOnInsert": {"expires_at": end + timedelta(days=1)}}
                    try:
                        reservation = await self.collection.find_one_and_update(
                            query, update, upsert=True, return_document=ReturnDocument.AFTER,
                        )
                    except DuplicateKeyError:
                        # A competing initial insert may still leave capacity.
                        # Retry only the conditional update; never exceed the cap.
                        reservation = await self.collection.find_one_and_update(
                            query, update, upsert=False, return_document=ReturnDocument.AFTER,
                        )
                    if reservation is None:
                        raise HTTPException(429, message, headers=headers)
        except (PyMongoError, TimeoutError) as exc:
            logging.getLogger(__name__).warning("Usage reservation failed (%s)", type(exc).__name__)
            raise HTTPException(503, "Live requests are temporarily unavailable. Explore the demo or try again later.",
                                headers={"X-Error-Code": "usage_unavailable"}) from exc


limiter = UsageLimiter(usage_collection)


def visitor_key(request: Request):
    """Only trust the platform's forwarded IP on Vercel; never store raw IPs."""
    secret = os.getenv('VISITOR_RATE_LIMIT_SECRET') or os.getenv('RESOURCE_ADMIN_TOKEN')
    if not secret:
        raise HTTPException(503, 'Visitor usage limits are not configured.',
                            headers={'X-Error-Code': 'usage_unavailable'})
    if os.getenv('VERCEL') == '1':
        # Vercel overwrites this header. Never fall back to client-supplied XFF.
        address = request.headers.get('x-vercel-forwarded-for', '')
        try:
            ip = ipaddress.ip_address(address.strip())
        except ValueError:
            raise HTTPException(503, 'Visitor usage limits are temporarily unavailable.',
                                headers={'X-Error-Code': 'usage_unavailable'}) from None
    else:
        address = request.client.host if request.client else ''
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            # Non-IP transports share one conservative bucket; headers cannot
            # choose another identity. Normal direct deployments use the peer IP.
            ip = None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    identity = (str(ipaddress.ip_network(f'{ip}/64', strict=False))
                if isinstance(ip, ipaddress.IPv6Address) else str(ip or 'unknown-peer'))
    return hmac.new(secret.encode(), f'visitor-limits:v1:{identity}'.encode(), 'sha256').hexdigest()


async def reserve_request(request: Request):
    submission = request.url.path.endswith(('/upload', '/resources', '/retry'))
    await limiter.reserve(visitor_key=visitor_key(request), submission=submission)
