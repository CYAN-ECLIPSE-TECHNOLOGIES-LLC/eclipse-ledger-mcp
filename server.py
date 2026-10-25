#!/usr/bin/env python3
"""Eclipse Ledger MCP — v0.1.0, phase B0 (RG Core + records +
fixture odds).

Powered by Cyan Eclipse Technologies (cetech.ai).

Descriptor (mandatory on every surface, spec section 2): "Eclipse
Ledger — betting records, price comparison, and responsible-gambling
controls. Not a sportsbook. No bets are placed here."

Ledger is the core of the Eclipse betting suite (spec:
eclipse-betting-suite-spec-20261025.md). The RG Core is the product;
platform chapters are adapters hanging off it, and no chapter may
weaken a core rule. B0 ships the core itself:

  * LIMITS ENGINE (spec 3.2). Decreases take effect immediately.
    Increases wait out a cooling delay — the maximum of the suite
    floor (72h daily / 7d weekly / 30d monthly) and any stricter
    state fixture (90d deposit windows exist) — and then need a
    fresh explicit confirmation inside a window, or they lapse.
    There is NO tool path that raises a limit: the denylist is
    enumerated in code and asserted in tests. The agent enforces
    limits; it never grants them, and no surface may suggest one.

  * SELF-EXCLUSION, ABSOLUTE (spec 3.3). One call, from any source
    (operator program / state program / self-declared — honored
    identically), and while it is active every function that could
    lead to a wager denies identically, "just checking" included.
    No tool ends an exclusion before its recorded legal expiry.
    Historical records, limit/exclusion management, reality
    snapshots, and help resources remain available — the suite
    stays a bookkeeper and a mirror, and stops being a betting aid.

  * JURISDICTION ENGINE (spec 4). The state matrix is versioned
    data keyed (state, product class, variant) with source +
    as-of + TTL. A stale matrix degrades verdicts to UNKNOWN, and
    UNKNOWN denies wagering-adjacent functions — never a shrug.

  * RECORDS LEDGER (spec 5.2) + P&L TRUTH (spec 3.4). The user's
    own records, user-entered only. Bonus bets are not cash: their
    stake is not returned and unsettled bonus instruments are
    valued at ZERO in the cash P&L. The headline number is cash
    net position, reproducible from the raw records. Pattern flags
    (NJ-trigger shape) are computed on ledger data only and
    surfaced as facts with the partial-view note attached.

  * ODDS (spec 5.1). FIXTURES shaped like The Odds API v4
    responses (3 books, 2 events). No feed is connected, no
    account exists, nothing is scraped. Comparison ordering is
    PRICE ONLY — no other ranking input exists. Operator
    promotions are stripped by construction and a banned-phrase
    lint backstops every odds-surface output.

  * SLIP PREP (spec 5.3 / 6). A prepared slip is a data object in
    the ledger, evaluated against limits x jurisdiction x
    bankroll policy x exclusion state. THERE IS NO SUBMIT TOOL.
    T2 (placement) is an empty tier in v1, stated not implied.

  * CLAIMS LAW (spec 9). Requests for a pick, a guarantee, or a
    "system" receive the banned-class refusal. The suite reports
    prices and records; it does not pick winners.

  * NO CREDENTIALS. There is no "connect your FanDuel account"
    flow: the only technical implementations are ToS-prohibited
    session automation (spec 1.1). A credential-shaped input to
    ANY tool is refused by name, structurally, in dispatch.

B0 SCOPE: fixtures + the user's own synthetic records only.
Live-user launch is behind the spec's counsel gate (D4); licensed
odds feeds are an owner signup step. Synthetic data only.

Transport: MCP over stdio (newline-delimited JSON-RPC 2.0), stdlib only.
State: $ECLIPSE_LEDGER_STATE or ./data/state.json beside this file.
Time: tools accept an optional at_ts (epoch seconds) fixture clock so
the delay/TTL laws are provable offline; production callers omit it.
"""
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
STATE_PATH = Path(os.environ.get(
    "ECLIPSE_LEDGER_STATE", HERE / "data" / "state.json"))
FIXTURES_DIR = HERE / "fixtures"
POLICY_PATH = HERE / "policy.json"

DESCRIPTOR = ("Eclipse Ledger — betting records, price comparison, "
              "and responsible-gambling controls. Not a sportsbook. "
              "No bets are placed here.")

# ------------------------------------------------------------- policy
# Suite floors (spec 3.2): delays may only ever be LONGER than these.
FLOORS = {"daily": 72, "weekly": 168, "monthly": 720, "per_bet": 72}
CONFIRM_WINDOW_MAX_HOURS = 168


def load_policy() -> dict:
    policy = json.loads(POLICY_PATH.read_text())
    delays = policy["increase_delay_hours"]
    for window, floor in FLOORS.items():
        if int(delays.get(window, 0)) < floor:
            raise ValueError(
                f"TIER_FLOOR_VIOLATION: increase delay for "
                f"'{window}' is {delays.get(window)}h, below the "
                f"suite floor of {floor}h (spec 3.2/7)")
    if not (1 <= int(policy["confirm_window_hours"])
            <= CONFIRM_WINDOW_MAX_HOURS):
        raise ValueError(
            "TIER_FLOOR_VIOLATION: confirm_window_hours out of "
            "bounds (spec 3.2)")
    return policy


try:
    POLICY = load_policy()
except ValueError as exc:  # tier-floor violation fails at load
    print(str(exc), file=sys.stderr)
    sys.exit(2)

LIMIT_KINDS = {"deposit", "wager", "loss", "time",
               "stake_cap", "pct_cap", "bankroll"}
LIMIT_WINDOWS = {"daily", "weekly", "monthly", "per_bet"}
WINDOW_SECONDS = {"daily": 86400, "weekly": 604800,
                  "monthly": 2592000, "per_bet": 0}
PRODUCT_CLASSES = {"sportsbook", "dfs-classic",
                   "pickem-ath", "pickem-p2p"}
LEGAL_VERDICTS = {"LEGAL_ONLINE": "ALLOWED"}

# Claim vocabulary banned on every surface (spec 2 + 9): no edge,
# no locks, no guarantees, no "risk-free" — including for arb.
BANNED_PHRASES = (
    "risk-free", "risk free", "guaranteed", "can't lose",
    "cant lose", "can not lose", "free money", "beat the book",
    "hot hand", "you're due", "you are due", "sure thing",
    "lock of the", "lock bet", "guaranteed profit", "no risk",
)

# Credential-shaped keys are refused anywhere in any tool's args:
# the suite holds no operator credential because none is collected.
CREDENTIAL_KEYS = {"password", "passwd", "pwd", "api_key", "apikey",
                   "secret", "credentials", "credential",
                   "session_token", "access_token", "auth_token",
                   "bearer_token", "cookie", "cookies"}

ARB_WARNING = (
    "Books limit winning accounts: systematically exploiting "
    "cross-book price differences predictably gets accounts "
    "limited or closed (spec 1.5). Shown prices can move, can be "
    "stale, and can be refused by a book at submission; both legs "
    "filling at the shown prices is never certain, so the "
    "arithmetic below is an observation, not a promise.")

PARTIAL_VIEW_NOTE = (
    "Computed from records in this ledger only; activity outside "
    "the ledger is invisible to it. A clean flag panel is not a "
    "clean bill of health.")


class ToolError(Exception):
    pass


def now_iso(ts=None) -> str:
    return datetime.fromtimestamp(
        ts if ts is not None else time.time(),
        timezone.utc).replace(microsecond=0).isoformat()


def iso_to_ts(value: str) -> float:
    return datetime.fromisoformat(
        value.replace("Z", "+00:00")).timestamp()


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def ts_of(args, state) -> float:
    """Fixture clock: explicit at_ts wins; else wall clock."""
    if args.get("at_ts") is not None:
        return float(args["at_ts"])
    return time.time()


# ---------------------------------------------------------------- state
def load_fixture(name):
    return json.loads((FIXTURES_DIR / name).read_text())


