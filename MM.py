from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
import csv
import random
import math
import argparse
from collections import deque, Counter

# -----------------------------
# Data model
# -----------------------------
@dataclass(frozen=True)
class Guild:
    guild_id: str
    server_id: str
    power: float

# -----------------------------
# Your MM bucketing algorithm (as described)
# -----------------------------
@dataclass
class BucketBuildStats:
    fallback_adds: int = 0
    queue_scans: int = 0  # how many full scans we performed (per slot max 1)

def build_buckets_as_is(
    guilds_sorted: List[Guild],
    bucket_size: int = 16,
) -> Tuple[List[List[Guild]], BucketBuildStats]:
    """
    Implements your algorithm:
    - guilds_sorted is already sorted by power desc
    - global FIFO waiting queue
    - for each bucket slot:
        - try queue with at most one full pass to find non-conflicting server
        - if not found, try main list (current guild)
        - fallback if both conflict
    """
    q = deque()  # FIFO waiting queue (Guild)
    buckets: List[List[Guild]] = []
    stats = BucketBuildStats()

    i = 0
    n = len(guilds_sorted)

    while i < n or q:
        bucket: List[Guild] = []
        servers_in_bucket = set()

        # Fill bucket slots
        while len(bucket) < bucket_size:
            # 1) Try to fill from queue without server conflict
            picked_from_queue = False
            if q:
                # One full pass maximum per slot
                stats.queue_scans += 1
                q_len = len(q)
                found_idx = None
                for _ in range(q_len):
                    g = q[0]
                    q.rotate(-1)  # move front to back
                    if g.server_id not in servers_in_bucket and found_idx is None:
                        # We found a candidate; it's now at the back because of rotate,
                        # so mark that we should take the last element.
                        found_idx = "back"
                        break
                if found_idx == "back":
                    g = q.pop()
                    bucket.append(g)
                    servers_in_bucket.add(g.server_id)
                    picked_from_queue = True

                # If not found, queue remains rotated; rotate back to preserve FIFO order.
                # Important: restore original order if we didn't pick.
                if not picked_from_queue:
                    q.rotate(q_len)

            if picked_from_queue:
                continue

            # 2) If still not filled, go to main list
            if i < n:
                g = guilds_sorted[i]
                i += 1

                if g.server_id not in servers_in_bucket:
                    bucket.append(g)
                    servers_in_bucket.add(g.server_id)
                else:
                    # conflict: put in queue
                    q.append(g)

                    # 3) Fallback condition:
                    # - queue scan for this slot failed to find non-conflicting
                    # - current main guild conflicts
                    # -> add g anyway (even if server already present)
                    #
                    # In our flow, the queue scan "failed" means:
                    # - we either had empty queue OR scan didn't pick
                    # and we just encountered main list conflict.
                    #
                    # But your text says: fallback happens when:
                    #   after one full pass of waiting queue no non-conflict found
                    #   AND main list guild conflicts
                    # So we apply fallback ONLY if q existed and scan happened and found none.
                    #
                    # We can track it by: if q existed and we scanned and didn't pick for this slot.
                    # Here it's ambiguous because q could be empty. We'll interpret strictly:
                    # fallback if q was non-empty AND we scanned it (one pass) AND didn't pick.
                    #
                    # We'll implement this by re-running a strict check:
                    # if queue is non-empty AND there is no non-conflicting server in queue right now
                    # then fallback.
                    if q:
                        has_non_conflict = any(x.server_id not in servers_in_bucket for x in q)
                        if not has_non_conflict:
                            # fallback: take current guild anyway
                            # remove it from queue tail (it was appended just now)
                            q.pop()
                            bucket.append(g)
                            # server already in set; keep
                            stats.fallback_adds += 1
            else:
                # main list exhausted: must take from queue (even if conflicting) to guarantee fill
                if q:
                    g = q.popleft()
                    bucket.append(g)
                    servers_in_bucket.add(g.server_id)
                    # This is effectively a fallback-like behavior after main list ends,
                    # but it's not the same as your described fallback. We won't count it.
                else:
                    break

            # If we can't fill anymore (no main list and no queue)
            if i >= n and not q and len(bucket) < bucket_size:
                break

        if bucket:
            buckets.append(bucket)
        else:
            break

    return buckets, stats

# -----------------------------
# Pairing inside bucket
# -----------------------------
@dataclass
class Pair:
    a: Guild
    b: Guild

