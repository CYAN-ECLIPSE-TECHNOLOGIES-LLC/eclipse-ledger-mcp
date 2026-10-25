#!/usr/bin/env python3
"""End-to-end stdio smoke for Eclipse Ledger v0.1 (B0).

Temp state. Drives initialize -> profile_set -> limit decrease /
increase-pending -> jurisdiction verdict -> odds_compare (price
order, promo stripped) -> slip_prepare -> bet_record_add ->
pnl_summary (cash truth + resources) -> exclusion_start ->
odds_compare DENIED (EXCLUDED) -> receipt_list (chain valid).
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
T0 = 1792886400 + 3600 * 15  # 2026-10-25 15:00Z
NBA = "fixture-nba-lal-bos-20261025"


def rpc(proc, rid, method, params=None):
    req = {"jsonrpc": "2.0", "id": rid, "method": method,
           "params": params or {}}
    proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def call(proc, rid, name, args):
    response = rpc(proc, rid, "tools/call",
                   {"name": name, "arguments": args})
    if "error" in response:
        return {"error": response["error"]["message"]}
    return json.loads(response["result"]["content"][0]["text"])


def main():
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ)
        env["ECLIPSE_LEDGER_STATE"] = str(Path(tmp) / "state.json")
        proc = subprocess.Popen(
            [sys.executable, str(HERE / "server.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, cwd=str(HERE), env=env)
        try:
            init = rpc(proc, 1, "initialize",
                       {"protocolVersion": "2025-03-26"})
            assert init["result"]["serverInfo"]["name"] == \
                "eclipse-ledger"
            print("initialize OK")
            tools = rpc(proc, 2, "tools/list")["result"]["tools"]
            names = {t["name"] for t in tools}
            for banned in ("place_bet", "submit_bet",
                           "connect_account", "limit_raise_now"):
                assert banned not in names, banned
            print(f"tools/list OK: {len(names)} tools, "
                  f"no placement surface")
            call(proc, 3, "profile_set",
                 {"state": "NY", "birth_year": 1990, "at_ts": T0})
            out = call(proc, 4, "limit_set",
                       {"kind": "wager", "window": "daily",
                        "amount": 100, "at_ts": T0})
            assert out["result"] == "APPLIED_IMMEDIATELY"
            out = call(proc, 5, "limit_set",
                       {"kind": "wager", "window": "daily",
                        "amount": 150, "at_ts": T0})
            assert out["result"] == "PENDING_INCREASE"
            print("limits OK: decrease instant, increase pending")
            out = call(proc, 6, "odds_compare",
                       {"event_id": NBA, "at_ts": T0})
            prices = [r["price_american"] for r in
                      out["prices"]["Los Angeles Lakers"]]
            assert prices == [102, -105, -110], prices
            assert out["promotions_stripped"] == 1
            assert "risk-free" not in json.dumps(out).lower()
            print("odds OK: price-only order, promo stripped")
            out = call(proc, 7, "slip_prepare",
                       {"book": "FanDuel", "event_id": NBA,
                        "selection": "Los Angeles Lakers",
                        "odds": 102, "stake": 20, "at_ts": T0})
            assert out["prep_verdict"] == "ALLOW_TO_PREP"
            print("slip prep OK: ALLOW_TO_PREP (data, not a bet)")
            call(proc, 8, "bet_record_add",
                 {"book": "FanDuel", "event": "Lakers game",
                  "stake": 50, "bonus_type": "bonus_bet",
                  "settlement": "won", "payout": 45,
                  "placed_ts": T0 - 86400, "at_ts": T0})
            out = call(proc, 9, "pnl_summary", {"at_ts": T0})
            assert out["cash_net_position"] == 45.0, out
            assert "entries" in out["resources"]
            print("P&L OK: bonus bet pays winnings, stake was "
                  "never cash; resources attached")
            call(proc, 10, "exclusion_start",
                 {"source": "self-declared", "term_days": 365,
                  "at_ts": T0})
            out = call(proc, 11, "odds_compare",
                       {"event_id": NBA, "at_ts": T0})
            assert "EXCLUDED" in out["error"], out
            assert "1-800-GAMBLER" in out["error"]
            print("exclusion OK: odds denied, resources in the "
                  "denial")
            resp = rpc(proc, 12, "tools/call",
                       {"name": "place_bet", "arguments": {}})
            assert resp["error"]["code"] == -32602
            print("place_bet OK: -32602 — the verb does not exist")
            out = call(proc, 13, "receipt_list", {})
            assert out["chain_valid"] is True
            print(f"receipts OK: {out['count']} entries, "
                  f"chain valid")
            print("SMOKE PASS")
        finally:
            proc.terminate()


if __name__ == "__main__":
    main()