def empty_state() -> dict:
    return {"profile": None, "limits": [], "pending_limits": [],
            "exclusions": [], "timeouts": [], "records": [],
            "deposits": [], "slips": [], "receipts": [],
            "matrix_loaded": load_fixture("matrix.json"),
            "resources": load_fixture("resources.json"),
            "odds": load_fixture("odds.json")}


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return empty_state()


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1))


# ------------------------------------------------------------- receipts
def emit_receipt(state: dict, rtype: str, detail: dict) -> dict:
    """Append-only, hash-chained, GENESIS-anchored. Denials are
    receipts too (house pattern)."""
    prev = state["receipts"][-1]["hash"] if state["receipts"] \
        else "GENESIS"
    entry = {"seq": len(state["receipts"]) + 1,
             "ts": int(time.time()), "type": rtype,
             "prev_hash": prev, "detail": detail}
    entry["hash"] = sha(prev + canon(
        {k: v for k, v in entry.items() if k != "hash"}))
    state["receipts"].append(entry)
    return entry


def verify_receipt_chain(receipts) -> bool:
    prev = "GENESIS"
    for entry in receipts:
        if entry.get("prev_hash") != prev:
            return False
        expected = sha(prev + canon(
            {k: v for k, v in entry.items() if k != "hash"}))
        if entry.get("hash") != expected:
            return False
        prev = entry["hash"]
    return True


