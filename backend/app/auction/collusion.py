# app/auction/collusion.py
# Day 6: collusion rules 1 + 2 (L10).
# Rule 1: the same two vendors keep bidding only 1-2% apart.
# Rule 2: one vendor wins an unusually high share of the contested tenders it enters.
# Pure logic: no database, no HTTP, no decryption. It only reads the output of
# service.rank_bids(), which has already passed the deadline check (L1).
from collections import defaultdict
from decimal import Decimal

GAP_MIN = Decimal("1.00")     # a gap this small or smaller than GAP_MAX ...
GAP_MAX = Decimal("2.00")     # ... is "suspiciously close" (both ends count)
MIN_REPEATS = 3               # the same pair must be that close in this many tenders
CENT = Decimal("0.01")


def close_neighbours(tender_id: int, ranking: list[dict],
                     gap_min: Decimal = GAP_MIN, gap_max: Decimal = GAP_MAX) -> list[dict]:
    """One event for every pair of NEIGHBOURING ranks whose gap_pct is in [gap_min, gap_max]."""
    events = []
    for lower, higher in zip(ranking, ranking[1:]):
        gap = higher["gap_pct"]                       # % above the bid just before it
        if gap is None or not (gap_min <= gap <= gap_max):
            continue
        if lower["vendor_id"] == higher["vendor_id"]:
            continue                                  # a vendor cannot collude with itself
        events.append({
            "tender_id": tender_id,
            "lower_vendor_id": lower["vendor_id"], "higher_vendor_id": higher["vendor_id"],
            "lower_bid_id": lower["bid_id"], "higher_bid_id": higher["bid_id"],
            "gap_pct": gap,
        })
    return events


def flag_repeated_pairs(events: list[dict], min_repeats: int = MIN_REPEATS) -> list[dict]:
    """Group events by vendor PAIR (order does not matter); flag pairs seen in >= min_repeats tenders."""
    by_pair = defaultdict(list)
    for e in events:
        pair = tuple(sorted((e["lower_vendor_id"], e["higher_vendor_id"])))
        by_pair[pair].append(e)

    flagged = []
    for (a, b), items in by_pair.items():
        tenders = sorted({e["tender_id"] for e in items})
        if len(tenders) < min_repeats:
            continue                                  # one close gap is normal competition
        items = sorted(items, key=lambda e: e["tender_id"])
        flagged.append({
            "vendor_a": a, "vendor_b": b,
            "times": len(tenders), "tender_ids": tenders,
            "a_cheaper_times": sum(1 for e in items if e["lower_vendor_id"] == a),
            "b_cheaper_times": sum(1 for e in items if e["lower_vendor_id"] == b),
            "avg_gap_pct": (sum(e["gap_pct"] for e in items) / len(items)).quantize(CENT),
            "events": items,
        })
    flagged.sort(key=lambda f: (-f["times"], f["vendor_a"], f["vendor_b"]))
    return flagged


# ---- Day 6: collusion rule 2 - one vendor wins an unusually high share of the tenders it enters ----
RULE_UNDERCUTTING = "repeated_undercutting"   # rule 1, the same text scan_undercutting returns
RULE_WIN_SHARE = "high_win_share"             # rule 2
WIN_SHARE_MIN = 75     # % of contested tenders won that counts as "unusually high" (75 itself counts)
MIN_ENTERED = 3        # a vendor is judged only after it entered this many contested tenders
MIN_BIDDERS = 2        # a tender with fewer valid bids had no competition, so it is not counted


def win_records(rankings: dict[int, list[dict]], min_bidders: int = MIN_BIDDERS) -> dict[int, dict]:
    """vendor_id -> {"entered": [tender ids], "won": [tender ids]}, CONTESTED tenders only.
    `rankings` maps tender_id -> the "ranking" list of service.rank_bids() (rank 1 first)."""
    records = defaultdict(lambda: {"entered": [], "won": []})
    for tender_id in sorted(rankings):
        ranking = rankings[tender_id]
        if len(ranking) < min_bidders:
            continue                                  # a sole bidder "wins" without competing
        for row in ranking:
            records[row["vendor_id"]]["entered"].append(tender_id)
        records[ranking[0]["vendor_id"]]["won"].append(tender_id)   # rank 1 = lowest valid bid
    return dict(records)


def flag_high_win_share(records: dict[int, dict], min_share: int = WIN_SHARE_MIN,
                        min_entered: int = MIN_ENTERED) -> list[dict]:
    """Flag every vendor that entered >= min_entered contested tenders and won >= min_share % of them."""
    flagged = []
    for vendor_id, r in records.items():
        entered, won = len(r["entered"]), len(r["won"])
        if entered < min_entered:
            continue                                  # too few tenders to call anything "unusual"
        if won * 100 < min_share * entered:           # exact whole-number test, no rounding
            continue
        flagged.append({
            "vendor_id": vendor_id, "entered": entered, "won": won,
            "win_share_pct": (Decimal(won * 100) / entered).quantize(CENT),   # shown, not compared
            "tender_ids_entered": r["entered"], "tender_ids_won": r["won"],
        })
    flagged.sort(key=lambda f: (-f["win_share_pct"], -f["won"], f["vendor_id"]))
    return flagged


def flag_rows(pairs: list[dict], winners: list[dict]) -> list[dict]:
    """Both rules' results -> CollusionFlags rows: ONE row per rule + tender + vendor (or pair).
    Rule 1: a row for every tender where the pair was close. Rule 2: a row for every tender won."""
    rows = []
    for p in pairs:                                   # from flag_repeated_pairs (rule 1)
        for e in p["events"]:
            rows.append({
                "rule": RULE_UNDERCUTTING, "tender_id": e["tender_id"],
                "vendor_id_a": p["vendor_a"], "vendor_id_b": p["vendor_b"],   # already sorted, a < b
                "flag_reason": (
                    f"vendor {e['higher_vendor_id']} ranked right above vendor {e['lower_vendor_id']}, "
                    f"{e['gap_pct']}% apart (bids {e['lower_bid_id']} and {e['higher_bid_id']}); "
                    f"this pair was {GAP_MIN}-{GAP_MAX}% apart in {p['times']} tenders"),
            })
    for w in winners:                                 # from flag_high_win_share (rule 2)
        for tender_id in w["tender_ids_won"]:
            rows.append({
                "rule": RULE_WIN_SHARE, "tender_id": tender_id,
                "vendor_id_a": w["vendor_id"], "vendor_id_b": None,           # one vendor, no pair
                "flag_reason": (
                    f"vendor {w['vendor_id']} won this tender; it won {w['won']} of the "
                    f"{w['entered']} contested tenders it entered ({w['win_share_pct']}%)"),
            })
    rows.sort(key=lambda r: (r["tender_id"], r["rule"], r["vendor_id_a"], r["vendor_id_b"] or 0))
    return rows