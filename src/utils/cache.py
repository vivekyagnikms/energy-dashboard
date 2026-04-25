"""Parquet-backed cache for EIA production data.

Two layers:
- Live cache at `data/cache/` — refreshed from API, gitignored.
- Seed snapshot at `data/seed/eia_snapshot.parquet` — committed to repo, used as
  fallback when the API is unreachable so the demo never hard-fails.
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

# 24-hour TTL: production data updates monthly, so a daily refresh is plenty fresh.
DEFAULT_TTL_SECONDS: int = 24 * 60 * 60

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = REPO_ROOT / "data" / "cache"
SEED_DIR = REPO_ROOT / "data" / "seed"
SEED_FILE = SEED_DIR / "eia_snapshot.parquet"


def cache_path(name: str) -> Path:
    """Resolve a cache file path under data/cache/, creating the dir if missing."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{name}.parquet"


def is_fresh(path: Path, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> bool:
    """True if the cache file exists and was modified within the TTL."""
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < ttl_seconds


def read_parquet(path: Path) -> pd.DataFrame | None:
    """Read a parquet file. Returns None if the file is missing or unreadable."""
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except (OSError, ValueError):
        # Corrupt or partial file — treat as cache miss; caller will refetch.
        return None


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Atomic-ish parquet write. Writes to a temp file, then renames."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


def load_seed() -> pd.DataFrame | None:
    """Read the committed seed snapshot. Returns None if not present yet."""
    return read_parquet(SEED_FILE)


def write_seed(df: pd.DataFrame) -> None:
    """Persist a fresh fetch as the committed seed snapshot.
    Called once during build to populate the fallback dataset.
    """
    write_parquet(df, SEED_FILE)
