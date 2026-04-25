"""Function-calling tools the AI can invoke during a chat turn.

Design:
- Every tool has (a) a Gemini FunctionDeclaration, (b) a Pydantic input
  model, and (c) a Python implementation. The chat loop validates inputs
  via Pydantic, executes the implementation, returns typed JSON-serializable
  output.
- Tool outputs are dataclasses-as-dicts; the chat layer cross-checks any
  numbers in the LLM's final response against the values these tools
  actually returned.
- Anomaly detection is performed STATISTICALLY here. The LLM cannot
  decide what is anomalous — it can only explain flagged years.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

import pandas as pd
from google.genai import types as genai_types
from pydantic import BaseModel, Field, ValidationError, field_validator

from src.data.regions import ALL_REGIONS, REGIONS_BY_CODE, REGIONS_BY_NAME, RegionGroup
from src.data.schema import PRODUCTS, Product
from src.forecast.engine import ForecastEngine
from src.kpis.calculators import compute_kpi_set, get_actual_or_forecast

logger = logging.getLogger(__name__)


# ============================================================
# Region resolution
# ============================================================


def resolve_region_code(value: str) -> str | None:
    """Map a user-provided string to a canonical EIA duoarea code.
    Accepts: full code (NUS, STX), region name (Texas), 2-letter state abbr (TX),
    or 'PADD N' / 'P N' / 'padd-n' shorthand. Returns None if unresolvable."""
    if not value:
        return None
    s = value.strip()
    if s in REGIONS_BY_CODE:
        return s
    name_match = REGIONS_BY_NAME.get(s)
    if name_match:
        return name_match.code
    # Case-insensitive name lookup.
    s_lower = s.lower()
    for r in ALL_REGIONS:
        if r.name.lower() == s_lower:
            return r.code
    # 2-letter state abbreviation.
    if len(s) == 2 and s.upper().isalpha():
        candidate = f"S{s.upper()}"
        if candidate in REGIONS_BY_CODE:
            return candidate
    # 'US' / 'USA' / 'United States' / 'national'.
    if s_lower in {"us", "usa", "united states", "national", "nation"}:
        return "NUS"
    # Gulf of Mexico shorthand.
    if "gulf" in s_lower or "gom" in s_lower:
        return "R3FM"
    # PADD shorthand: 'PADD 3', 'PADD-3', 'PADD3', 'P3', 'P 3' -> R30.
    import re as _re

    m = _re.search(r"\bpadd[\s\-]*(\d)\b", s_lower)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 5:
            return f"R{n}0"
    m = _re.search(r"\bp[\s\-]*(\d)\b", s_lower)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 5:
            return f"R{n}0"
    return None


def resolve_product(value: str) -> str | None:
    """Accepts 'crude_oil', 'crude', 'oil', 'natural_gas', 'gas', 'ng'."""
    if not value:
        return None
    s = value.strip().lower().replace("-", "_").replace(" ", "_")
    if s in PRODUCTS:
        return s
    if s in {"crude", "oil", "petroleum", "crude_oil"}:
        return Product.CRUDE_OIL
    if s in {"gas", "ng", "natgas", "natural_gas", "naturalgas"}:
        return Product.NATURAL_GAS
    return None


# ============================================================
# Tool input models (Pydantic)
# ============================================================


class GetProductionInput(BaseModel):
    region: str = Field(description="Region name, EIA code, or 2-letter state abbr")
    product: str = Field(description="'crude_oil' or 'natural_gas'")
    year: int = Field(ge=1900, le=2100)

    @field_validator("product")
    @classmethod
    def _normalize_product(cls, v: str) -> str:
        norm = resolve_product(v)
        if norm is None:
            raise ValueError(f"unknown product {v!r}")
        return norm


class GetHistoryInput(BaseModel):
    region: str
    product: str
    start_year: int = Field(ge=1900, le=2100, default=2010)
    end_year: int = Field(ge=1900, le=2100, default=2030)

    @field_validator("product")
    @classmethod
    def _normalize_product(cls, v: str) -> str:
        norm = resolve_product(v)
        if norm is None:
            raise ValueError(f"unknown product {v!r}")
        return norm


class CompareRegionsInput(BaseModel):
    regions: list[str] = Field(min_length=2, max_length=5)
    product: str
    year: int = Field(ge=1900, le=2100)

    @field_validator("product")
    @classmethod
    def _normalize_product(cls, v: str) -> str:
        norm = resolve_product(v)
        if norm is None:
            raise ValueError(f"unknown product {v!r}")
        return norm


class GetKpisInput(BaseModel):
    region: str
    product: str
    year: int = Field(ge=1900, le=2100)

    @field_validator("product")
    @classmethod
    def _normalize_product(cls, v: str) -> str:
        norm = resolve_product(v)
        if norm is None:
            raise ValueError(f"unknown product {v!r}")
        return norm


class GetAnomaliesInput(BaseModel):
    region: str
    product: str
    z_threshold: float = Field(ge=1.0, le=5.0, default=2.5)

    @field_validator("product")
    @classmethod
    def _normalize_product(cls, v: str) -> str:
        norm = resolve_product(v)
        if norm is None:
            raise ValueError(f"unknown product {v!r}")
        return norm


class ListRegionsInput(BaseModel):
    group: str | None = Field(
        default=None,
        description="Optional filter: 'national', 'offshore', 'padd', 'state'.",
    )


# ============================================================
# Tool output dataclasses (typed, JSON-serializable)
# ============================================================


@dataclass(frozen=True)
class ToolResult:
    """Wrapper returned to the LLM. Always includes status so the LLM can
    react to errors gracefully without freelancing numbers."""

    ok: bool
    data: dict | list | None = None
    error: str | None = None
    notes: list[str] = field(default_factory=list)


# ============================================================
# Tool implementations (pure functions over df + engine)
# ============================================================


def _name_for(code: str) -> str:
    r = REGIONS_BY_CODE.get(code)
    return r.name if r else code


def get_production_impl(
    df: pd.DataFrame, engine: ForecastEngine, args: GetProductionInput
) -> ToolResult:
    code = resolve_region_code(args.region)
    if code is None:
        return ToolResult(ok=False, error=f"Unknown region: {args.region!r}")
    value, is_forecast = get_actual_or_forecast(
        df, engine, code, args.product, args.year
    )
    if value is None:
        return ToolResult(
            ok=False,
            error=(
                f"No production data for {_name_for(code)} ({args.product}) in {args.year}. "
                "This region likely does not produce this product, or the year is "
                "too far past the available data window."
            ),
        )
    unit = "MBBL" if args.product == Product.CRUDE_OIL else "MMCF"
    return ToolResult(
        ok=True,
        data={
            "region": _name_for(code),
            "region_code": code,
            "product": args.product,
            "year": args.year,
            "value": round(float(value), 2),
            "unit": unit,
            "is_forecast": bool(is_forecast),
        },
    )


def get_history_impl(
    df: pd.DataFrame, engine: ForecastEngine, args: GetHistoryInput
) -> ToolResult:
    code = resolve_region_code(args.region)
    if code is None:
        return ToolResult(ok=False, error=f"Unknown region: {args.region!r}")
    hist = engine.history(code, args.product)
    if hist.empty:
        return ToolResult(
            ok=False,
            error=f"{_name_for(code)} has no {args.product} production data.",
        )
    sub = hist[(hist["year"] >= args.start_year) & (hist["year"] <= args.end_year)]
    if sub.empty:
        return ToolResult(
            ok=False,
            error=(
                f"No {args.product} data for {_name_for(code)} between "
                f"{args.start_year} and {args.end_year}."
            ),
        )
    unit = "MBBL" if args.product == Product.CRUDE_OIL else "MMCF"
    return ToolResult(
        ok=True,
        data={
            "region": _name_for(code),
            "product": args.product,
            "unit": unit,
            "series": [
                {"year": int(y), "value": round(float(v), 2)}
                for y, v in zip(sub["year"], sub["value"])
            ],
        },
    )


def compare_regions_impl(
    df: pd.DataFrame, engine: ForecastEngine, args: CompareRegionsInput
) -> ToolResult:
    rows: list[dict] = []
    notes: list[str] = []
    for raw in args.regions:
        code = resolve_region_code(raw)
        if code is None:
            notes.append(f"unrecognized region {raw!r}; skipped")
            continue
        value, is_forecast = get_actual_or_forecast(
            df, engine, code, args.product, args.year
        )
        rows.append(
            {
                "region": _name_for(code),
                "region_code": code,
                "value": (round(float(value), 2) if value is not None else None),
                "is_forecast": bool(is_forecast) if value is not None else None,
                "available": value is not None,
            }
        )
    if not rows:
        return ToolResult(ok=False, error="No valid regions to compare.", notes=notes)
    unit = "MBBL" if args.product == Product.CRUDE_OIL else "MMCF"
    rows.sort(key=lambda r: (r["value"] is None, -(r["value"] or 0)))
    return ToolResult(
        ok=True,
        data={
            "product": args.product,
            "year": args.year,
            "unit": unit,
            "rows": rows,
        },
        notes=notes,
    )


def get_kpis_impl(
    df: pd.DataFrame, engine: ForecastEngine, args: GetKpisInput
) -> ToolResult:
    code = resolve_region_code(args.region)
    if code is None:
        return ToolResult(ok=False, error=f"Unknown region: {args.region!r}")
    kpis = compute_kpi_set(df, engine, code, args.product, args.year)
    return ToolResult(ok=True, data=kpis.as_dict(), notes=list(kpis.notes))


def get_anomalies_impl(
    df: pd.DataFrame, engine: ForecastEngine, args: GetAnomaliesInput
) -> ToolResult:
    """Statistical anomaly detection on YoY % changes. Z-score against the
    region's own historical YoY distribution. The LLM only EXPLAINS what
    this returns; it cannot add or remove anomalies."""
    code = resolve_region_code(args.region)
    if code is None:
        return ToolResult(ok=False, error=f"Unknown region: {args.region!r}")
    hist = engine.history(code, args.product)
    if len(hist) < 4:
        return ToolResult(
            ok=False,
            error=f"{_name_for(code)} has too little data for anomaly detection.",
        )
    series = hist.set_index("year")["value"]
    yoy = series.pct_change().dropna()
    if len(yoy) < 3:
        return ToolResult(ok=False, error="Not enough year-over-year observations.")
    mean = float(yoy.mean())
    std = float(yoy.std(ddof=1))
    if std < 1e-9:
        return ToolResult(
            ok=True,
            data={
                "anomalies": [],
                "method": "z>2.5 on YoY%",
                "mean_yoy": mean,
                "std_yoy": std,
            },
        )
    z = (yoy - mean) / std
    flagged = []
    for year, score in z.items():
        if abs(score) >= args.z_threshold:
            flagged.append(
                {
                    "year": int(year),
                    "yoy_pct": round(float(yoy.loc[year]) * 100, 2),
                    "z_score": round(float(score), 2),
                    "value": round(float(series.loc[year]), 2),
                    "prior_value": round(float(series.loc[year - 1]), 2),
                }
            )
    flagged.sort(key=lambda r: -abs(r["z_score"]))
    return ToolResult(
        ok=True,
        data={
            "region": _name_for(code),
            "product": args.product,
            "method": f"|z| >= {args.z_threshold} on year-over-year % change",
            "mean_yoy_pct": round(mean * 100, 2),
            "std_yoy_pct": round(std * 100, 2),
            "anomalies": flagged,
        },
    )


def list_regions_impl(
    df: pd.DataFrame, engine: ForecastEngine, args: ListRegionsInput
) -> ToolResult:
    """Return regions that have any data for either product."""
    have_data = set(df["region_code"].unique()) if not df.empty else set()
    group_filter: RegionGroup | None = None
    if args.group:
        g = args.group.lower()
        if g.startswith("nation"):
            group_filter = RegionGroup.NATIONAL
        elif "offshore" in g or "gulf" in g:
            group_filter = RegionGroup.OFFSHORE
        elif "padd" in g:
            group_filter = RegionGroup.PADD
        elif "state" in g:
            group_filter = RegionGroup.STATE
    out = []
    for r in ALL_REGIONS:
        if group_filter and r.group is not group_filter:
            continue
        out.append(
            {
                "code": r.code,
                "name": r.name,
                "group": r.group.value,
                "has_data": r.code in have_data,
            }
        )
    return ToolResult(ok=True, data={"regions": out})


# ============================================================
# Gemini FunctionDeclarations
# ============================================================


def _build_function_declarations() -> list[genai_types.FunctionDeclaration]:
    """All tools the LLM is allowed to call. Schemas mirror the Pydantic models."""
    SCHEMA = genai_types.Schema
    OBJ = "OBJECT"
    STR = "STRING"
    INT = "INTEGER"
    NUM = "NUMBER"
    ARR = "ARRAY"

    return [
        genai_types.FunctionDeclaration(
            name="get_production",
            description=(
                "Get the production volume for one region/product/year. "
                "Past full years return the EIA actual; future or partial-current "
                "years return the linear-regression forecast. "
                "Returns value with unit (MBBL for crude oil, MMCF for natural gas) "
                "and an is_forecast flag."
            ),
            parameters=SCHEMA(
                type=OBJ,
                properties={
                    "region": SCHEMA(
                        type=STR,
                        description="Region name, EIA code, or 2-letter state abbr (e.g. 'Texas', 'STX', 'TX', 'United States', 'PADD 3')",
                    ),
                    "product": SCHEMA(
                        type=STR, description="'crude_oil' or 'natural_gas'"
                    ),
                    "year": SCHEMA(type=INT, description="Calendar year"),
                },
                required=["region", "product", "year"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="get_history",
            description=(
                "Get the historical annual production time series for one region/product. "
                "Returns a list of {year, value} pairs with unit metadata."
            ),
            parameters=SCHEMA(
                type=OBJ,
                properties={
                    "region": SCHEMA(type=STR),
                    "product": SCHEMA(
                        type=STR, description="'crude_oil' or 'natural_gas'"
                    ),
                    "start_year": SCHEMA(type=INT),
                    "end_year": SCHEMA(type=INT),
                },
                required=["region", "product"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="compare_regions",
            description=(
                "Compare two to five regions for the same product/year. "
                "Returns rows sorted descending by value, plus is_forecast flags."
            ),
            parameters=SCHEMA(
                type=OBJ,
                properties={
                    "regions": SCHEMA(
                        type=ARR,
                        items=SCHEMA(type=STR),
                        description="2-5 regions",
                    ),
                    "product": SCHEMA(type=STR),
                    "year": SCHEMA(type=INT),
                },
                required=["regions", "product", "year"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="get_kpis",
            description=(
                "Get the full KPI bundle (projected production, YoY growth, "
                "5-year CAGR, volatility, illustrative revenue potential) for "
                "one region/product/year."
            ),
            parameters=SCHEMA(
                type=OBJ,
                properties={
                    "region": SCHEMA(type=STR),
                    "product": SCHEMA(type=STR),
                    "year": SCHEMA(type=INT),
                },
                required=["region", "product", "year"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="get_anomalies",
            description=(
                "Statistically detect production anomalies in one region/product. "
                "Anomalies are flagged using a z-score on year-over-year percent "
                "change against the region's own history. The LLM is NOT permitted "
                "to invent or remove anomalies; only explain the ones returned here."
            ),
            parameters=SCHEMA(
                type=OBJ,
                properties={
                    "region": SCHEMA(type=STR),
                    "product": SCHEMA(type=STR),
                    "z_threshold": SCHEMA(
                        type=NUM,
                        description="Z-score threshold (default 2.5; range 1.0-5.0)",
                    ),
                },
                required=["region", "product"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="list_regions",
            description=(
                "List the regions the dashboard supports. Optional 'group' filter: "
                "'national', 'offshore', 'padd', or 'state'."
            ),
            parameters=SCHEMA(
                type=OBJ,
                properties={
                    "group": SCHEMA(type=STR),
                },
            ),
        ),
    ]


FUNCTION_DECLARATIONS: list[genai_types.FunctionDeclaration] = (
    _build_function_declarations()
)


# ============================================================
# Tool dispatch table
# ============================================================


_DISPATCH: dict[str, tuple[type[BaseModel], Callable[..., ToolResult]]] = {
    "get_production": (GetProductionInput, get_production_impl),
    "get_history": (GetHistoryInput, get_history_impl),
    "compare_regions": (CompareRegionsInput, compare_regions_impl),
    "get_kpis": (GetKpisInput, get_kpis_impl),
    "get_anomalies": (GetAnomaliesInput, get_anomalies_impl),
    "list_regions": (ListRegionsInput, list_regions_impl),
}


def execute_tool(
    name: str,
    raw_args: dict[str, Any],
    df: pd.DataFrame,
    engine: ForecastEngine,
) -> dict:
    """Validate inputs, run the implementation, return a JSON-serializable dict
    suitable for sending back to Gemini as a function_response."""
    entry = _DISPATCH.get(name)
    if entry is None:
        return asdict(ToolResult(ok=False, error=f"Unknown tool: {name!r}"))
    model_cls, impl = entry
    try:
        validated = model_cls.model_validate(raw_args)
    except ValidationError as e:
        return asdict(
            ToolResult(
                ok=False,
                error=f"Invalid arguments for {name}: {e.errors(include_url=False)}",
            )
        )
    try:
        result = impl(df, engine, validated)
    except (
        Exception
    ) as e:  # tool implementations should not throw, but defense in depth
        logger.exception("Tool %s raised", name)
        return asdict(ToolResult(ok=False, error=f"Tool {name} crashed: {e}"))
    return asdict(result)
