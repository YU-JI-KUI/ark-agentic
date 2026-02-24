# Legacy Field Mappings and Redundant Logic Cleanup Plan

## Overview

Based on the analysis of the codebase, the real API format is now stable and working. This plan outlines the removal of backward-compatible legacy field mappings and redundant logic to simplify the codebase.

---

## Files to Modify

### 1. `field_extraction.py` - Remove Legacy Mappings

#### Current State
The file contains dual field mappings for each service:
- Real API format mappings (e.g., `ACCOUNT_OVERVIEW_FIELD_MAPPING`)
- Legacy format mappings (e.g., `ACCOUNT_OVERVIEW_LEGACY_MAPPING`)

#### Items to Remove

| Service | Legacy Mapping | Lines | Description |
|---------|---------------|-------|-------------|
| account_overview | `ACCOUNT_OVERVIEW_LEGACY_MAPPING` | 79-92 | Old `data.*` path mappings |
| cash_assets | `CASH_ASSETS_LEGACY_MAPPING` | 151-157 | Old `data.*` path mappings |
| etf_holdings | `ETF_HOLDINGS_LEGACY_MAPPING` | 207-211 | Old `data.*` path mappings |
| hksc_holdings | `HKSC_HOLDINGS_LEGACY_MAPPING` | 304-308 | Old `data.*` path mappings |

#### Functions to Simplify

| Function | Current Logic | Simplified Logic |
|----------|---------------|------------------|
| `extract_account_overview()` | Detects format, chooses mapping | Use real mapping directly |
| `extract_cash_assets()` | Detects format, chooses mapping | Use real mapping directly |
| `extract_etf_holdings()` | Detects format, chooses mapping | Use real mapping directly |
| `extract_hksc_holdings()` | Detects format, chooses mapping | Use real mapping directly |
| `detect_response_format()` | Returns "real" or "legacy" | Remove entirely |

#### SERVICE_FIELD_MAPPINGS Registry
Remove the `legacy` key from each service entry:
```python
# Before
SERVICE_FIELD_MAPPINGS = {
    "account_overview": {
        "real": ACCOUNT_OVERVIEW_FIELD_MAPPING,
        "legacy": ACCOUNT_OVERVIEW_LEGACY_MAPPING,  # REMOVE
    },
    ...
}

# After
SERVICE_FIELD_MAPPINGS = {
    "account_overview": ACCOUNT_OVERVIEW_FIELD_MAPPING,
    ...
}
```

---

### 2. `schemas.py` - Remove Legacy Schema Classes and Methods

#### Schema Classes to Remove/Simplify

| Class | Legacy Elements | Action |
|-------|-----------------|--------|
| `HoldingItemSchema` | Entire class (lines 126-169) | Remove - used only for legacy format |
| `HoldingsSummarySchema` | Entire class (lines 171-189) | Remove - used only for legacy format |
| `AccountOverviewSchema` | `from_raw_data()` method, legacy fields | Remove method and legacy fields |
| `ETFHoldingsSchema` | `from_raw_data()` method, `holdings`/`summary` fields | Remove method and legacy fields |
| `HKSCHoldingsSchema` | `from_raw_data()` method, `holdings`/`summary` fields | Remove method and legacy fields |
| `CashAssetsSchema` | `from_raw_data()` method, legacy fields | Remove method and legacy fields |

#### Detailed Removal for AccountOverviewSchema

**Legacy fields to remove:**
- `total_profit` (not in real API)
- `profit_rate` (not in real API)
- `update_time` (not in real API)
- `margin_ratio` (compatibility field)
- `risk_level` (compatibility field)
- `maintenance_margin` (compatibility field)
- `available_margin` (compatibility field)

**Methods to remove:**
- `from_raw_data()` (lines 58-87)

#### Detailed Removal for ETFHoldingsSchema

**Legacy fields to remove:**
- `holdings: list[HoldingItemSchema]` (line 249)
- `summary: HoldingsSummarySchema | None` (line 250)

**Methods to remove:**
- `from_raw_data()` (lines 277-304)

#### Detailed Removal for HKSCHoldingsSchema

**Legacy fields to remove:**
- `holdings: list[HoldingItemSchema]` (line 385)
- `summary: HoldingsSummarySchema | None` (line 386)

**Methods to remove:**
- `from_raw_data()` (lines 420-445)

#### Detailed Removal for CashAssetsSchema

**Legacy fields to remove:**
- `available_cash` (line 526)
- `frozen_cash` (line 527)
- `total_cash` (line 528)
- `update_time` (line 529)

**Methods to remove:**
- `from_raw_data()` (lines 533-548)

---

### 3. `service_client.py` - Verify No Legacy Logic

The service client adapters already use the real API format correctly. No changes needed.

---

### 4. `display_card.py` - Verify Compatibility

The display_card tool uses `extract_*` functions from field_extraction. After cleanup:
- `extract_account_overview()` → returns real API fields directly
- `extract_cash_assets()` → returns real API fields directly
- `extract_etf_holdings()` → returns real API fields directly
- `extract_hksc_holdings()` → returns real API fields directly

**Note:** Line 118-119 in display_card.py has a comment about Fund using "old format":
```python
else:
    # Fund 暂时使用旧格式
    template = TemplateRenderer.render_holdings_list_card(asset_class, data)
```
This is acceptable as fund_holdings does not have real API documentation yet.

---

## Implementation Order

```
1. field_extraction.py
   ├── Remove all *_LEGACY_MAPPING constants
   ├── Remove detect_response_format() function
   ├── Simplify extract_* functions to use real mappings only
   └── Simplify SERVICE_FIELD_MAPPINGS registry

2. schemas.py
   ├── Remove HoldingItemSchema class
   ├── Remove HoldingsSummarySchema class
   ├── Remove from_raw_data() methods from all schema classes
   ├── Remove legacy fields from schema classes
   └── Keep from_api_response() methods (rename to from_extracted_data or keep as-is)

3. Verify
   └── Run tests to ensure no regressions
```

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Mock data incompatibility | Low | Mock data files already use real API format |
| Template rendering breaks | Low | Templates use field_extraction output which will still work |
| Tests fail | Medium | Run full test suite after changes |

---

## Summary of Changes

| File | Lines Removed | Lines Modified | Complexity |
|------|---------------|----------------|------------|
| field_extraction.py | ~60 lines | ~30 lines | Low |
| schemas.py | ~200 lines | ~50 lines | Medium |
| **Total** | **~260 lines** | **~80 lines** | **Medium** |

---

## Decision Points

1. **Should we keep `from_api_response()` methods?**
   - They are currently unused (field_extraction returns dicts, not schemas)
   - Could be removed if not needed for validation

2. **Should we keep the Pydantic schemas at all?**
   - Currently only `FundHoldingsSchema` and `SecurityDetailSchema` are used in service_client.py
   - Other schemas are defined but not used in the actual flow
   - Could be removed entirely if not needed for validation
