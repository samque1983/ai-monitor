# Project: V1.9 Quant Radar

## Agentic Workflow Standards

### 1. TDD Core
Strictly follow Test-Driven Development for all functional changes.
- Write the failing test FIRST, run it to confirm failure.
- Write the minimum implementation to make it pass.
- Refactor only after green.
- Never mark a task as "Done" until tests show 100% pass rate.

### 2. Mirror Testing Rule
Every source file must have a corresponding test file:
- `src/config.py` → `tests/test_config.py`
- `src/data_loader.py` → `tests/test_data_loader.py`
- `src/market_data.py` → `tests/test_market_data.py`
- `src/data_engine.py` → `tests/test_data_engine.py`
- `src/scanners.py` → `tests/test_scanners.py`
- `src/report.py` → `tests/test_report.py`
- `src/iv_store.py` → `tests/test_iv_store.py`
- `src/main.py` → `tests/test_integration.py` (integration test)

### 3. Contract Validation
- **Backend tests:** Verify core logic accuracy and edge cases.
- **Frontend tests:** Verify UI components return the exact data structures required by the logic layer.

### 4. Execution Protocol
- Before implementation: write test → run test → see RED.
- After implementation: run test → see GREEN (100% pass).
- On commit: all tests must pass.

### 5. UI Standard
<!-- Define your design system reference, e.g.:
All frontend code must follow the design system defined in `docs/specs/design_system.md`:
- Design tokens in CSS (no magic numbers).
- Only the bridge layer imports from logic/data. Components are pure renderers.
-->

### 6. Spec-to-Code Mapping
Each spec in `docs/specs/` maps 1:1 to source modules:
- `req/phase_1_monitor_market.md` → `src/config.py`, `src/data_loader.py`, `src/market_data.py`, `src/data_engine.py`, `src/scanners.py`, `src/report.py`, `src/iv_store.py`, `src/main.py`

## Document Hierarchy

Three-layer documentation. Claude reads **this file** automatically; read others **on demand** as described below.

```
CLAUDE.md                  ← Always loaded (workflow + routing rules)
req/                       ← Requirements (WHAT)
  GLOBAL_MASTER.md           ← Constitution: universal constraints for ALL features
  PHASE_N_*.md               ← Individual feature requirements
docs/specs/                ← Design specs (HOW), 1:1 mapped to source modules
docs/plans/                ← Temporary working docs (not maintained post-implementation)
```

### Reading Protocol
- **Before any implementation task:** read `req/GLOBAL_MASTER.md` first — it contains architectural constraints, phased roadmap, and business rules that apply to all code.
- **When modifying existing code:** read the corresponding `docs/specs/*.md` (see Spec-to-Code Mapping above) to understand the current design contract.
- **When implementing a new feature/phase:** read `req/GLOBAL_MASTER.md` + the relevant `req/PHASE_N_*.md` to understand requirements, then read/create the corresponding spec.
- **Do NOT load all docs at once.** Only read files relevant to the current task.

### Adding New Requirements
- New universal constraints → append to `req/GLOBAL_MASTER.md`.
- New feature → create `req/PHASE_N_FEATURE_NAME.md`, then create matching `docs/specs/*.md` during design.
- Update Spec-to-Code Mapping and Mirror Testing Rule in this file when new modules are added.

### Plans Workflow
- Plans are saved to `docs/plans/YYYY-MM-DD-<feature-name>.md` during implementation.
- Plans are **temporary working docs** — they guide implementation but are not maintained afterward.
- **Cleanup trigger:** When a feature is fully implemented, tests pass, and `docs/specs/` is synced with code → delete the corresponding `docs/plans/*.md` files.
- **Do NOT read plan files** for understanding current code — always use `docs/specs/` instead.

### Requirement Lifecycle
- `req/GLOBAL_MASTER.md` is the constitution — **never archive**.
- `req/PHASE_N_*.md` — archive to `archive/` via `git mv` once the phase is fully implemented.
- `docs/specs/*.md` — **never archive**; they live and die with their corresponding source modules.
- `docs/plans/*.md` — **delete** once the feature is fully implemented and specs are synced. Plans are throwaway working docs; the spec is the permanent record.
- `req/` contains only active requirements. **Do NOT read `archive/` files** unless the user explicitly asks.

### Source of Truth
- After implementation, `docs/specs/*.md` is the authoritative reference for each module (1:1 with code).
- `req/PHASE_N_*.md` captures original intent but may drift; specs reflect what was actually built.
- If a human-readable summary is needed, generate it from the spec on demand — do not create extra docs.

### Conflict Resolution
- `req/GLOBAL_MASTER.md` Roadmap Index is a summary only. Detailed requirements live in `req/PHASE_N_*.md` — these take precedence.

## Architecture Rules
- **Import direction:** `main.py → scanners.py/report.py → data_engine.py → market_data.py → data_loader.py` (never reverse).
- **Data model:** `TickerData` dataclass is the central data structure passed between modules.
- **Config authority:** All configuration lives in `config.yaml`, loaded via `src/config.py`.
- **Market data:** All external API calls go through `MarketDataProvider` — no other module touches yfinance or ib_insync directly.
- **Error isolation:** Per-ticker try-except in main loop — one ticker failure never crashes the scan.
