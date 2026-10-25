# Eclipse Ledger MCP

**Powered by Cyan Eclipse Technologies** — https://cetech.ai

**Eclipse Ledger — betting records, price comparison, and responsible-gambling controls. Not a sportsbook. No bets are placed here.**

The Eclipse betting suite is the owner's explicit, separate home for sports-betting platforms — records, prices, and self-protection for a person who already bets. It never blends with Eclipse Marquee (whose §7 line keeps gambling out of ticketing entirely). There is no public consumer API for odds or bet placement at any major US sportsbook — FanDuel included — and the only technical substitutes are ToS-prohibited scraping and session automation. So this suite is built on what honestly exists: licensed odds data, the user's own records, and a responsible-gambling core that enforces limits the user set for themselves in a calm state. It takes no wagers, holds no betting funds, picks no winners, and — by owner decision D2 — earns no operator affiliate revenue.

## Status — honest labels

v0.1.0, phase **B0 (RG Core + records + fixture odds)**. Local stdio transport, Python stdlib only. Odds data is **fixtures** shaped like The Odds API v4 responses (3 books, 2 events) — no feed is connected, no account exists, nothing is scraped, all records are synthetic, and **no certification is claimed — bench pending**. Live-user launch is behind the spec's **counsel gate (D4)**; a licensed odds feed is an owner signup step (B0 adapter candidate: The Odds API).

## The RG Core is the product

**Limits engine (spec §3.2).** Decreases take effect *in the same call*. Increases wait out a cooling delay — the stricter of the suite floor (72h daily / 7d weekly / 30d monthly) and any stricter state fixture (90-day deposit windows in MA/IN/LA/OH fixtures) — then require a **fresh explicit confirmation** inside a 24-hour window or they lapse. There is **no tool that raises a limit**: the forbidden names are enumerated in code and asserted in tests, and `limit_set` with an increase returns PENDING state only. An honest scope note rides every limits surface: suite limits govern what *this tool* will help with; they do not change the user's limits at any operator.

**Self-exclusion — absolute (spec §3.3).** One call from any source (operator program, state program, NVSEP, or self-declared — honored identically) and while it is active, *every* function that could lead to a wager denies identically — odds, prep, arbitrage observation, new-bet records, "just checking" included. No tool ends an exclusion before its recorded legal expiry; after expiry, reactivation requires a fresh jurisdiction verdict plus limits re-confirmation. What remains: historical records, limit/exclusion management, reality snapshots, and help resources. Easy to exclude, impossible to un-exclude early — asymmetric by construction.

**Help resources (§3.5).** The resource block carries **1-800-GAMBLER** (the number printed by state programs and operators) **and** **1-800-MY-RESET (1-800-697-3738)**, because NCPG's national helpline branding reportedly shifted in 2026 (§1.4) — both are carried as versioned data with a `reverify_due` marker, honestly labeled, rather than one being silently dropped or silently stale. The block is presented in every periodic summary, on exclusion events and denials, on evasion/claims refusals, and whenever a pattern flag fires.

