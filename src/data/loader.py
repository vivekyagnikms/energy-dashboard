"""Production-data loader: fetch from EIA, normalize to annual, cache.

Public API:
    load_production_data(api_key, *, force_refresh=False, start_year=2010)
        -> pd.DataFrame with the canonical schema (see schema.py: ANNUAL_COLUMNS).

Resilience layers (outer to inner):
    1. Live cache (parquet, 24h TTL) at data/cache/
    2. Live EIA API
    3. Committed seed snapshot at data/seed/
"""

from __future__ import annotations

import logging
from typing import Final

import pandas as pd

from src.data.eia_client import EIAClient, EIAClientError
from src.data.regions import REGIONS_BY_CODE
from src.data.schema import ANNUAL_COLUMNS, Product
from src.utils.cache import (
    cache_path,
    is_fresh,
    load_seed,
    read_parquet,
    write_parquet,
    write_seed,
)

logger = logging.getLogger(__name__)

CACHE_NAME: Final[str] = "production_annual"

# EIA endpoint + facet definitions per product.
# Faceted query parameters: see https://www.eia.gov/opendata/browser/
_QUERIES: Final[dict[str, dict]] = {
    Product.CRUDE_OIL: {
        "path": "/petroleum/crd/crpdn/data/",
        "facets": {
            # EPC0 = crude oil; FPF = field production.
            "facets[product][]": "EPC0",
            "facets[process][]": "FPF",
        },
        # Crude returns two rows per (area, period): MBBL (monthly total) and
        # MBBL/D (daily average). We sum monthly totals to get annual production,
        # so we keep MBBL and discard MBBL/D.
        "target_unit": "MBBL",
    },
    Product.NATURAL_GAS: {
        "path": "/natural-gas/prod/sum/data/",
        "facets": {
            # VGM = marketed natural gas production (the standard production figure).
            "facets[process][]": "VGM",
        },
        "target_unit": "MMCF",
    },
}


def _build_params(query: dict, start_year: int) -> dict[str, str]:
    """Compose the query string for a single product fetch."""
    return {
        "frequency": "monthly",
        "data[0]": "value",
        "start": f"{start_year}-01",
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        **query["facets"],
    }


def _fetch_product(client: EIAClient, product: str, start_year: int) -> list[dict]:
    """Fetch monthly rows from EIA for a single product across all areas."""
    query = _QUERIES[product]
    params = _build_params(query, start_year)
    return client.fetch_all(query["path"], params)


def _normalize_rows(rows: list[dict], product: str) -> pd.DataFrame:
    """Convert raw EIA monthly rows into our canonical annual DataFrame.

    Aggregation: sum monthly `value` within each (region_code, year). Monthly
    counts are tracked so the UI can flag partial years.

    Per-product unit filter applied here: crude returns both MBBL and MBBL/D
    rows for the same period; we keep only the monthly-total unit.
    """
    if not rows:
        return pd.DataFrame(columns=list(ANNUAL_COLUMNS))

    df = pd.DataFrame(rows)

    required = {"duoarea", "period", "value", "units"}
    if not required.issubset(df.columns):
        raise ValueError(
            f"EIA response missing expected columns; got {sorted(df.columns)}, "
            f"need at least {sorted(required)}"
        )

    # Filter to the canonical unit for this product (drops daily-average duplicates).
    target_unit = _QUERIES[product]["target_unit"]
    df = df[df["units"].astype(str).str.upper() == target_unit.upper()].copy()
    if df.empty:
        return pd.DataFrame(columns=list(ANNUAL_COLUMNS))

    # Coerce types.
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    df["year"] = pd.to_numeric(df["period"].str.slice(0, 4), errors="coerce").astype(
        "Int64"
    )
    df = df.dropna(subset=["year"])
    df["year"] = df["year"].astype(int)

    # Aggregate monthly → annual.
    grouped = df.groupby(["duoarea", "year"], as_index=False).agg(
        value=("value", "sum"), n_months=("value", "size")
    )

    # Filter to regions we know about (drops EIA aggregates we haven't mapped).
    grouped = grouped[grouped["duoarea"].isin(REGIONS_BY_CODE)].copy()

    grouped["region_code"] = grouped["duoarea"]
    grouped["region_name"] = grouped["region_code"].map(
        lambda c: REGIONS_BY_CODE[c].name
    )
    grouped["product"] = product
    grouped["unit"] = target_unit
    grouped = grouped[list(ANNUAL_COLUMNS)]

    return grouped


def _fetch_and_normalize(api_key: str, start_year: int) -> pd.DataFrame:
    """Hit EIA for both products and return the combined annual DataFrame."""
    client = EIAClient(api_key=api_key)
    frames: list[pd.DataFrame] = []
    for product in (Product.CRUDE_OIL, Product.NATURAL_GAS):
        rows = _fetch_product(client, product, start_year)
        df = _normalize_rows(rows, product)
        logger.info("Loaded %d annual rows for %s", len(df), product)
        frames.append(df)
    combined = pd.concat(frames, ignore_index=True)
    return combined.sort_values(["product", "region_code", "year"]).reset_index(
        drop=True
    )


def load_production_data(
    api_key: str,
    *,
    force_refresh: bool = False,
    start_year: int = 2010,
) -> pd.DataFrame:
    """Return annual production data with the canonical schema.

    Resolution order:
      1. Live parquet cache (if fresh and not forced)
      2. EIA API (with retries) → write to live cache + return
      3. Committed seed snapshot (if API fails) → return with warning logged

    Raises EIAClientError only if all three layers fail.
    """
    path = cache_path(CACHE_NAME)

    if not force_refresh and is_fresh(path):
        cached = read_parquet(path)
        if cached is not None and not cached.empty:
            logger.info("Loaded %d rows from live cache: %s", len(cached), path)
            return cached

    try:
        df = _fetch_and_normalize(api_key, start_year)
        if not df.empty:
            write_parquet(df, path)
            return df
        logger.warning("EIA fetch returned no rows; falling back to seed")
    except EIAClientError as e:
        logger.error("EIA fetch failed; falling back to seed: %s", e)

    seed = load_seed()
    if seed is not None and not seed.empty:
        logger.warning("Serving seed snapshot (live data unavailable)")
        return seed

    raise EIAClientError(
        "Production data unavailable: live API failed and no seed snapshot present"
    )


def refresh_seed(api_key: str, *, start_year: int = 2010) -> pd.DataFrame:
    """Force a live fetch and persist the result as both the seed snapshot
    and the live cache. Run during build (or when refreshing the bundled
    fallback) to keep data/seed/ and data/cache/ in sync.
    """
    df = _fetch_and_normalize(api_key, start_year)
    write_seed(df)
    write_parquet(df, cache_path(CACHE_NAME))
    logger.info("Wrote seed + live cache: %d rows", len(df))
    return df
