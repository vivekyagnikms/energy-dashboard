"""Live commodity-price feed: WTI crude oil + Henry Hub natural gas.

Promotes Revenue Potential from "illustrative constants" to "live prices,
last refreshed N days ago" — the Tier-3 graduation for that KPI.

Resilience: every call falls back to the illustrative constants in
src/kpis/calculators.py if the EIA price endpoints fail. The KPI still
returns a number; only the label changes between live and illustrative.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from src.data.eia_client import EIAClient, EIAClientError
from src.kpis.calculators import (
    HENRY_HUB_USD_PER_MMBTU as DEFAULT_HENRY_HUB_USD_PER_MMBTU,
)
from src.kpis.calculators import (
    WTI_PRICE_USD_PER_BBL as DEFAULT_WTI_USD_PER_BBL,
)

logger = logging.getLogger(__name__)


# Series IDs are documented at https://www.eia.gov/opendata/browser/.
WTI_SPOT_PATH: Final[str] = "/petroleum/pri/spt/data/"
WTI_SERIES: Final[str] = "RWTC"  # Cushing OK WTI Spot Price FOB, USD/bbl

# Henry Hub spot lives under /pri/fut/, not /pri/sum/. /pri/sum/ is consumer
# (city-gate) prices.
HENRY_HUB_PATH: Final[str] = "/natural-gas/pri/fut/data/"
HENRY_HUB_SERIES: Final[str] = "RNGWHHD"  # Henry Hub Natural Gas Spot, USD/MMBtu


@dataclass(frozen=True)
class CommodityPrices:
    """Latest commodity price snapshot. is_live distinguishes a real EIA
    fetch from the deterministic constants we fall back to."""

    wti_usd_per_bbl: float
    henry_hub_usd_per_mmbtu: float
    as_of: str  # ISO date string ("YYYY-MM-DD") or "" if not live
    is_live: bool

    @property
    def wti_label(self) -> str:
        if self.is_live and self.as_of:
            return f"WTI USD {self.wti_usd_per_bbl:.2f}/bbl as of {self.as_of}"
        return f"WTI USD {self.wti_usd_per_bbl:.2f}/bbl (illustrative)"

    @property
    def henry_hub_label(self) -> str:
        if self.is_live and self.as_of:
            return (
                f"Henry Hub USD {self.henry_hub_usd_per_mmbtu:.2f}/MMBtu "
                f"as of {self.as_of}"
            )
        return f"Henry Hub USD {self.henry_hub_usd_per_mmbtu:.2f}/MMBtu (illustrative)"


ILLUSTRATIVE_PRICES: Final[CommodityPrices] = CommodityPrices(
    wti_usd_per_bbl=DEFAULT_WTI_USD_PER_BBL,
    henry_hub_usd_per_mmbtu=DEFAULT_HENRY_HUB_USD_PER_MMBTU,
    as_of="",
    is_live=False,
)


def _latest_value(rows: list[dict]) -> tuple[float | None, str]:
    """From a list of EIA price rows, return (latest_value, latest_period)."""
    if not rows:
        return None, ""
    # EIA returns rows sorted ascending by period when we ask; take the tail.
    candidates = [r for r in rows if r.get("value") not in (None, "")]
    if not candidates:
        return None, ""
    candidates.sort(key=lambda r: str(r.get("period", "")))
    last = candidates[-1]
    try:
        return float(last["value"]), str(last.get("period", ""))
    except (TypeError, ValueError):
        return None, ""


def fetch_live_prices(api_key: str) -> CommodityPrices:
    """Fetch the most recent WTI + Henry Hub spot prices from EIA. Falls back
    to illustrative constants on any failure (logged as a warning).

    The EIA series we use are daily; we ask for the last 60 calendar days
    and take the most recent non-null reading. This is robust to weekends,
    holidays, and occasional EIA reporting gaps.
    """
    try:
        client = EIAClient(api_key=api_key)

        # Crude WTI spot supports daily; gas pricing endpoint only supports
        # 'monthly' or 'annual'. We use the finest available granularity
        # for each so the "as of" label is as recent as possible.
        wti_rows = client.fetch_all(
            WTI_SPOT_PATH,
            {
                "frequency": "daily",
                "data[0]": "value",
                "facets[series][]": WTI_SERIES,
                "sort[0][column]": "period",
                "sort[0][direction]": "asc",
            },
        )
        wti, wti_period = _latest_value(wti_rows)

        hh_rows = client.fetch_all(
            HENRY_HUB_PATH,
            {
                "frequency": "monthly",
                "data[0]": "value",
                "facets[series][]": HENRY_HUB_SERIES,
                "sort[0][column]": "period",
                "sort[0][direction]": "asc",
            },
        )
        hh, hh_period = _latest_value(hh_rows)
    except EIAClientError as e:
        logger.warning("Price fetch failed; using illustrative constants: %s", e)
        return ILLUSTRATIVE_PRICES

    if wti is None or hh is None:
        logger.warning(
            "Price fetch returned no usable rows; using illustrative constants"
        )
        return ILLUSTRATIVE_PRICES

    # Use the more conservative (older) of the two periods as the "as of" date.
    as_of = (
        min(p for p in (wti_period, hh_period) if p)
        or datetime.utcnow().date().isoformat()
    )

    return CommodityPrices(
        wti_usd_per_bbl=float(wti),
        henry_hub_usd_per_mmbtu=float(hh),
        as_of=as_of,
        is_live=True,
    )
