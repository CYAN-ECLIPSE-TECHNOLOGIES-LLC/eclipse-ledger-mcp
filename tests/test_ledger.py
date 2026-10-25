#!/usr/bin/env python3
"""Eclipse Ledger v0.1 (B0) tests — spec section 13 acceptance
properties are the organizing targets.
Run: python3 -m unittest discover tests"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import server as S  # noqa: E402

T0 = 1792886400 + 3600 * 15  # 2026-10-25 15:00Z, fresh vs fixtures
NBA = "fixture-nba-lal-bos-20261025"
NFL = "fixture-nfl-kc-buf-20261026"


def fresh(profile_state="NY", birth_year=1990):
    state = S.empty_state()
    S.t_profile_set(state, {"state": profile_state,
                            "birth_year": birth_year, "at_ts": T0})
    return state


class TestLimits(unittest.TestCase):
    """Spec 13.1/13.2 — asymmetry + agent-never-raises."""

    def test_decrease_applies_same_call(self):
        state = fresh()
        S.t_limit_set(state, {"kind": "wager", "window": "daily",
                              "amount": 100, "at_ts": T0})
        out = S.t_limit_set(state, {"kind": "wager",
                                    "window": "daily",
                                    "amount": 40, "at_ts": T0})
        self.assertEqual(out["result"], "APPLIED_IMMEDIATELY")
        self.assertEqual(out["direction"], "decrease")
        eff = S.effective_limit(state, "wager", "daily")
        self.assertEqual(eff["amount"], 40.0)

    def test_increase_pending_then_confirm_after_delay(self):
        state = fresh()
        S.t_limit_set(state, {"kind": "wager", "window": "daily",
                              "amount": 100, "at_ts": T0})
        out = S.t_limit_set(state, {"kind": "wager",
                                    "window": "daily",
                                    "amount": 150, "at_ts": T0})
        self.assertEqual(out["result"], "PENDING_INCREASE")
        self.assertEqual(out["delay_hours"], 72)
        # current limit unchanged while pending
        self.assertEqual(
            S.effective_limit(state, "wager", "daily")["amount"],
            100.0)
        with self.assertRaises(S.ToolError) as ctx:
            S.t_limit_confirm(state, {"kind": "wager",
                                      "window": "daily",
                                      "at_ts": T0 + 3600})
        self.assertIn("LIMIT_INCREASE_PENDING", str(ctx.exception))
        out = S.t_limit_confirm(state, {"kind": "wager",
                                        "window": "daily",
                                        "at_ts": T0 + 73 * 3600})
        self.assertEqual(out["result"], "INCREASE_EFFECTIVE")
        self.assertEqual(
            S.effective_limit(state, "wager", "daily")["amount"],
            150.0)

    def test_unconfirmed_increase_lapses(self):
        state = fresh()
        S.t_limit_set(state, {"kind": "deposit", "window": "weekly",
                              "amount": 200, "at_ts": T0})
        S.t_limit_set(state, {"kind": "deposit", "window": "weekly",
                              "amount": 300, "at_ts": T0})
        # delay 168h + confirm window 24h -> at +200h it has lapsed
        with self.assertRaises(S.ToolError) as ctx:
            S.t_limit_confirm(state, {"kind": "deposit",
                                      "window": "weekly",
                                      "at_ts": T0 + 200 * 3600})
        self.assertIn("LIMIT_INCREASE_LAPSED", str(ctx.exception))
        self.assertEqual(
            S.effective_limit(state, "deposit", "weekly")["amount"],
            200.0)

    def test_state_fixture_delay_is_stricter(self):
        # MA deposit increases: 90-day state fixture beats 72h floor
        state = fresh(profile_state="MA")
        out = S.t_limit_set(state, {"kind": "deposit",
                                    "window": "daily",
                                    "amount": 100, "at_ts": T0})
        self.assertEqual(out["result"], "APPLIED_IMMEDIATELY")
        out = S.t_limit_set(state, {"kind": "deposit",
                                    "window": "daily",
                                    "amount": 150, "at_ts": T0})
        self.assertEqual(out["delay_hours"], 90 * 24)

    def test_no_tool_path_raises_a_limit(self):
        # Denylist: no raise-now verb exists at all (spec 13.2)
        for name in ("limit_raise_now", "raise_limit_now",
                     "limit_remove"):
            self.assertNotIn(name, S.TOOLS)
            self.assertIn(name, S.FORBIDDEN_TOOL_NAMES)
        # And limit_set itself never returns an applied increase
        state = fresh()
        S.t_limit_set(state, {"kind": "loss", "window": "monthly",
                              "amount": 500, "at_ts": T0})
        out = S.t_limit_set(state, {"kind": "loss",
                                    "window": "monthly",
                                    "amount": 900, "at_ts": T0})
        self.assertEqual(out["result"], "PENDING_INCREASE")
        self.assertEqual(out["delay_hours"], 720)

    def test_increase_during_timeout_stays_pending(self):
        state = fresh()
        S.t_limit_set(state, {"kind": "wager", "window": "daily",
                              "amount": 100, "at_ts": T0})
        S.t_timeout_start(state, {"days": 7, "at_ts": T0})
        out = S.t_limit_set(state, {"kind": "wager",
                                    "window": "daily",
                                    "amount": 500, "at_ts": T0})
        self.assertEqual(out["result"], "PENDING_INCREASE")
        self.assertEqual(
            S.effective_limit(state, "wager", "daily")["amount"],
            100.0)


class TestExclusion(unittest.TestCase):
    """Spec 13.3 — absoluteness."""

    def test_exclusion_denies_all_wagering_adjacent(self):
        state = fresh()
        S.t_exclusion_start(state, {"source": "self-declared",
                                    "term_days": 365, "at_ts": T0})
        for fn, args in (
                (S.t_odds_compare, {"event_id": NBA, "at_ts": T0}),
                (S.t_arb_observe, {"event_id": NFL, "at_ts": T0}),
                (S.t_slip_prepare, {"book": "FanDuel",
                                    "event_id": NBA,
                                    "selection": "Lakers",
                                    "odds": -110, "stake": 10,
                                    "at_ts": T0}),
                (S.t_bet_record_add, {"book": "FanDuel",
                                      "event": "Lakers game",
                                      "stake": 10, "at_ts": T0})):
            with self.assertRaises(S.ToolError) as ctx:
                fn(state, args)
            self.assertIn("EXCLUDED", str(ctx.exception))
            self.assertIn("1-800-GAMBLER", str(ctx.exception))

    def test_excluded_profile_keeps_bookkeeping(self):
        state = fresh()
        S.t_bet_record_add(state, {
            "book": "FanDuel", "event": "Old game", "stake": 25,
            "settlement": "lost", "payout": 0,
            "placed_ts": T0 - 10 * 86400, "at_ts": T0})
        S.t_exclusion_start(state, {"source": "operator",
                                    "term_days": 365, "at_ts": T0})
        # records reads + summaries + resources still answer
        self.assertEqual(S.t_records_list(state, {})["count"], 1)
        summary = S.t_pnl_summary(state, {"at_ts": T0})
        self.assertEqual(summary["cash_net_position"], -25.0)
        self.assertIn("entries", summary["resources"])
        # backfill of pre-exclusion SETTLED history allowed
        out = S.t_bet_record_add(state, {
            "book": "FanDuel", "event": "Older game", "stake": 10,
            "settlement": "won", "payout": 19,
            "placed_ts": T0 - 20 * 86400, "at_ts": T0})
        self.assertEqual(out["record"]["settlement"], "won")

    def test_no_early_end_and_reactivation_requirements(self):
        state = fresh()
        S.t_exclusion_start(state, {"source": "state-program",
                                    "term_days": 30, "at_ts": T0})
        with self.assertRaises(S.ToolError) as ctx:
            S.t_exclusion_end(state, {"at_ts": T0 + 86400})
        self.assertIn("EXCLUSION_IRREVOCABLE_UNTIL_EXPIRY",
                      str(ctx.exception))
        after = T0 + 31 * 86400
        with self.assertRaises(S.ToolError) as ctx:
            S.t_exclusion_end(state, {"at_ts": after})
        self.assertIn("REACTIVATION_INCOMPLETE",
                      str(ctx.exception))
        out = S.t_exclusion_end(state, {
            "at_ts": after, "jurisdiction_rechecked": True,
            "limits_reconfirmed": True})
        self.assertEqual(out["result"], "EXCLUSION_EXPIRED")
        self.assertFalse(
            S.t_exclusion_status(state, {"at_ts": after})["excluded"])

    def test_timeout_denies_like_exclusion(self):
        state = fresh()
        S.t_timeout_start(state, {"days": 3, "at_ts": T0})
        with self.assertRaises(S.ToolError) as ctx:
            S.t_odds_compare(state, {"event_id": NBA, "at_ts": T0})
        self.assertIn("TIMEOUT_ACTIVE", str(ctx.exception))
        out = S.t_odds_compare(state, {
            "event_id": NBA, "at_ts": T0 + 4 * 86400})
        # matrix as_of 2026-10-25 + 30d TTL: still fresh at +4d
        self.assertEqual(out["event_id"], NBA)


class TestJurisdiction(unittest.TestCase):
    """Spec 13.4 — denial, incl. stale-matrix degradation."""

    def test_not_legal_denies_and_records_stay(self):
        state = fresh(profile_state="TX")
        verdict = S.t_jurisdiction_check(
            state, {"product_class": "sportsbook", "at_ts": T0})
        self.assertEqual(verdict["verdict"], "NOT_LEGAL")
        with self.assertRaises(S.ToolError) as ctx:
            S.t_odds_compare(state, {"event_id": NBA, "at_ts": T0})
        self.assertIn("JURISDICTION_NOT_LEGAL", str(ctx.exception))
        # DFS split falls out of class keying: DFS legal in TX
        verdict = S.t_jurisdiction_check(
            state, {"product_class": "dfs-classic", "at_ts": T0})
        self.assertEqual(verdict["verdict"], "ALLOWED")
        # records remain readable in a NOT_LEGAL state
        self.assertEqual(S.t_records_list(state, {})["count"], 0)

    def test_stale_matrix_degrades_to_unknown_and_denies(self):
        state = fresh()
        fresh_ts = T0 + 29 * 86400
        verdict = S.t_jurisdiction_check(
            state, {"product_class": "sportsbook",
                    "at_ts": fresh_ts})
        self.assertEqual(verdict["verdict"], "ALLOWED")
        stale_ts = T0 + 40 * 86400  # beyond 30d TTL
        verdict = S.t_jurisdiction_check(
            state, {"product_class": "sportsbook",
                    "at_ts": stale_ts})
        self.assertEqual(verdict["verdict"], "UNKNOWN")
        self.assertTrue(verdict["stale_matrix"])
        with self.assertRaises(S.ToolError) as ctx:
            S.t_odds_compare(state, {"event_id": NBA,
                                     "at_ts": stale_ts})
        self.assertIn("JURISDICTION_UNKNOWN", str(ctx.exception))
        self.assertTrue(S.t_matrix_status(
            state, {"at_ts": stale_ts})["stale"])

    def test_verdicts_are_receipted(self):
        state = fresh()
        before = len(state["receipts"])
        S.t_jurisdiction_check(
            state, {"product_class": "sportsbook", "at_ts": T0})
        self.assertEqual(len(state["receipts"]), before + 1)
        self.assertEqual(state["receipts"][-1]["type"],
                         "jurisdiction_verdict")

    def test_age_floor_denies(self):
        state = fresh(birth_year=2012)  # 14 at fixture time
        verdict = S.t_jurisdiction_check(
            state, {"product_class": "sportsbook", "at_ts": T0})
        self.assertEqual(verdict["verdict"], "NOT_LEGAL")
        self.assertEqual(verdict["row_status"], "AGE_FLOOR")


class TestPnlTruth(unittest.TestCase):
    """Spec 13.5 — bonus bets are not cash."""

    def test_bonus_bet_winnings_without_stake(self):
        state = fresh()
        S.t_bet_record_add(state, {
            "book": "FanDuel", "event": "Game A", "stake": 50,
            "bonus_type": "bonus_bet", "settlement": "won",
            "payout": 45, "placed_ts": T0 - 86400, "at_ts": T0})
        S.t_bet_record_add(state, {
            "book": "DraftKings", "event": "Game B", "stake": 100,
            "settlement": "lost", "payout": 0,
            "placed_ts": T0 - 86400, "at_ts": T0})
        summary = S.t_pnl_summary(state, {"at_ts": T0})
        # cash: paid out 45, cash staked 100 -> net -55, NOT -5
        self.assertEqual(summary["cash_net_position"], -55.0)

    def test_unsettled_bonus_valued_zero(self):
        state = fresh()
        S.t_bet_record_add(state, {
            "book": "FanDuel", "event": "Game C", "stake": 500,
            "bonus_type": "bonus_bet", "settlement": "pending",
            "placed_ts": T0, "at_ts": T0})
        summary = S.t_pnl_summary(state, {"at_ts": T0})
        self.assertEqual(summary["cash_net_position"], 0.0)
        self.assertEqual(
            summary["unsettled_bonus_value_in_cash_pnl"], 0.0)
        view = summary["records"][0]
        self.assertFalse(view["stake_returned"])
        self.assertIn("valued at $0", view["bonus_note"])

    def test_headline_reproducible_from_raw_records(self):
        state = fresh()
        for i, (stake, settle, payout, bonus) in enumerate((
                (20, "won", 38, "none"), (20, "lost", 0, "none"),
                (10, "won", 9, "bonus_bet"),
                (30, "pending", None, "none"))):
            S.t_bet_record_add(state, {
                "book": "BetMGM", "event": f"Game {i}",
                "stake": stake, "bonus_type": bonus,
                "settlement": settle, "payout": payout,
                "placed_ts": T0 - 3600, "at_ts": T0})
        summary = S.t_pnl_summary(state, {"at_ts": T0})
        raw = S.t_records_list(state, {})["raw_records"]
        recomputed = round(sum(
            (float(r["payout"] or 0) if r["settlement"] != "pending"
             else 0.0)
            - (r["stake"] if r["bonus_type"] == "none" else 0.0)
            for r in raw if r["settlement"] != "pending"), 2)
        self.assertEqual(summary["cash_net_position"], recomputed)


class TestPatternFlags(unittest.TestCase):
    def test_loss_chasing_flag_is_a_fact_with_note(self):
        state = fresh(profile_state="NJ")
        S.t_bet_record_add(state, {
            "book": "FanDuel", "event": "G1", "stake": 10,
            "settlement": "lost", "payout": 0,
            "placed_ts": T0 - 7200, "at_ts": T0})
        S.t_bet_record_add(state, {
            "book": "FanDuel", "event": "G2", "stake": 20,
            "settlement": "lost", "payout": 0,
            "placed_ts": T0 - 3600, "at_ts": T0})
        snap = S.t_reality_snapshot(state, {"at_ts": T0})
        flags = [f["flag"] for f in snap["pattern_flags"]]
        self.assertIn("loss_chasing_signature", flags)
        for flag in snap["pattern_flags"]:
            self.assertIn("invisible", flag["partial_view_note"])
        # resources ride along when a flag fires (spec 3.5)
        self.assertIn("entries", snap["resources"])

    def test_deposit_over_limit_fact(self):
        state = fresh()
        S.t_limit_set(state, {"kind": "deposit", "window": "daily",
                              "amount": 100, "at_ts": T0})
        S.t_deposit_record_add(state, {"amount": 60, "at_ts": T0})
        out = S.t_deposit_record_add(state, {"amount": 60,
                                            "at_ts": T0})
        self.assertIn("limit_fact", out)
        self.assertIn("above the daily deposit limit",
                      out["limit_fact"])


class TestOddsSurface(unittest.TestCase):
    def test_price_only_ordering_and_refs(self):
        state = fresh()
        out = S.t_odds_compare(state, {"event_id": NBA,
                                       "at_ts": T0})
        prices = [r["price_american"]
                  for r in out["prices"]["Los Angeles Lakers"]]
        self.assertEqual(prices, [102, -105, -110])  # DK best 1st
        self.assertEqual(out["jurisdiction_verdict"]["verdict"],
                         "ALLOWED")
        self.assertIn("receipt_seq",
                      out["jurisdiction_verdict"])
        self.assertFalse(out["rg_status"]["excluded"])
        self.assertIsNone(out["recommendation"])
        # margin visible: FanDuel -110/-110 sums to 104.8
        self.assertEqual(
            out["book_market_sums_pct"]["fanduel"], 104.8)

    def test_promotions_stripped_and_banned_lint(self):
        state = fresh()
        out = S.t_odds_compare(state, {"event_id": NBA,
                                       "at_ts": T0})
        self.assertEqual(out["promotions_stripped"], 1)
        blob = json.dumps(out).lower()
        self.assertNotIn("risk-free", blob)
        self.assertNotIn('"promo"', blob)  # no promo FIELD survives
        self.assertNotIn("first bet", blob)  # promo content is gone

    def test_stale_price_labeled(self):
        state = fresh()
        out = S.t_odds_compare(state, {"event_id": NBA,
                                       "at_ts": T0 + 3600})
        row = out["prices"]["Los Angeles Lakers"][0]
        self.assertTrue(row["stale"])
        self.assertGreater(row["stale_age_seconds"], 900)

    def test_arb_observation_carries_limiting_warning(self):
        state = fresh()
        out = S.t_arb_observe(state, {"event_id": NFL,
                                      "at_ts": T0})
        self.assertLess(out["best_price_implied_sum_pct"], 100)
        self.assertIn("Books limit winning accounts",
                      out["mandatory_honesty"])
        self.assertIsNone(out["execution_support"])
        blob = json.dumps(out).lower()
        self.assertNotIn("risk-free", blob)
        self.assertNotIn("guaranteed", blob)


class TestSlipPrep(unittest.TestCase):
    def test_prep_allow_and_deny_paths(self):
        state = fresh()
        S.t_limit_set(state, {"kind": "stake_cap",
                              "window": "per_bet", "amount": 25,
                              "at_ts": T0})
        with self.assertRaises(S.ToolError) as ctx:
            S.t_slip_prepare(state, {
                "book": "FanDuel", "event_id": NBA,
                "selection": "Lakers", "odds": -110, "stake": 50,
                "at_ts": T0})
        self.assertIn("OVER_POLICY", str(ctx.exception))
        out = S.t_slip_prepare(state, {
            "book": "FanDuel", "event_id": NBA,
            "selection": "Lakers", "odds": -110, "stake": 20,
            "at_ts": T0})
        self.assertEqual(out["prep_verdict"], "ALLOW_TO_PREP")
        self.assertIn("No tool in this suite can submit",
                      out["slip"]["note"])

    def test_prep_wager_limit(self):
        state = fresh()
        S.t_limit_set(state, {"kind": "wager", "window": "daily",
                              "amount": 30, "at_ts": T0})
        with self.assertRaises(S.ToolError) as ctx:
            S.t_slip_prepare(state, {
                "book": "FanDuel", "event_id": NBA,
                "selection": "Lakers", "odds": -110, "stake": 31,
                "at_ts": T0})
        self.assertIn("OVER_LIMIT", str(ctx.exception))


class TestClaimsAndSurface(unittest.TestCase):
    """Spec 13.6/13.7 — no placement, claims refusal."""

    def test_no_placement_surface(self):
        for name in S.FORBIDDEN_TOOL_NAMES:
            self.assertNotIn(name, S.TOOLS)
        resp = S.handle({"jsonrpc": "2.0", "id": 1,
                         "method": "tools/call",
                         "params": {"name": "place_bet",
                                    "arguments": {}}})
        self.assertEqual(resp["error"]["code"], -32602)

    def test_advice_request_refused_by_class(self):
        state = fresh()
        with self.assertRaises(S.ToolError) as ctx:
            S.t_advice_request(state, {
                "question": "give me a guaranteed lock for tonight",
                "at_ts": T0})
        self.assertIn("CLAIMS_REFUSAL", str(ctx.exception))

    def test_credential_inputs_refused_by_name(self):
        state = fresh()
        with self.assertRaises(S.ToolError) as ctx:
            S.t_bet_record_add(state, {
                "book": "FanDuel", "event": "G", "stake": 10,
                "password": "hunter2", "at_ts": T0})
        self.assertIn("CREDENTIALS_NOT_ACCEPTED",
                      str(ctx.exception))
        # nested credential shape is also refused (dispatch-level)
        resp = S.handle({"jsonrpc": "2.0", "id": 9,
                         "method": "tools/call",
                         "params": {"name": "odds_compare",
                                    "arguments": {
                                        "event_id": NBA,
                                        "meta": {"api_key": "x"}}}})
        text = resp["result"]["content"][0]["text"]
        self.assertIn("CREDENTIALS_NOT_ACCEPTED", text)

    def test_source_has_no_placement_or_credential_store(self):
        source = Path(S.__file__).read_text()
        for verb in ("def place_bet", "def submit_bet",
                     "def connect_account", "def login"):
            self.assertNotIn(verb, source)

    def test_descriptor_verbatim(self):
        self.assertIn("Not a sportsbook. No bets are placed here.",
                      S.DESCRIPTOR)


class TestResources(unittest.TestCase):
    """Spec 13.8 — triggers produce the verified block."""

    def test_block_carries_both_numbers_and_reverify(self):
        state = fresh()
        block = S.t_resources_get(state, {"at_ts": T0})["resources"]
        phones = " ".join(e.get("phone") or ""
                          for e in block["entries"])
        self.assertIn("1-800-GAMBLER", phones)
        self.assertIn("1-800-MY-RESET", phones)
        self.assertIn("reverify_due", block)
        self.assertIn("reverify", block["note"].lower())

    def test_summary_always_carries_resources(self):
        state = fresh()
        summary = S.t_pnl_summary(state, {"at_ts": T0})
        self.assertIn("entries", summary["resources"])

    def test_reverify_overdue_flagged(self):
        state = fresh()
        block = S.t_resources_get(
            state, {"at_ts": T0 + 60 * 86400})["resources"]
        self.assertTrue(block["reverify_overdue"])


class TestReceipts(unittest.TestCase):
    def test_chain_valid_and_tamper_detected(self):
        state = fresh()
        S.t_limit_set(state, {"kind": "wager", "window": "daily",
                              "amount": 100, "at_ts": T0})
        out = S.t_receipt_list(state, {})
        self.assertTrue(out["chain_valid"])
        state["receipts"][0]["detail"]["verdict"] = "FORGED"
        self.assertFalse(S.verify_receipt_chain(state["receipts"]))

    def test_denials_are_receipts(self):
        state = fresh(profile_state="TX")
        with self.assertRaises(S.ToolError):
            S.t_odds_compare(state, {"event_id": NBA, "at_ts": T0})
        types = [r["type"] for r in state["receipts"]]
        self.assertIn("jurisdiction_verdict", types)


if __name__ == "__main__":
    unittest.main()
