"""Thin client for the U.S. Energy Information Administration (EIA) API v2.

Handles auth, pagination, retries, and error normalization. Endpoint-specific
queries (crude oil vs natural gas, regions, time ranges) are constructed in
`src/data/loader.py` — this file is a generic transport.

EIA API docs: https://www.eia.gov/opendata/documentation.php
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

EIA_API_V2_BASE: str = "https://api.eia.gov/v2"

# EIA's faceted endpoint returns up to 5000 rows per page. We auto-paginate.
PAGE_SIZE: int = 5000

# Polite retry/backoff for transient failures.
MAX_RETRIES: int = 3
INITIAL_BACKOFF_SECONDS: float = 1.0
HTTP_TIMEOUT_SECONDS: int = 30


class EIAClientError(Exception):
    """Raised when the EIA API returns an error or is unreachable after retries."""


class EIAClient:
    """Synchronous client for EIA API v2 faceted queries.

    Usage:
        client = EIAClient(api_key="...")
        rows = client.fetch_all(
            path="/petroleum/crd/crpdn/data/",
            params={
                "frequency": "monthly",
                "data[0]": "value",
                "facets[product][]": "EPC0",
                "facets[process][]": "FPF",
                "start": "2010-01",
            },
        )
    """

    def __init__(
        self, api_key: str, *, session: requests.Session | None = None
    ) -> None:
        if not api_key:
            raise ValueError("EIA API key is required")
        self._api_key = api_key
        self._session = session or requests.Session()

    def fetch_page(self, path: str, params: dict[str, Any], offset: int = 0) -> dict:
        """Fetch a single page from the EIA API. Returns the parsed JSON 'response' object.

        Caller is responsible for paginating; use `fetch_all` for the common case.
        """
        url = f"{EIA_API_V2_BASE}{path}"
        merged: dict[str, Any] = {
            "api_key": self._api_key,
            "offset": offset,
            "length": PAGE_SIZE,
            **params,
        }

        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._session.get(
                    url, params=merged, timeout=HTTP_TIMEOUT_SECONDS
                )
                resp.raise_for_status()
                payload = resp.json()
                # EIA wraps results under "response" with "data" being the list of rows.
                response_obj = payload.get("response")
                if response_obj is None:
                    # Some error envelopes nest the message at top level.
                    err_msg = (
                        payload.get("error") or "EIA API returned no 'response' field"
                    )
                    raise EIAClientError(f"{err_msg} (path={path})")
                return response_obj
            except (requests.RequestException, ValueError) as e:
                last_error = e
                # Exponential backoff. Don't retry 4xx auth/format errors.
                if isinstance(e, requests.HTTPError) and e.response is not None:
                    status = e.response.status_code
                    if 400 <= status < 500 and status != 429:
                        raise EIAClientError(
                            f"EIA API client error {status} on {path}: {e.response.text[:300]}"
                        ) from e
                if attempt < MAX_RETRIES:
                    sleep_for = INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1))
                    logger.warning(
                        "EIA fetch %s failed (attempt %d/%d): %s — retrying in %.1fs",
                        path,
                        attempt,
                        MAX_RETRIES,
                        e,
                        sleep_for,
                    )
                    time.sleep(sleep_for)

        raise EIAClientError(
            f"EIA API unreachable after {MAX_RETRIES} attempts (path={path}): {last_error}"
        ) from last_error

    def fetch_all(self, path: str, params: dict[str, Any]) -> list[dict]:
        """Fetch all pages of results, concatenated into a single list of row dicts.

        Stops when a page returns fewer rows than PAGE_SIZE (EIA's signal for end-of-data).
        """
        rows: list[dict] = []
        offset = 0
        while True:
            response_obj = self.fetch_page(path, params, offset=offset)
            page_rows: list[dict] = response_obj.get("data", []) or []
            rows.extend(page_rows)

            if len(page_rows) < PAGE_SIZE:
                break
            offset += PAGE_SIZE

            # Defensive cap so a misconfigured query can't loop forever.
            if offset > 200_000:
                logger.warning("EIA fetch_all hit safety cap of 200k rows on %s", path)
                break

        logger.info("EIA fetch_all %s → %d rows", path, len(rows))
        return rows