def pair_bucket_min_power_gap_avoid_same_server(bucket: List[Guild]) -> List[Pair]:
    """
    Greedy pairing:
    - Sort by power desc
    - For each unpaired guild, pair with closest power unpaired guild with different server if possible,
      else closest power regardless of server.
    """
    remaining = bucket[:]
    remaining.sort(key=lambda g: g.power, reverse=True)
    pairs: List[Pair] = []

    used = [False] * len(remaining)

    def find_best_partner(i: int, require_diff_server: bool) -> Optional[int]:
        best_j = None
        best_gap = float("inf")
        for j in range(len(remaining)):
            if i == j or used[j]:
                continue
            if require_diff_server and remaining[j].server_id == remaining[i].server_id:
                continue
            gap = abs(remaining[i].power - remaining[j].power)
            if gap < best_gap:
                best_gap = gap
                best_j = j
        return best_j

    for i in range(len(remaining)):
        if used[i]:
            continue
        used[i] = True
        j = find_best_partner(i, require_diff_server=True)
        if j is None:
            j = find_best_partner(i, require_diff_server=False)
        if j is None:
            break
        used[j] = True
        pairs.append(Pair(remaining[i], remaining[j]))

    return pairs

# -----------------------------
# Analytics
# -----------------------------
def percentile(values: List[float], p: float) -> float:
    if not values:
        return float("nan")
    values_sorted = sorted(values)
    k = (len(values_sorted) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return values_sorted[int(k)]
    return values_sorted[f] * (c - k) + values_sorted[c] * (k - f)

@dataclass
class Report:
    buckets_count: int
    total_pairs: int
    cross_server_pairs: int
    same_server_pairs: int
    same_server_pair_rate: float
    bucket_unique_servers_p50: float
    bucket_unique_servers_p10: float
    bucket_unique_servers_p90: float
    match_power_gap_p50: float
    match_power_gap_p90: float
    match_power_gap_max: float
    bucket_power_range_p50: float
    bucket_power_range_p90: float
    fallback_adds: int
    fallback_rate_per_guild: float
    ok_by_power_gap: bool
    ok_by_same_server_rate: bool

def analyze(
    buckets: List[List[Guild]],
    pairing_fn,
    power_gap_ok_p90: float,
    same_server_rate_ok: float,
    stats: BucketBuildStats,
) -> Report:
    all_pairs: List[Pair] = []
    bucket_unique_counts: List[int] = []
    bucket_power_ranges: List[float] = []

    for b in buckets:
        servers = {g.server_id for g in b}
        bucket_unique_counts.append(len(servers))
        pows = [g.power for g in b]
        if pows:
            bucket_power_ranges.append(max(pows) - min(pows))

        pairs = pairing_fn(b)
        all_pairs.extend(pairs)

    gaps = [abs(p.a.power - p.b.power) for p in all_pairs]
    same_server = sum(1 for p in all_pairs if p.a.server_id == p.b.server_id)
    total_pairs = len(all_pairs)
    cross_server = total_pairs - same_server
    same_rate = (same_server / total_pairs) if total_pairs else 0.0

    total_guilds = sum(len(b) for b in buckets) or 1
    fallback_rate = stats.fallback_adds / total_guilds

    rep = Report(
        buckets_count=len(buckets),
        total_pairs=total_pairs,
        cross_server_pairs=cross_server,
        same_server_pairs=same_server,
        same_server_pair_rate=same_rate,
        bucket_unique_servers_p50=percentile(bucket_unique_counts, 0.50),
        bucket_unique_servers_p10=percentile(bucket_unique_counts, 0.10),
        bucket_unique_servers_p90=percentile(bucket_unique_counts, 0.90),
        match_power_gap_p50=percentile(gaps, 0.50),
        match_power_gap_p90=percentile(gaps, 0.90),
        match_power_gap_max=max(gaps) if gaps else float("nan"),
        bucket_power_range_p50=percentile(bucket_power_ranges, 0.50),
        bucket_power_range_p90=percentile(bucket_power_ranges, 0.90),
        fallback_adds=stats.fallback_adds,
        fallback_rate_per_guild=fallback_rate,
        ok_by_power_gap=(percentile(gaps, 0.90) <= power_gap_ok_p90) if gaps else True,
        ok_by_same_server_rate=(same_rate <= same_server_rate_ok) if total_pairs else True,
    )
    return rep

# -----------------------------
# IO: CSV and synthetic generator
# -----------------------------
def read_guilds_csv(path: str) -> List[Guild]:
    out = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            out.append(Guild(
                guild_id=str(row["guild_id"]),
                server_id=str(row["server_id"]),
                power=float(row["power"]),
            ))
    return out

def gen_synthetic(
    servers: int,
    guilds_per_server: int,
    seed: int,
    power_mu: float,
    power_sigma: float,
    server_strength_sigma: float,
) -> List[Guild]:
    rnd = random.Random(seed)
    out: List[Guild] = []
    # server baseline offsets (to simulate "strong servers")
    server_offsets = [rnd.gauss(0, server_strength_sigma) for _ in range(servers)]
    for s in range(servers):
        for g in range(guilds_per_server):
            power = max(0.0, rnd.gauss(power_mu + server_offsets[s], power_sigma))
            out.append(Guild(
                guild_id=f"S{s}_G{g}",
                server_id=f"S{s}",
                power=power
            ))
    return out

# -----------------------------
# Pretty print
# -----------------------------
def print_bucket_preview(buckets: List[List[Guild]], show_buckets: int, show_rows: int):
    show_buckets = min(show_buckets, len(buckets))
    for bi in range(show_buckets):
        b = buckets[bi]
        uniq = len({g.server_id for g in b})
        print(f"\n=== Bucket #{bi+1} (size={len(b)}, unique_servers={uniq}) ===")
        # show top rows
        b_sorted = sorted(b, key=lambda g: g.power, reverse=True)
        for g in b_sorted[:show_rows]:
            print(f"  {g.guild_id:12}  server={g.server_id:8}  power={g.power:.2f}")
        if len(b_sorted) > show_rows:
            print(f"  ... ({len(b_sorted)-show_rows} more)")

def print_report(rep: Report):
    print("\n================= SUMMARY =================")
    print(f"Buckets built: {rep.buckets_count}")
    print(f"Total matches (pairs): {rep.total_pairs}")
    print(f"Cross-server pairs: {rep.cross_server_pairs}")
    print(f"Same-server pairs:  {rep.same_server_pairs}  (rate={rep.same_server_pair_rate:.4f})")

    print("\n-- Bucket server diversity --")
    print(f"Unique servers per bucket p10/p50/p90: "
          f"{rep.bucket_unique_servers_p10:.1f} / {rep.bucket_unique_servers_p50:.1f} / {rep.bucket_unique_servers_p90:.1f}")

    print("\n-- Power tightness --")
    print(f"Match power gap p50/p90/max: "
          f"{rep.match_power_gap_p50:.2f} / {rep.match_power_gap_p90:.2f} / {rep.match_power_gap_max:.2f}")
    print(f"Bucket power range p50/p90: "
          f"{rep.bucket_power_range_p50:.2f} / {rep.bucket_power_range_p90:.2f}")

    print("\n-- Fallback --")
    print(f"Fallback adds: {rep.fallback_adds}  (per-guild rate={rep.fallback_rate_per_guild:.4f})")

    print("\n-- OK / NOT OK flags (by thresholds) --")
    print(f"Power gap OK (p90): {rep.ok_by_power_gap}")
    print(f"Same-server rate OK: {rep.ok_by_same_server_rate}")
    print("==========================================\n")

# -----------------------------
# Main
# -----------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=str, default=None, help="Path to CSV with columns: guild_id,server_id,power")
    ap.add_argument("--bucket", type=int, default=16)
    ap.add_argument("--show_buckets", type=int, default=3)
    ap.add_argument("--show_rows", type=int, default=16)

    # thresholds (tune to your "norm")
    ap.add_argument("--power_gap_ok_p90", type=float, default=5000.0,
                    help="p90 of match power gap must be <= this to be OK")
    ap.add_argument("--same_server_rate_ok", type=float, default=0.02,
                    help="same-server pair rate must be <= this to be OK")

    # synthetic params (if --csv not provided)
    ap.add_argument("--servers", type=int, default=2000)
    ap.add_argument("--guilds_per_server", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--power_mu", type=float, default=100000.0)
    ap.add_argument("--power_sigma", type=float, default=15000.0)
    ap.add_argument("--server_strength_sigma", type=float, default=8000.0)

    args = ap.parse_args()

    if args.csv:
        guilds = read_guilds_csv(args.csv)
    else:
        guilds = gen_synthetic(
            servers=args.servers,
            guilds_per_server=args.guilds_per_server,
            seed=args.seed,
            power_mu=args.power_mu,
            power_sigma=args.power_sigma,
            server_strength_sigma=args.server_strength_sigma,
        )

    # sort by power desc
    guilds_sorted = sorted(guilds, key=lambda g: g.power, reverse=True)

    buckets, build_stats = build_buckets_as_is(guilds_sorted, bucket_size=args.bucket)

    print_bucket_preview(buckets, show_buckets=args.show_buckets, show_rows=args.show_rows)

    rep = analyze(
        buckets=buckets,
        pairing_fn=pair_bucket_min_power_gap_avoid_same_server,
        power_gap_ok_p90=args.power_gap_ok_p90,
        same_server_rate_ok=args.same_server_rate_ok,
        stats=build_stats,
    )

    print_report(rep)

if __name__ == "__main__":
    main()