# ------------------------------------------------------- input hygiene
def reject_credentials(obj, path="args") -> None:
    """A credential-shaped input is refused by name, at any depth,
    for every tool (spec 1.1/9: no credential route exists)."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).lower() in CREDENTIAL_KEYS:
                raise ToolError(
                    f"CREDENTIALS_NOT_ACCEPTED: '{key}' at {path} — "
                    f"this suite never asks for, stores, or uses an "
                    f"operator credential; there is no account-"
                    f"connection route in v1 (spec 1.1, 5.2, 9)")
            reject_credentials(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            reject_credentials(value, f"{path}[{i}]")


def lint_output(text: str) -> None:
    """Banned-claim backstop (spec 2/9): no surface ships a claim."""
    low = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase in low:
            raise ToolError(
                f"OUTPUT_QUARANTINED: banned claim phrase "
                f"'{phrase}' present in a surface payload (spec "
                f"2/9 claims law); the surface was not emitted")


# ------------------------------------------------------------ resources
def resource_block(state, ts) -> dict:
    res = state["resources"]
    block = {"version": res["version"], "as_of": res["as_of"],
             "entries": res["entries"], "note": res["note"],
             "reverify_due": res["reverify_due"],
             "reverify_overdue":
                 ts > iso_to_ts(res["reverify_due"] + "T00:00:00Z")}
    state_entry = next(
        (e for e in res["entries"] if e["name"] == "State program"),
        None)
    if state_entry is not None and state.get("profile"):
        block["state_context"] = (
            f"profile state: {state['profile']['state']} — the "
            f"state program entry above is resolved for this "
            f"state at render time")
    return block


def resources_text(state, ts) -> str:
    block = resource_block(state, ts)
    lines = []
    for entry in block["entries"]:
        if entry.get("phone"):
            lines.append(f"{entry['name']}: {entry['phone']}")
    return "; ".join(lines)


# ------------------------------------------------------------------ RG
def active_exclusion(state, ts):
    for record in state["exclusions"]:
        if record["status"] == "active" \
                and ts < record["legal_expiry_ts"]:
            return record
    return None


def active_timeout(state, ts):
    for record in state["timeouts"]:
        if record["status"] == "active" and ts < record["ends_ts"]:
            return record
    return None


def rg_status(state, ts) -> dict:
    exclusion = active_exclusion(state, ts)
    timeout = active_timeout(state, ts)
    return {"excluded": exclusion is not None,
            "exclusion": exclusion,
            "timeout_active": timeout is not None,
            "timeout": timeout,
            "wagering_adjacent_allowed":
                exclusion is None and timeout is None,
            "active_limits": [lim for lim in state["limits"]
                              if lim["state"] == "active"],
            "resources": resource_block(state, ts)}


def check_rg(state, ts, what: str) -> dict:
    """The enforcement check every wagering-adjacent component
    consults (spec 3.2/3.3). Raises on exclusion/timeout."""
    status = rg_status(state, ts)
    if status["excluded"]:
        record = status["exclusion"]
        emit_receipt(state, "rg_denied", {
            "what": what, "reason": "EXCLUDED",
            "exclusion_id": record["id"], "verdict": "DENY"})
        raise ToolError(
            f"EXCLUDED: a self-exclusion is active (source: "
            f"{record['source']}, until "
            f"{record['legal_expiry']}), so {what} is denied — "
            f"for every function that could lead to a wager, "
            f"including 'just checking' (spec 3.3). Your records, "
            f"limits, and past-activity summaries remain "
            f"available. Help: {resources_text(state, ts)}")
    if status["timeout_active"]:
        record = status["timeout"]
        emit_receipt(state, "rg_denied", {
            "what": what, "reason": "TIMEOUT_ACTIVE",
            "timeout_id": record["id"], "verdict": "DENY"})
        raise ToolError(
            f"TIMEOUT_ACTIVE: a self-imposed timeout runs until "
            f"{record['ends_at']}, so {what} is denied for its "
            f"term (spec 3.2). A timeout cannot be shortened by "
            f"anyone, including you, inside this suite.")
    return status


def require_profile(state):
    if not state.get("profile"):
        raise ToolError(
            "PROFILE_REQUIRED: set the profile first (profile_set "
            "with declared state + birth year). One profile = one "
            "legal person; profiles for other people do not exist "
            "(spec 3.1/9)")
    return state["profile"]


# --------------------------------------------------------- jurisdiction
def matrix_row(state, state_code, product_class):
    for row in state["matrix_loaded"]["rows"]:
        if row["state"] == state_code and row["class"] \
                == product_class:
            return row
    return None


def jurisdiction_verdict(state, ts, product_class,
                         state_code=None) -> dict:
    """Receipted verdict (spec 4). Stale matrix or missing row
    degrades to UNKNOWN, and UNKNOWN denies."""
    profile = require_profile(state)
    code = (state_code or profile["state"]).upper()
    matrix = state["matrix_loaded"]
    as_of_ts = iso_to_ts(matrix["as_of"] + "T00:00:00Z")
    stale = ts > as_of_ts + matrix["ttl_days"] * 86400
    row = None if stale else matrix_row(state, code, product_class)
    if stale:
        verdict, raw = "UNKNOWN", "MATRIX_STALE"
    elif row is None:
        verdict, raw = "UNKNOWN", "NO_ROW"
    else:
        raw = row["status"]
        verdict = LEGAL_VERDICTS.get(raw, "NOT_LEGAL")
        age = profile_age(state, ts)
        if verdict == "ALLOWED" and age is not None \
                and age < row["age_floor"]:
            verdict, raw = "NOT_LEGAL", "AGE_FLOOR"
    receipt = emit_receipt(state, "jurisdiction_verdict", {
        "state": code, "product_class": product_class,
        "matrix_version": matrix["version"], "row_status": raw,
        "verdict": verdict, "stale_matrix": stale})
    return {"verdict": verdict, "row_status": raw, "state": code,
            "product_class": product_class,
            "matrix_version": matrix["version"],
            "matrix_as_of": matrix["as_of"], "stale_matrix": stale,
            "age_floor": row["age_floor"] if row else None,
            "source": row["source"] if row else None,
            "receipt_seq": receipt["seq"]}


def profile_age(state, ts):
    profile = state.get("profile") or {}
    birth_year = profile.get("birth_year")
    if not birth_year:
        return None
    year = datetime.fromtimestamp(ts, timezone.utc).year
    return year - int(birth_year)


def check_jurisdiction(state, ts, product_class, what) -> dict:
    verdict = jurisdiction_verdict(state, ts, product_class)
    if verdict["verdict"] != "ALLOWED":
        raise ToolError(
            f"JURISDICTION_{verdict['verdict']}: {what} is denied "
            f"for {verdict['state']} / {product_class} "
            f"(row status: {verdict['row_status']}, matrix "
            f"{verdict['matrix_version']} as of "
            f"{verdict['matrix_as_of']}). Your records here remain "
            f"available. Matrix verdicts are information as of "
            f"their source date, not legal advice; operators make "
            f"their own eligibility determinations (spec 4)")
    return verdict

# --------------------------------------------------------- limits core
def limit_key(kind, window, platform):
    return f"{kind}|{window}|{platform or 'suite'}"


def effective_limit(state, kind, window, platform=None):
    """Latest ACTIVE limit for the key, or None. Pending increases
    are visible in state['pending_limits'] and never effective."""
    key = limit_key(kind, window, platform)
    current = None
    for record in state["limits"]:
        if record["key"] == key and record["state"] == "active":
            current = record
    return current


def increase_delay_hours(state, kind, window) -> int:
    """The stricter of suite floor (by window) and the state
    fixture for deposit limits (spec 3.2: the maximum governs)."""
    delay = int(POLICY["increase_delay_hours"][
        window if window in POLICY["increase_delay_hours"]
        else "per_bet"])
    profile = state.get("profile") or {}
    state_days = state["matrix_loaded"].get(
        "state_deposit_increase_delay_days", {}).get(
            profile.get("state", ""))
    if kind == "deposit" and state_days:
        delay = max(delay, int(state_days) * 24)
    return delay


def apply_limit(state, ts, kind, window, amount, platform, via):
    record = {"key": limit_key(kind, window, platform),
              "kind": kind, "window": window,
              "platform": platform, "amount": amount,
              "state": "active", "set_at": now_iso(ts), "via": via}
    state["limits"].append(record)
    return record


def expire_lapsed_pending(state, ts):
    """A pending increase not confirmed in its window lapses."""
    confirm_window = int(POLICY["confirm_window_hours"]) * 3600
    for pending in state["pending_limits"]:
        if pending["state"] == "pending" and ts > \
                pending["confirm_by_ts"]:
            pending["state"] = "lapsed"
            emit_receipt(state, "limit_increase_lapsed", {
                "key": pending["key"],
                "requested_amount": pending["amount"],
                "effective_at": pending["effective_at"]})


def t_profile_set(state, args):
    ts = ts_of(args, state)
    reject_credentials(args)
    code = str(args.get("state") or "").upper()
    if len(code) != 2:
        raise ToolError("profile_set requires a 2-letter state")
    birth_year = args.get("birth_year")
    if not birth_year or not (1900 < int(birth_year) < 2100):
        raise ToolError(
            "profile_set requires birth_year (age attestation, "
            "spec 9: no minors; attestation, not ID verification "
            "— scope per owner decision D6)")
    if state.get("profile"):
        raise ToolError(
            "PROFILE_EXISTS: one profile = one legal person "
            "(spec 3.1); profiles for other people do not exist")
    profile = {"state": code, "birth_year": int(birth_year),
               "basis": str(args.get("basis") or "residence"),
               "attested_at": now_iso(ts)}
    state["profile"] = profile
    receipt = emit_receipt(state, "profile_set", {
        "state": code, "basis": profile["basis"],
        "age_at_attestation": profile_age(state, ts)})
    return {"profile": profile, "descriptor": DESCRIPTOR,
            "receipt_seq": receipt["seq"]}


def t_profile_get(state, args):
    ts = ts_of(args, state)
    profile = state.get("profile")
    status = rg_status(state, ts)
    return {"profile": profile, "descriptor": DESCRIPTOR,
            "rg_status": {"excluded": status["excluded"],
                          "timeout_active": status["timeout_active"],
                          "wagering_adjacent_allowed":
                              status["wagering_adjacent_allowed"]},
            "resources": status["resources"]}


def t_limit_set(state, args):
    """The asymmetry law (spec 3.2): a decrease applies in this
    same call; an increase becomes PENDING — delay + fresh
    confirmation — and no other path exists."""
    ts = ts_of(args, state)
    require_profile(state)
    kind = str(args.get("kind") or "")
    window = str(args.get("window") or "")
    if kind not in LIMIT_KINDS:
        raise ToolError(f"unknown limit kind '{kind}' "
                        f"(kinds: {sorted(LIMIT_KINDS)})")
    if window not in LIMIT_WINDOWS:
        raise ToolError(f"unknown limit window '{window}' "
                        f"(windows: {sorted(LIMIT_WINDOWS)})")
    amount = args.get("amount")
    if amount is None or float(amount) < 0:
        raise ToolError("limit_set requires amount >= 0")
    amount = float(amount)
    platform = args.get("platform")
    expire_lapsed_pending(state, ts)
    current = effective_limit(state, kind, window, platform)
    flags = pattern_flags(state, ts)
    if current is not None and amount == current["amount"]:
        return {"result": "UNCHANGED", "kind": kind,
                "window": window, "amount": amount}
    if current is None or amount < current["amount"]:
        # Initial set or DECREASE: immediate (spec 3.2).
        state["pending_limits"] = [
            p for p in state["pending_limits"]
            if not (p["key"] == limit_key(kind, window, platform)
                    and p["state"] == "pending")]
        record = apply_limit(state, ts, kind, window, amount,
                             platform, via="limit_set")
        receipt = emit_receipt(state, "limit_applied", {
            "key": record["key"], "amount": amount,
            "direction":
                "initial" if current is None else "decrease",
            "effective": "immediate"})
        return {"result": "APPLIED_IMMEDIATELY", "kind": kind,
                "window": window, "amount": amount,
                "direction":
                    "initial" if current is None else "decrease",
                "receipt_seq": receipt["seq"]}
    # INCREASE: pending only — never effective in this call.
    delay_h = increase_delay_hours(state, kind, window)
    effective_ts = ts + delay_h * 3600
    confirm_by = effective_ts + int(
        POLICY["confirm_window_hours"]) * 3600
    pending = {"key": limit_key(kind, window, platform),
               "kind": kind, "window": window,
               "platform": platform, "amount": amount,
               "prior_amount": current["amount"],
               "requested_at": now_iso(ts),
               "effective_at": now_iso(effective_ts),
               "effective_ts": effective_ts,
               "confirm_by_ts": confirm_by,
               "confirm_by": now_iso(confirm_by),
               "delay_hours": delay_h, "state": "pending",
               "requested_during_flags": [f["flag"] for f in flags]}
    state["pending_limits"] = [
        p for p in state["pending_limits"]
        if not (p["key"] == pending["key"]
                and p["state"] == "pending")]
    state["pending_limits"].append(pending)
    receipt = emit_receipt(state, "limit_increase_pending", {
        "key": pending["key"], "amount": amount,
        "prior_amount": current["amount"], "delay_hours": delay_h,
        "effective_at": pending["effective_at"],
        "requested_during_flags": pending["requested_during_flags"]})
    out = {"result": "PENDING_INCREASE", "kind": kind,
           "window": window, "amount": amount,
           "current_effective_amount": current["amount"],
           "delay_hours": delay_h,
           "effective_at": pending["effective_at"],
           "confirm_by": pending["confirm_by"],
           "note": ("An increase takes effect only after the "
                    "cooling delay AND a fresh confirmation "
                    "(limit_confirm) inside its window; "
                    "unconfirmed, it lapses. The current limit "
                    "stays in force meanwhile (spec 3.2)."),
           "receipt_seq": receipt["seq"]}
    if flags:
        out["resources"] = resource_block(state, ts)
        out["note"] += (" Requested during an active pattern "
                        "flag; the delay and the flag are restated "
                        "factually (spec 3.2/3.5).")
    return out


def t_limit_confirm(state, args):
    ts = ts_of(args, state)
    require_profile(state)
    kind = str(args.get("kind") or "")
    window = str(args.get("window") or "")
    platform = args.get("platform")
    key = limit_key(kind, window, platform)
    expire_lapsed_pending(state, ts)
    pending = next((p for p in state["pending_limits"]
                    if p["key"] == key and p["state"] == "pending"),
                   None)
    if pending is None:
        lapsed = next((p for p in reversed(state["pending_limits"])
                       if p["key"] == key
                       and p["state"] == "lapsed"), None)
        if lapsed:
            raise ToolError(
                f"LIMIT_INCREASE_LAPSED: the pending increase "
                f"for {key} was not confirmed inside its window "
                f"and has lapsed (spec 3.2). Request it again if "
                f"you still want it; the delay runs again.")
        raise ToolError(
            f"NO_PENDING_INCREASE for {key} — there is nothing "
            f"to confirm")
    if ts < pending["effective_ts"]:
        raise ToolError(
            f"LIMIT_INCREASE_PENDING: the increase for {key} "
            f"cannot take effect before {pending['effective_at']} "
            f"(cooling delay {pending['delay_hours']}h, spec "
            f"3.2). The current limit stays in force.")
    pending["state"] = "confirmed"
    record = apply_limit(state, ts, kind, window,
                         pending["amount"], platform,
                         via="limit_confirm_after_delay")
    receipt = emit_receipt(state, "limit_increase_confirmed", {
        "key": key, "amount": pending["amount"],
        "requested_at": pending["requested_at"],
        "effective_at": pending["effective_at"]})
    return {"result": "INCREASE_EFFECTIVE", "kind": kind,
            "window": window, "amount": pending["amount"],
            "receipt_seq": receipt["seq"]}


def t_limits_list(state, args):
    ts = ts_of(args, state)
    expire_lapsed_pending(state, ts)
    active = {}
    for record in state["limits"]:
        if record["state"] == "active":
            active[record["key"]] = record
    return {"active_limits": list(active.values()),
            "pending_increases": [p for p in state["pending_limits"]
                                  if p["state"] == "pending"],
            "history": state["limits"],
            "honest_scope": (
                "Suite limits govern what this tool will help "
                "with; they do not change your limits at any "
                "operator. Set matching limits at each book "
                "(spec 3.2).")}


def t_timeout_start(state, args):
    ts = ts_of(args, state)
    require_profile(state)
    days = int(args.get("days") or 0)
    if not (3 <= days <= 365):
        raise ToolError(
            "timeout_start requires days in 3..365 (operator "
            "pattern, spec 3.2)")
    record = {"id": f"timeout-{len(state['timeouts']) + 1}",
              "days": days, "started_at": now_iso(ts),
              "ends_ts": ts + days * 86400,
              "ends_at": now_iso(ts + days * 86400),
              "status": "active"}
    state["timeouts"].append(record)
    receipt = emit_receipt(state, "timeout_started", {
        "timeout_id": record["id"], "days": days,
        "ends_at": record["ends_at"]})
    return {"timeout": record, "receipt_seq": receipt["seq"],
            "note": ("During a timeout, wagering-adjacent "
                     "functions deny exactly as in exclusion, "
                     "and the timeout cannot be shortened by "
                     "anyone (spec 3.2).")}


def t_exclusion_start(state, args):
    """Easy by construction: one call, any source, honored
    identically (spec 3.3)."""
    ts = ts_of(args, state)
    require_profile(state)
    source = str(args.get("source") or "self-declared")
    if source not in ("operator", "state-program", "nvsep",
                      "self-declared"):
        raise ToolError(
            f"unknown exclusion source '{source}' (operator / "
            f"state-program / nvsep / self-declared — all honored "
            f"identically, spec 3.3)")
    expiry = args.get("legal_expiry")
    term_days = args.get("term_days")
    if expiry:
        expiry_ts = iso_to_ts(str(expiry))
        expiry_iso = now_iso(expiry_ts)
    elif term_days:
        expiry_ts = ts + int(term_days) * 86400
        expiry_iso = now_iso(expiry_ts)
    else:
        raise ToolError(
            "exclusion_start requires legal_expiry (ISO) or "
            "term_days — the exclusion's OWN legal term, as "
            "recorded from its source (spec 3.3)")
    if active_exclusion(state, ts):
        return {"result": "ALREADY_EXCLUDED",
                "exclusion": active_exclusion(state, ts),
                "resources": resource_block(state, ts)}
    record = {"id": f"excl-{len(state['exclusions']) + 1}",
              "source": source,
              "scope": str(args.get("scope") or "all-suite"),
              "started_at": now_iso(ts),
              "legal_expiry": expiry_iso,
              "legal_expiry_ts": expiry_ts, "status": "active"}
    state["exclusions"].append(record)
    receipt = emit_receipt(state, "exclusion_started", {
        "exclusion_id": record["id"], "source": source,
        "legal_expiry": expiry_iso})
    return {"exclusion": record, "receipt_seq": receipt["seq"],
            "resources": resource_block(state, ts),
            "note": ("Exclusion is active now. Every function "
                     "that could lead to a wager denies while it "
                     "is active; no tool in this suite can end it "
                     "before its legal expiry (spec 3.3).")}


def t_exclusion_end(state, args):
    """The refusal machine (spec 3.3): before the exclusion's
    own legal expiry this ALWAYS refuses; after expiry,
    reactivation requires the source record expired + a fresh
    jurisdiction verdict + limits re-confirmation."""
    ts = ts_of(args, state)
    require_profile(state)
    record = next((e for e in reversed(state["exclusions"])
                   if e["status"] == "active"), None)
    if record is None:
        raise ToolError("NO_ACTIVE_EXCLUSION to end")
    if ts < record["legal_expiry_ts"]:
        emit_receipt(state, "exclusion_end_refused", {
            "exclusion_id": record["id"],
            "reason": "BEFORE_LEGAL_EXPIRY",
            "legal_expiry": record["legal_expiry"]})
        raise ToolError(
            f"EXCLUSION_IRREVOCABLE_UNTIL_EXPIRY: this exclusion "
            f"runs to its recorded legal expiry "
            f"({record['legal_expiry']}) and no tool in this "
            f"suite can end it early — easy to start, impossible "
            f"to un-exclude early, by construction (spec 3.3). "
            f"Help: {resources_text(state, ts)}")
    missing = []
    if not args.get("jurisdiction_rechecked"):
        missing.append("fresh jurisdiction verdict")
    if not args.get("limits_reconfirmed"):
        missing.append("limits re-confirmation")
    if missing:
        raise ToolError(
            f"REACTIVATION_INCOMPLETE: the exclusion term has "
            f"expired, but reactivation requires "
            f"{' + '.join(missing)} (spec 3.3)")
    record["status"] = "expired"
    receipt = emit_receipt(state, "exclusion_expired_reactivated", {
        "exclusion_id": record["id"],
        "legal_expiry": record["legal_expiry"]})
    return {"result": "EXCLUSION_EXPIRED", "exclusion": record,
            "receipt_seq": receipt["seq"]}


def t_exclusion_status(state, args):
    ts = ts_of(args, state)
    status = rg_status(state, ts)
    return {"excluded": status["excluded"],
            "exclusion": status["exclusion"],
            "all_exclusions": state["exclusions"],
            "timeout_active": status["timeout_active"],
            "resources": status["resources"]}


def t_jurisdiction_check(state, args):
    ts = ts_of(args, state)
    product_class = str(args.get("product_class") or "")
    if product_class not in PRODUCT_CLASSES:
        raise ToolError(
            f"unknown product_class '{product_class}' "
            f"(classes: {sorted(PRODUCT_CLASSES)})")
    return jurisdiction_verdict(state, ts, product_class,
                                args.get("state"))


def t_matrix_status(state, args):
    ts = ts_of(args, state)
    matrix = state["matrix_loaded"]
    as_of_ts = iso_to_ts(matrix["as_of"] + "T00:00:00Z")
    stale_at = as_of_ts + matrix["ttl_days"] * 86400
    return {"version": matrix["version"], "as_of": matrix["as_of"],
            "ttl_days": matrix["ttl_days"],
            "source": matrix["source"],
            "rows": len(matrix["rows"]),
            "stale": ts > stale_at,
            "stale_after": now_iso(stale_at),
            "note": ("A matrix older than its TTL degrades "
                     "verdicts to UNKNOWN = deny (spec 4).")}

# ---------------------------------------------------------------- records
def record_cash_view(record) -> dict:
    """Cash truth per record (spec 3.4): a bonus bet's stake is
    not cash and is never returned; unsettled bonus instruments
    are worth zero in cash P&L."""
    bonus = record["bonus_type"]
    cash_stake = record["stake"] if bonus == "none" else 0.0
    settled = record["settlement"] != "pending"
    payout = float(record.get("payout") or 0) if settled else 0.0
    return {"record_id": record["id"], "book": record["book"],
            "event": record["event"], "market": record["market"],
            "odds": record["odds"], "stake": record["stake"],
            "bonus_type": bonus,
            "cash_stake": cash_stake,
            "stake_returned": bonus == "none",
            "settlement": record["settlement"],
            "payout": payout if settled else None,
            "cash_net": (payout - cash_stake) if settled else 0.0,
            "bonus_note": (
                "Bonus instrument: stake is not returned and it "
                "is valued at $0 in cash P&L until settled "
                "(spec 3.4)." if bonus != "none" else None),
            "placed_at": record["placed_at"],
            "source": record["source"]}


def compute_pnl(state) -> dict:
    """Headline = cash net position, reproducible from the raw
    records by an independent recomputation (spec 13.5)."""
    views = [record_cash_view(r) for r in state["records"]]
    settled = [v for v in views if v["settlement"] != "pending"]
    cash_staked = round(sum(v["cash_stake"] for v in settled), 2)
    payouts = round(sum(v["payout"] or 0 for v in settled), 2)
    return {"views": views,
            "cash_staked_settled": cash_staked,
            "cash_payouts_settled": payouts,
            "cash_net": round(payouts - cash_staked, 2),
            "pending_count": len(views) - len(settled),
            "unsettled_bonus_value_in_cash_pnl": 0.0}


def pattern_flags(state, ts) -> list:
    """NJ-trigger shapes (spec 1.4/3.4), computed on ledger data
    only. Surfaced as facts; never as engagement hooks."""
    flags = []
    records = state["records"]
    day = 86400
    recent = [r for r in records
              if ts - r["placed_ts"] <= 7 * day]
    prior = [r for r in records
             if 7 * day < ts - r["placed_ts"] <= 14 * day]
    stake_recent = sum(r["stake"] for r in recent)
    stake_prior = sum(r["stake"] for r in prior)
    if prior and stake_prior > 0 and stake_recent >= 1.5 * stake_prior:
        flags.append({
            "flag": "stake_velocity_up",
            "fact": (f"Last 7 days: {len(recent)} bets staking "
                     f"${stake_recent:.2f} vs prior 7 days "
                     f"${stake_prior:.2f} "
                     f"(+{(stake_recent / stake_prior - 1) * 100:.0f}%)."),
            "partial_view_note": PARTIAL_VIEW_NOTE})
    by_day = {}
    for record in sorted(records, key=lambda r: r["placed_ts"]):
        by_day.setdefault(record["placed_ts"] // day, []).append(
            record)
    chasing_days = 0
    for day_records in by_day.values():
        for i, record in enumerate(day_records):
            if record["settlement"] != "lost":
                continue
            later = [r for r in day_records[i + 1:]
                     if r["stake"] >= 1.5 * record["stake"]]
            if later:
                chasing_days += 1
                break
    if chasing_days:
        flags.append({
            "flag": "loss_chasing_signature",
            "fact": (f"On {chasing_days} day(s), a stake at "
                     f"least 50% larger followed a loss the same "
                     f"day — the loss-chasing pattern."),
            "partial_view_note": PARTIAL_VIEW_NOTE})
    near_zero_days = 0
    for day_records in by_day.values():
        settled = [r for r in day_records
                   if r["settlement"] != "pending"]
        if len(settled) >= 3:
            net = sum(record_cash_view(r)["cash_net"]
                      for r in settled)
            staked = sum(record_cash_view(r)["cash_stake"]
                         for r in settled)
            if staked > 0 and net <= -0.9 * staked:
                near_zero_days += 1
    if near_zero_days:
        flags.append({
            "flag": "sessions_ending_near_zero",
            "fact": (f"{near_zero_days} day(s) with 3+ settled "
                     f"bets ended at a cash loss of 90%+ of the "
                     f"day's cash stakes."),
            "partial_view_note": PARTIAL_VIEW_NOTE})
    dep_recent = sum(d["amount"] for d in state["deposits"]
                     if ts - d["ts"] <= 7 * day)
    dep_prior = sum(d["amount"] for d in state["deposits"]
                    if 7 * day < ts - d["ts"] <= 14 * day)
    if dep_prior > 0 and dep_recent >= 1.5 * dep_prior:
        flags.append({
            "flag": "deposit_velocity_up",
            "fact": (f"Deposits last 7 days ${dep_recent:.2f} vs "
                     f"prior 7 days ${dep_prior:.2f}."),
            "partial_view_note": PARTIAL_VIEW_NOTE})
    increases = [p for p in state["pending_limits"]
                 if ts - iso_to_ts(p["requested_at"]) <= 30 * day]
    confirmed = [r for r in state["receipts"]
                 if r["type"] == "limit_increase_confirmed"
                 and ts - r["ts"] <= 30 * day]
    if len(increases) + len(confirmed) >= 2:
        flags.append({
            "flag": "repeated_limit_increase_requests",
            "fact": (f"{len(increases) + len(confirmed)} limit "
                     f"increase request(s) in the last 30 days."),
            "partial_view_note": PARTIAL_VIEW_NOTE})
    return flags


def t_bet_record_add(state, args):
    ts = ts_of(args, state)
    require_profile(state)
    placed_ts = float(args.get("placed_ts") or ts)
    settlement = str(args.get("settlement") or "pending")
    if settlement not in ("pending", "won", "lost", "push", "void"):
        raise ToolError(f"unknown settlement '{settlement}'")
    bonus_type = str(args.get("bonus_type") or "none")
    if bonus_type not in ("none", "bonus_bet", "bonus_funds"):
        raise ToolError(f"unknown bonus_type '{bonus_type}'")
    status = rg_status(state, ts)
    if status["excluded"]:
        exclusion = status["exclusion"]
        backfill = placed_ts < iso_to_ts(
            exclusion["started_at"]) and settlement != "pending"
        if not backfill:
            emit_receipt(state, "record_add_denied", {
                "reason": "EXCLUDED", "verdict": "DENY"})
            raise ToolError(
                f"EXCLUDED: recording a new bet is a function "
                f"that could lead to a wager and is denied while "
                f"an exclusion is active (spec 3.3). Bets placed "
                f"before the exclusion that are already settled "
                f"may still be backfilled as history. Help: "
                f"{resources_text(state, ts)}")
    record = {"id": f"bet-{len(state['records']) + 1}",
              "book": str(args.get("book") or ""),
              "event": str(args.get("event") or ""),
              "market": str(args.get("market") or "h2h"),
              "selection": str(args.get("selection") or ""),
              "odds": args.get("odds"),
              "stake": float(args.get("stake") or 0),
              "bonus_type": bonus_type,
              "placed_ts": placed_ts,
              "placed_at": now_iso(placed_ts),
              "settlement": settlement,
              "payout": args.get("payout"),
              "source": str(args.get("source")
                            or "manual-entry"),
              "data_rights": {
                  "source": "the profile holder's own records",
                  "legal_basis": "user-provided",
                  "license": "n/a — user's own data",
                  "method": str(args.get("source")
                                or "manual-entry"),
                  "retention": "local profile only (spec 10)"}}
    if not record["book"] or not record["event"] \
            or record["stake"] <= 0:
        raise ToolError(
            "bet_record_add requires book, event, stake > 0")
    state["records"].append(record)
    receipt = emit_receipt(state, "bet_record_added", {
        "record_id": record["id"], "book": record["book"],
        "bonus_type": bonus_type, "settlement": settlement,
        "verdict": "ALLOW"})
    return {"record": record_cash_view(record),
            "receipt_seq": receipt["seq"]}


def t_records_list(state, args):
    return {"records": [record_cash_view(r)
                        for r in state["records"]],
            "count": len(state["records"]),
            "raw_records": state["records"]}


def t_deposit_record_add(state, args):
    ts = ts_of(args, state)
    require_profile(state)
    amount = float(args.get("amount") or 0)
    if amount <= 0:
        raise ToolError("deposit_record_add requires amount > 0")
    entry = {"id": f"dep-{len(state['deposits']) + 1}",
             "amount": amount, "ts": ts, "at": now_iso(ts),
             "book": str(args.get("book") or "")}
    state["deposits"].append(entry)
    limit = effective_limit(state, "deposit", "daily")
    fact = None
    if limit:
        day_total = sum(d["amount"] for d in state["deposits"]
                        if ts - d["ts"] <= 86400)
        if day_total > limit["amount"]:
            fact = (f"Fact, stated plainly: deposits in the "
                    f"last 24h total ${day_total:.2f}, above "
                    f"the daily deposit limit of "
                    f"${limit['amount']:.2f} you set for "
                    f"yourself. Suite limits govern what this "
                    f"tool will help with; they do not change "
                    f"your limits at any operator (spec 3.2).")
    receipt = emit_receipt(state, "deposit_recorded", {
        "deposit_id": entry["id"], "amount": amount,
        "over_limit_fact": fact is not None})
    out = {"deposit": entry, "receipt_seq": receipt["seq"]}
    if fact:
        out["limit_fact"] = fact
        out["resources"] = resource_block(state, ts)
    return out


def t_pnl_summary(state, args):
    """The periodic summary: leads with cash net position and
    ALWAYS carries the resource block (spec 3.5)."""
    ts = ts_of(args, state)
    pnl = compute_pnl(state)
    flags = pattern_flags(state, ts)
    out = {"cash_net_position": pnl["cash_net"],
           "cash_staked_settled": pnl["cash_staked_settled"],
           "cash_payouts_settled": pnl["cash_payouts_settled"],
           "pending_records": pnl["pending_count"],
           "unsettled_bonus_value_in_cash_pnl":
               pnl["unsettled_bonus_value_in_cash_pnl"],
           "records": pnl["views"],
           "pattern_flags": flags,
           "partial_view_note": PARTIAL_VIEW_NOTE,
           "resources": resource_block(state, ts)}
    lint_output(canon(out))
    return out


def t_reality_snapshot(state, args):
    ts = ts_of(args, state)
    pnl = compute_pnl(state)
    flags = pattern_flags(state, ts)
    status = rg_status(state, ts)
    out = {"cash_net_position": pnl["cash_net"],
           "records_count": len(state["records"]),
           "deposits_total": round(
               sum(d["amount"] for d in state["deposits"]), 2),
           "pattern_flags": flags,
           "partial_view_note": PARTIAL_VIEW_NOTE,
           "excluded": status["excluded"],
           "timeout_active": status["timeout_active"],
           "active_limits": status["active_limits"]}
    if flags or status["excluded"]:
        out["resources"] = resource_block(state, ts)
    lint_output(canon(out))
    return out


# ------------------------------------------------------------------- odds
def implied_prob(american) -> float:
    price = float(american)
    if price < 0:
        return (-price) / ((-price) + 100.0)
    return 100.0 / (price + 100.0)


def find_event(state, event_id):
    for event in state["odds"]:
        if event["id"] == event_id:
            return event
    raise ToolError(f"unknown fixture event: {event_id}")


def odds_rows(state, ts, event) -> dict:
    """Price rows per outcome, ordered by PRICE ONLY (best price
    first) — no other ranking input exists (spec 5.1/8).
    Promotions are stripped by construction (spec 3.6): a book's
    promo text is never a surface."""
    outcomes = {}
    promos_stripped = 0
    book_sums = {}
    for book in event["bookmakers"]:
        if "promo" in book:
            promos_stripped += 1
        for market in book["markets"]:
            if market["key"] != "h2h":
                continue
            total = sum(implied_prob(o["price"])
                        for o in market["outcomes"])
            book_sums[book["key"]] = round(total * 100, 1)
            stale_age = ts - iso_to_ts(book["last_update"])
            for outcome in market["outcomes"]:
                outcomes.setdefault(outcome["name"], []).append({
                    "book": book["title"], "book_key": book["key"],
                    "price_american": outcome["price"],
                    "implied_prob": round(
                        implied_prob(outcome["price"]) * 100, 2),
                    "feed_timestamp": book["last_update"],
                    "stale": stale_age > 900,
                    "stale_age_seconds":
                        int(stale_age) if stale_age > 900 else None})
    for name in outcomes:
        # PRICE ONLY ordering (spec 5.1/8): lowest implied
        # probability = best price for the bettor = first.
        outcomes[name].sort(key=lambda r: r["implied_prob"])
    return {"outcomes": outcomes, "book_market_sums_pct": book_sums,
            "promotions_stripped": promos_stripped}


def odds_surface(state, ts, event, verdict, status) -> dict:
    rows = odds_rows(state, ts, event)
    return {"event_id": event["id"],
            "sport": event["sport_title"],
            "matchup": f"{event['home_team']} vs "
                       f"{event['away_team']}",
            "commence_time": event["commence_time"],
            "feed": event["feed"],
            "feed_as_of": event["feed_as_of"],
            "data_rights": event["data_rights"],
            "prices": rows["outcomes"],
            "book_market_sums_pct": rows["book_market_sums_pct"],
            "promotions_stripped": rows["promotions_stripped"],
            "price_truth_note": (
                "Prices are data with a timestamp and a source, "
                "never a promise: a displayed price can be "
                "stale, can move, and can be refused by the book "
                "(spec 5.1). The market sum shows the margin: "
                "100% is fair; above it is what the market "
                "charges."),
            "jurisdiction_verdict": {
                "verdict": verdict["verdict"],
                "receipt_seq": verdict["receipt_seq"],
                "matrix_version": verdict["matrix_version"]},
            "rg_status": {
                "excluded": status["excluded"],
                "timeout_active": status["timeout_active"],
                "active_limit_keys": [
                    lim["key"] for lim in status["active_limits"]]},
            "recommendation": None}


def t_odds_compare(state, args):
    ts = ts_of(args, state)
    require_profile(state)
    status = check_rg(state, ts, "odds comparison")
    verdict = check_jurisdiction(state, ts, "sportsbook",
                                 "odds comparison")
    event = find_event(state, args.get("event_id"))
    out = odds_surface(state, ts, event, verdict, status)
    emit_receipt(state, "odds_compared", {
        "event_id": event["id"], "verdict": "ALLOW",
        "jurisdiction_receipt": verdict["receipt_seq"]})
    lint_output(canon(out))
    return out


def t_arb_observe(state, args):
    """Market observation only, with its mandatory honesty
    attached (spec 5.4/1.5). No execution support exists."""
    ts = ts_of(args, state)
    require_profile(state)
    status = check_rg(state, ts, "arbitrage observation")
    verdict = check_jurisdiction(state, ts, "sportsbook",
                                 "arbitrage observation")
    event = find_event(state, args.get("event_id"))
    rows = odds_rows(state, ts, event)
    best = {}
    for name, book_rows in rows["outcomes"].items():
        best[name] = min(book_rows,
                         key=lambda r: r["implied_prob"])
    total = round(sum(r["implied_prob"] for r in best.values()), 2)
    out = {"event_id": event["id"],
           "matchup": f"{event['home_team']} vs "
                      f"{event['away_team']}",
           "best_prices": best,
           "best_price_implied_sum_pct": total,
           "observation": (
               "cross-book difference present"
               if total < 100 else
               "no cross-book difference below 100% at the "
               "shown prices"),
           "mandatory_honesty": ARB_WARNING,
           "execution_support": None,
           "jurisdiction_verdict": {
               "verdict": verdict["verdict"],
               "receipt_seq": verdict["receipt_seq"]},
           "rg_status": {
               "excluded": status["excluded"],
               "active_limit_keys": [
                   lim["key"] for lim in status["active_limits"]]}}
    emit_receipt(state, "arb_observed", {
        "event_id": event["id"], "implied_sum_pct": total,
        "verdict": "ALLOW"})
    lint_output(canon(out))
    return out


# -------------------------------------------------------------- slip prep
def window_stakes(state, ts, window):
    seconds = WINDOW_SECONDS[window]
    if seconds == 0:
        return sum(r["stake"] for r in state["records"])
    return sum(r["stake"] for r in state["records"]
               if ts - r["placed_ts"] <= seconds)


def window_net_loss(state, ts, window):
    seconds = WINDOW_SECONDS[window]
    views = [record_cash_view(r) for r in state["records"]
             if r["settlement"] != "pending"
             and (seconds == 0 or ts - r["placed_ts"] <= seconds)]
    net = sum(v["cash_net"] for v in views)
    return max(0.0, -net)


def t_slip_prepare(state, args):
    """Prep is data (spec 5.3/6): evaluated against limits x
    jurisdiction x bankroll policy x exclusion, receipted with
    named reasons. No tool can submit the result."""
    ts = ts_of(args, state)
    require_profile(state)
    stake = float(args.get("stake") or 0)
    if stake <= 0:
        raise ToolError("slip_prepare requires stake > 0")
    try:
        status = check_rg(state, ts, "slip prep")
    except ToolError as exc:
        emit_receipt(state, "slip_prep_denied", {
            "reason": str(exc)[:60], "verdict": "EXCLUDED"})
        raise
    verdict = jurisdiction_verdict(state, ts, "sportsbook")
    if verdict["verdict"] != "ALLOWED":
        emit_receipt(state, "slip_prep_denied", {
            "reason": verdict["verdict"],
            "jurisdiction_receipt": verdict["receipt_seq"],
            "verdict": "DENY"})
        raise ToolError(
            f"PREP_DENIED[{verdict['verdict']}]: jurisdiction "
            f"verdict for {verdict['state']} / sportsbook is "
            f"{verdict['verdict']} (row: {verdict['row_status']})"
            f" — prep is a wagering-adjacent function (spec 4)")
    reasons = []
    wager_limit = effective_limit(state, "wager", "daily")
    if wager_limit and window_stakes(state, ts, "daily") + stake \
            > wager_limit["amount"]:
        reasons.append(
            f"OVER_LIMIT: daily wager limit "
            f"${wager_limit['amount']:.2f} would be exceeded")
    loss_limit = effective_limit(state, "loss", "daily")
    if loss_limit and window_net_loss(state, ts, "daily") \
            >= loss_limit["amount"]:
        reasons.append(
            f"OVER_LIMIT: daily loss limit "
            f"${loss_limit['amount']:.2f} already reached")
    stake_cap = effective_limit(state, "stake_cap", "per_bet")
    if stake_cap and stake > stake_cap["amount"]:
        reasons.append(
            f"OVER_POLICY: stake cap (bankroll policy) is "
            f"${stake_cap['amount']:.2f} per bet")
    pct_cap = effective_limit(state, "pct_cap", "per_bet")
    bankroll = effective_limit(state, "bankroll", "per_bet")
    if pct_cap and bankroll and stake > \
            bankroll["amount"] * pct_cap["amount"] / 100.0:
        reasons.append(
            f"OVER_POLICY: stake exceeds {pct_cap['amount']}% "
            f"of the declared bankroll "
            f"(${bankroll['amount']:.2f})")
    if reasons:
        emit_receipt(state, "slip_prep_denied", {
            "reasons": reasons, "stake": stake, "verdict": "DENY"})
        raise ToolError("PREP_DENIED: " + "; ".join(reasons))
    slip = {"slip_id": f"slip-{len(state['slips']) + 1}",
            "book": str(args.get("book") or ""),
            "event_id": str(args.get("event_id") or ""),
            "selection": str(args.get("selection") or ""),
            "odds": args.get("odds"), "stake": stake,
            "status": "prepared",
            "prepared_at": now_iso(ts),
            "jurisdiction_receipt": verdict["receipt_seq"],
            "note": ("A prepared slip is data. No tool in this "
                     "suite can submit it, and none ever will "
                     "in v1 (spec 6: T2 is an empty tier).")}
    state["slips"].append(slip)
    receipt = emit_receipt(state, "slip_prepared", {
        "slip_id": slip["slip_id"], "stake": stake,
        "verdict": "ALLOW_TO_PREP"})
    out = {"slip": slip, "prep_verdict": "ALLOW_TO_PREP",
           "receipt_seq": receipt["seq"],
           "rg_status": {"excluded": status["excluded"],
                         "active_limit_keys": [
                             lim["key"] for lim
                             in status["active_limits"]]}}
    lint_output(canon(out))
    return out


def t_advice_request(state, args):
    """Claims law (spec 9/13.7): a request for a pick, a
    guarantee, or a system gets the banned-class refusal. The
    suite reports prices and records; it does not pick winners,
    and analysis without a tracked record is never emitted."""
    ts = ts_of(args, state)
    emit_receipt(state, "advice_refused", {
        "reason": "CLAIMS_LAW", "verdict": "DENY"})
    raise ToolError(
        "CLAIMS_REFUSAL: this suite reports prices and records; "
        "it does not pick winners, and it offers no guarantee, "
        "edge, system, or lock — those are a banned output class "
        "(spec 2/9). Any analysis surface in this suite must be "
        "labeled opinion and carry its own settled track record "
        "or it is not emitted; none is in v1.")


def t_resources_get(state, args):
    ts = ts_of(args, state)
    return {"resources": resource_block(state, ts),
            "descriptor": DESCRIPTOR}


def t_receipt_list(state, args):
    limit = args.get("limit")
    receipts = state["receipts"]
    if limit is not None:
        receipts = receipts[-int(limit):]
    return {"receipts": receipts, "count": len(state["receipts"]),
            "chain_valid": verify_receipt_chain(state["receipts"])}

# ------------------------------------------------------- handler guard
def _credential_guard(fn):
    """Every handler refuses credential-shaped input by name,
    at any depth — enforced in the handlers themselves, not
    only at dispatch (spec 1.1/9)."""
    def wrapper(state, args):
        reject_credentials(args)
        return fn(state, args)
    return wrapper


for _name in [n for n in list(globals()) if n.startswith("t_")]:
    globals()[_name] = _credential_guard(globals()[_name])
del _name


# ------------------------------------------------------------------ tools
TOOLS = {
    "profile_set": (
        t_profile_set,
        "Set the single profile: declared state + birth year "
        "(age attestation, spec 9/D6). One profile = one legal "
        "person; profiles for other people do not exist.",
        {"state": {"type": "string"},
         "birth_year": {"type": "integer"},
         "basis": {"type": "string"},
         "at_ts": {"type": "number"}}, ["state", "birth_year"]),
    "profile_get": (
        t_profile_get,
        "Read the profile + RG status + the help-resource block. "
        "T0.",
        {"at_ts": {"type": "number"}}, []),
    "limit_set": (
        t_limit_set,
        "Set a limit (deposit/wager/loss/time/stake_cap/pct_cap/"
        "bankroll; window daily/weekly/monthly/per_bet). A "
        "DECREASE applies immediately. An INCREASE becomes "
        "pending for the cooling delay and needs limit_confirm "
        "afterwards; there is no path that raises a limit in "
        "one call (spec 3.2).",
        {"kind": {"type": "string"}, "window": {"type": "string"},
         "amount": {"type": "number"},
         "platform": {"type": "string"},
         "at_ts": {"type": "number"}},
        ["kind", "window", "amount"]),
    "limit_confirm": (
        t_limit_confirm,
        "Confirm a pending limit increase after its cooling "
        "delay; unconfirmed increases lapse (spec 3.2).",
        {"kind": {"type": "string"}, "window": {"type": "string"},
         "platform": {"type": "string"},
         "at_ts": {"type": "number"}}, ["kind", "window"]),
    "limits_list": (
        t_limits_list,
        "Active limits, pending increases, and full limit "
        "history. T0.",
        {"at_ts": {"type": "number"}}, []),
    "timeout_start": (
        t_timeout_start,
        "Start a self-imposed timeout (3-365 days): wagering-"
        "adjacent functions deny for its term, and it cannot be "
        "shortened by anyone (spec 3.2).",
        {"days": {"type": "integer"},
         "at_ts": {"type": "number"}}, ["days"]),
    "exclusion_start": (
        t_exclusion_start,
        "Start a self-exclusion — one call, any source (operator "
        "/ state-program / nvsep / self-declared), honored "
        "identically and immediately (spec 3.3).",
        {"source": {"type": "string"},
         "scope": {"type": "string"},
         "legal_expiry": {"type": "string"},
         "term_days": {"type": "integer"},
         "at_ts": {"type": "number"}}, []),
    "exclusion_end": (
        t_exclusion_end,
        "Ask to end an exclusion. Before its recorded legal "
        "expiry this always refuses — no tool can end an "
        "exclusion early (spec 3.3). After expiry, reactivation "
        "needs a fresh jurisdiction verdict + limits "
        "re-confirmation.",
        {"jurisdiction_rechecked": {"type": "boolean"},
         "limits_reconfirmed": {"type": "boolean"},
         "at_ts": {"type": "number"}}, []),
    "exclusion_status": (
        t_exclusion_status,
        "Exclusion state + history + resources. Answers even "
        "while excluded. T0.",
        {"at_ts": {"type": "number"}}, []),
    "jurisdiction_check": (
        t_jurisdiction_check,
        "Receipted verdict for (state, product class) from the "
        "versioned matrix. UNKNOWN (incl. stale matrix) denies "
        "wagering-adjacent functions (spec 4).",
        {"product_class": {"type": "string"},
         "state": {"type": "string"},
         "at_ts": {"type": "number"}}, ["product_class"]),
    "matrix_status": (
        t_matrix_status,
        "Jurisdiction matrix version, as-of, TTL, staleness. T0.",
        {"at_ts": {"type": "number"}}, []),
    "bet_record_add": (
        t_bet_record_add,
        "Add one of YOUR OWN bet records (manual entry or your "
        "export). Bonus stakes are recorded as bonus: not cash, "
        "never stake-returned, $0 in cash P&L until settled "
        "(spec 3.4/5.2). While excluded, new bets are refused; "
        "pre-exclusion settled history may be backfilled.",
        {"book": {"type": "string"}, "event": {"type": "string"},
         "market": {"type": "string"},
         "selection": {"type": "string"},
         "odds": {"type": "number"}, "stake": {"type": "number"},
         "bonus_type": {"type": "string"},
         "settlement": {"type": "string"},
         "payout": {"type": "number"},
         "placed_ts": {"type": "number"},
         "source": {"type": "string"},
         "at_ts": {"type": "number"}},
        ["book", "event", "stake"]),
    "records_list": (
        t_records_list,
        "Your records: cash views + the raw records they were "
        "computed from (P&L is independently reproducible). T0.",
        {"at_ts": {"type": "number"}}, []),
    "deposit_record_add": (
        t_deposit_record_add,
        "Record one of your own deposits. If it carries you "
        "over a deposit limit you set, that fact is stated "
        "plainly — the suite records facts; operator limits "
        "live at the operator (spec 3.2).",
        {"amount": {"type": "number"}, "book": {"type": "string"},
         "at_ts": {"type": "number"}}, ["amount"]),
    "pnl_summary": (
        t_pnl_summary,
        "Periodic summary: cash net position FIRST, wins never "
        "shown without the period's losses, pattern flags as "
        "facts, and the help-resource block — always (spec "
        "3.4/3.5).",
        {"at_ts": {"type": "number"}}, []),
    "reality_snapshot": (
        t_reality_snapshot,
        "Reality surface: net position, totals, pattern flags "
        "(ledger data only, partial-view note attached). T0.",
        {"at_ts": {"type": "number"}}, []),
    "odds_compare": (
        t_odds_compare,
        "Line shopping over FIXTURE prices (3 books): ordered "
        "by price only, margin shown, stale prices labeled, "
        "promotions stripped. Carries jurisdiction verdict + "
        "RG status refs. Data, never a recommendation "
        "(spec 5.1).",
        {"event_id": {"type": "string"},
         "at_ts": {"type": "number"}}, ["event_id"]),
    "arb_observe": (
        t_arb_observe,
        "Cross-book price observation with the mandatory "
        "honesty attached: books limit winning accounts, "
        "prices can be refused, both legs filling is never "
        "certain. Observation only — no execution support "
        "(spec 5.4).",
        {"event_id": {"type": "string"},
         "at_ts": {"type": "number"}}, ["event_id"]),
    "slip_prepare": (
        t_slip_prepare,
        "Prepare a slip as DATA: evaluated against limits x "
        "jurisdiction x bankroll policy x exclusion, with "
        "named verdicts. No tool in this suite can submit a "
        "prepared slip; T2 placement is an empty tier (spec "
        "5.3/6).",
        {"book": {"type": "string"}, "event_id": {"type": "string"},
         "selection": {"type": "string"},
         "odds": {"type": "number"}, "stake": {"type": "number"},
         "at_ts": {"type": "number"}}, ["stake"]),
    "advice_request": (
        t_advice_request,
        "Ask for a pick, a tip, a system, or an edge. The "
        "answer is the claims-law refusal, by construction: "
        "this suite reports prices and records and does not "
        "pick winners (spec 9).",
        {"question": {"type": "string"},
         "at_ts": {"type": "number"}}, ["question"]),
    "resources_get": (
        t_resources_get,
        "The help-resource block (build-verified fixture data "
        "with reverify marker). Always available, including "
        "while excluded (spec 3.5).",
        {"at_ts": {"type": "number"}}, []),
    "receipt_list": (
        t_receipt_list,
        "Append-only hash-chained receipts + chain "
        "verification. Denials are receipts too.",
        {"limit": {"type": "integer"}}, []),
}

# Capability denylist, enumerated in code (spec 6/9/13.2/13.6):
# NO placement verb, NO account connection, NO credential store,
# NO instant limit raise, NO early exclusion end, NO arb/stake
# execution calculator, NO session automation — at any tier, ever.
FORBIDDEN_TOOL_NAMES = {
    "place_bet", "submit_bet", "submit_slip", "confirm_bet",
    "place_wager", "connect_account", "link_account", "login",
    "session_login", "scrape_odds", "scrape_book",
    "limit_raise_now", "raise_limit_now", "limit_remove",
    "exclusion_end_early", "exclusion_lift", "unexclude",
    "timeout_end", "timeout_cancel",
    "arb_calculator", "arb_stake_calculator", "stake_calculator",
    "kelly_calculator", "pick_generator", "tip_generator",
    "bet_for_other", "proxy_bet",
}


def tool_list():
    return [{"name": name, "description": description,
             "inputSchema": {"type": "object", "properties": props,
                             "required": required}}
            for name, (_, description, props, required)
            in TOOLS.items()]


def handle(req: dict):
    method, rid = req.get("method", ""), req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": req.get("params", {}).get(
                "protocolVersion", "2025-03-26"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "eclipse-ledger",
                           "version": "0.1.0"}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid,
                "result": {"tools": tool_list()}}
    if method == "tools/call":
        name = req["params"]["name"]
        args = req["params"].get("arguments", {})
        if name in FORBIDDEN_TOOL_NAMES or name not in TOOLS:
            return {"jsonrpc": "2.0", "id": rid, "error": {
                "code": -32602,
                "message": f"unknown or prohibited tool {name}"}}
        state = load_state()
        try:
            reject_credentials(args)
            out = TOOLS[name][0](state, args)
            save_state(state)
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps(out, indent=1)}]}}
        except ToolError as exc:
            # Denials are receipts too: handlers emit DENY
            # receipts before raising where applicable; persist
            # either way. Denied tools raise before mutating
            # anything else by construction.
            save_state(state)
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps({"error": str(exc)})}],
                "isError": True}}
    if rid is not None:
        return {"jsonrpc": "2.0", "id": rid, "error": {
            "code": -32601, "message": f"method not found: {method}"}}
    return None


def main():
    try:
        load_policy()  # tier-floor validation at load (spec 7)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            response = handle(json.loads(line))
        except Exception as exc:  # never crash the transport
            response = {"jsonrpc": "2.0", "id": None, "error": {
                "code": -32603, "message": str(exc)}}
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
