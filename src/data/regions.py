"""Region definitions for U.S. oil & gas production analysis.

Maps EIA "duoarea" codes (the API's region identifier) to display names,
groupings, and sort priorities. Centralized here so the UI selector,
loader, and AI layer share one source of truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RegionGroup(str, Enum):
    NATIONAL = "National"
    OFFSHORE = "Federal Offshore"
    PADD = "PADD (Petroleum Administration for Defense District)"
    STATE = "State"


@dataclass(frozen=True)
class Region:
    code: str          # EIA duoarea code (e.g. "NUS", "SAL", "R10")
    name: str          # Display name (e.g. "United States", "Alabama", "PADD 1 East Coast")
    group: RegionGroup
    sort_priority: int  # Lower = appears earlier in selectors. National=0, Offshore=10, PADD=20, States=30+.


# --- National total ---
US_NATIONAL = Region("NUS", "United States", RegionGroup.NATIONAL, 0)

# --- Federal Offshore (significant producer; reported separately by EIA) ---
FEDERAL_OFFSHORE_GOM = Region("R3FM", "Federal Offshore Gulf of Mexico", RegionGroup.OFFSHORE, 10)

# --- PADDs ---
# Petroleum Administration for Defense Districts — industry-standard regional groupings.
PADDS: tuple[Region, ...] = (
    Region("R10", "PADD 1 East Coast",       RegionGroup.PADD, 20),
    Region("R20", "PADD 2 Midwest",          RegionGroup.PADD, 21),
    Region("R30", "PADD 3 Gulf Coast",       RegionGroup.PADD, 22),
    Region("R40", "PADD 4 Rocky Mountain",   RegionGroup.PADD, 23),
    Region("R50", "PADD 5 West Coast",       RegionGroup.PADD, 24),
)

# --- States ---
# EIA uses "S" + 2-letter postal code for state duoarea codes (e.g. "STX" = Texas).
# We include all 50 states + DC. States with no oil/gas production are still listed;
# the UI surfaces a clean "no production" message rather than hiding them.
_STATE_ABBREVS: tuple[tuple[str, str], ...] = (
    ("AL", "Alabama"), ("AK", "Alaska"), ("AZ", "Arizona"), ("AR", "Arkansas"),
    ("CA", "California"), ("CO", "Colorado"), ("CT", "Connecticut"), ("DE", "Delaware"),
    ("DC", "District of Columbia"), ("FL", "Florida"), ("GA", "Georgia"), ("HI", "Hawaii"),
    ("ID", "Idaho"), ("IL", "Illinois"), ("IN", "Indiana"), ("IA", "Iowa"),
    ("KS", "Kansas"), ("KY", "Kentucky"), ("LA", "Louisiana"), ("ME", "Maine"),
    ("MD", "Maryland"), ("MA", "Massachusetts"), ("MI", "Michigan"), ("MN", "Minnesota"),
    ("MS", "Mississippi"), ("MO", "Missouri"), ("MT", "Montana"), ("NE", "Nebraska"),
    ("NV", "Nevada"), ("NH", "New Hampshire"), ("NJ", "New Jersey"), ("NM", "New Mexico"),
    ("NY", "New York"), ("NC", "North Carolina"), ("ND", "North Dakota"), ("OH", "Ohio"),
    ("OK", "Oklahoma"), ("OR", "Oregon"), ("PA", "Pennsylvania"), ("RI", "Rhode Island"),
    ("SC", "South Carolina"), ("SD", "South Dakota"), ("TN", "Tennessee"), ("TX", "Texas"),
    ("UT", "Utah"), ("VT", "Vermont"), ("VA", "Virginia"), ("WA", "Washington"),
    ("WV", "West Virginia"), ("WI", "Wisconsin"), ("WY", "Wyoming"),
)

STATES: tuple[Region, ...] = tuple(
    Region(code=f"S{abbr}", name=name, group=RegionGroup.STATE, sort_priority=30)
    for abbr, name in _STATE_ABBREVS
)

# --- Master registry ---
ALL_REGIONS: tuple[Region, ...] = (US_NATIONAL, FEDERAL_OFFSHORE_GOM, *PADDS, *STATES)

# Keyed lookup. Code → Region.
REGIONS_BY_CODE: dict[str, Region] = {r.code: r for r in ALL_REGIONS}

# Keyed lookup. Display name → Region.
REGIONS_BY_NAME: dict[str, Region] = {r.name: r for r in ALL_REGIONS}


def get_region(code_or_name: str) -> Region | None:
    """Resolve a region by EIA code or display name. Returns None if not found."""
    return REGIONS_BY_CODE.get(code_or_name) or REGIONS_BY_NAME.get(code_or_name)