**Jurisdiction engine (§4).** The state matrix is versioned data keyed *(state, product class)* — `sportsbook`, `dfs-classic`, `pickem-ath`, `pickem-p2p` are distinct legal objects (in New York, against-the-house pick'em is NOT_LEGAL while the P2P variant is legal; in Texas, sportsbook is NOT_LEGAL while classic DFS is legal). Every verdict is receipted. A matrix past its 30-day TTL degrades verdicts to **UNKNOWN, and UNKNOWN denies** — the suite never answers from stale law. Declared jurisdiction is the user's attestation; the suite never geolocates and never helps spoof.

**P&L truth (§3.4).** A bonus bet is not cash: its stake is not returned on a win and unsettled bonus instruments are valued at **zero** in the cash P&L. The headline on every summary is **cash net position**, reproducible from the raw records by independent recomputation (a test does exactly that). Pattern flags in the NJ-trigger shape — stake/deposit velocity, loss-chasing signatures, sessions ending near-zero, repeated limit increases — are computed **on ledger data only** and surfaced as facts with the partial-view note: activity outside the ledger is invisible to it, and a clean panel is not a clean bill of health.

**Odds (§5.1/§5.4).** Comparison ordering is **price only** — no other ranking input exists. Every surface carries its jurisdiction verdict reference, its RG status reference, timestamps, and the market margin. Operator promotions are **stripped by construction** and a banned-phrase lint backstops every output (no "risk-free", no "guaranteed", no "lock" — §2/§9 vocabulary). Arbitrage observation is data with its mandatory honesty attached: *books limit winning accounts*, prices can be refused, and both legs filling is never certain. There is deliberately **no arb stake calculator** (D5: execution support, not observation).

**Slip prep (§5.3/§6).** `slip_prepare` returns a prepared slip *record* — data, evaluated against limits × jurisdiction × bankroll policy × exclusion with named verdicts (`ALLOW_TO_PREP` / `OVER_LIMIT` / `OVER_POLICY` / `EXCLUDED` / `NOT_LEGAL`). **There is no submit tool.** Tier 2 (placement) is an empty tier in v1, stated not implied.

**No credentials, ever (§1.1/§5.2).** There is no "connect your FanDuel account" flow, because its only implementations are ToS-prohibited session automation. A credential-shaped input to *any* tool (at any nesting depth) is refused by name — `CREDENTIALS_NOT_ACCEPTED` — enforced in every handler, not only at dispatch.

## Tools (22)

| Tool | What it does |
|---|---|
| `profile_set` / `profile_get` | The one profile (declared state + age attestation) + RG status + resources. |
| `limit_set` / `limit_confirm` / `limits_list` | The asymmetry law: decreases instant, increases delayed + confirmed or lapsed. |
| `timeout_start` | Self-imposed break (3–365d); denies like exclusion; unshortenable. |
| `exclusion_start` / `exclusion_end` / `exclusion_status` | Exclusion lifecycle: one-call start, refusal-machine end, always-readable status. |
| `jurisdiction_check` / `matrix_status` | Receipted (state, class) verdicts; matrix version/TTL/staleness. |
| `bet_record_add` / `records_list` | Your own records in; cash views + raw records out. |
| `deposit_record_add` | Your deposits, with over-limit facts stated plainly. |
| `pnl_summary` / `reality_snapshot` | Cash net position first; flags as facts; resources attached. |
| `odds_compare` / `arb_observe` | Fixture line shopping (price only) / cross-book observation with its warning. |
| `slip_prepare` | A slip as data, policy-evaluated. Cannot be submitted by anything here. |
| `advice_request` | Ask for a pick/system/edge → the claims-law refusal, by construction. |
| `resources_get` / `receipt_list` | The help-resource block; the hash-chained receipt ledger. |

## Name note (spec §2)

**Ledger** passes the §3 naming test *with cautions* (N1 trust-and-receipts field — "ledger" is named in §3 verbatim; it claims records, the one thing the product provably keeps). A **trademark screen is owed before any public surface** (Ledger SAS adjacency); if the screen fails, the functional fallback ships instead: **Eclipse Betting Records**. Platform chapters carry no creative names — platforms appear in descriptors only, so nothing implies operator affiliation or endorsement.

## Run it

```bash
python3 server.py            # MCP over stdio, stdlib only, no dependencies
python3 smoke.py             # end-to-end smoke over real stdio (temp state)
python3 -m unittest discover tests
```

State lives in `data/state.json` (override: `ECLIPSE_LEDGER_STATE`); deleting it re-seeds from the fixtures. Tools accept an optional `at_ts` (epoch seconds) fixture clock so the delay/TTL laws are provable offline.

## Lineage

Spec: `~/workspace/cyan-eclipse/eclipse-betting-suite-spec-20261025.md` (B0 = §3 RG Core, §4 jurisdiction, §5 surface, §13 acceptance properties). Receipts are hash-chained in the house pattern (GENESIS anchor); denials are receipts too. FanDuel, DraftKings, BetMGM, and The Odds API are referenced nominatively as data sources/fixtures; nothing here implies any operator endorses Cyan Eclipse Technologies.

A Cyan Eclipse Technologies product. The "Powered by Cyan Eclipse Technologies" attribution travels with it.
