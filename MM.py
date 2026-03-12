import streamlit as st
import pandas as pd
import numpy as np
import random
import math
from dataclasses import dataclass
from collections import deque, Counter
from typing import List, Tuple, Optional, Dict
import matplotlib.pyplot as plt

# -----------------------------
# Data model
# -----------------------------
@dataclass(frozen=True)
class Guild:
    guild_id: str
    server_id: str
    power: float

@dataclass
class BucketBuildStats:
    fallback_adds: int = 0
    queue_scans: int = 0

@dataclass
class Pair:
    a: Guild
    b: Guild

# -----------------------------
# Algorithm (as described by user)
# -----------------------------
def build_buckets_as_is(guilds_sorted: List[Guild], bucket_size: int = 16) -> Tuple[List[List[Guild]], BucketBuildStats]:
    q = deque()
    buckets: List[List[Guild]] = []
    stats = BucketBuildStats()

    i = 0
    n = len(guilds_sorted)

    while i < n or q:
        bucket: List[Guild] = []
        servers_in_bucket = set()

        while len(bucket) < bucket_size:
            picked_from_queue = False
            scanned_queue = False
            if q:
                # One full pass maximum per slot
                stats.queue_scans += 1
                scanned_queue = True
                q_len = len(q)
                found_idx = None
                for _ in range(q_len):
                    g = q[0]
                    q.rotate(-1)
                    if g.server_id not in servers_in_bucket and found_idx is None:
                        found_idx = "back"
                        break
                if found_idx == "back":
                    g = q.pop()
                    bucket.append(g)
                    servers_in_bucket.add(g.server_id)
                    picked_from_queue = True
                if not picked_from_queue:
                    q.rotate(q_len)

            if picked_from_queue:
                continue

            if i < n:
                g = guilds_sorted[i]
                i += 1
                if g.server_id not in servers_in_bucket:
                    bucket.append(g)
                    servers_in_bucket.add(g.server_id)
                else:
                    q.append(g)
                    # fallback check: if we scanned queue and no non-conflict found -> fallback
                    if scanned_queue:
                        has_non_conflict = any(x.server_id not in servers_in_bucket for x in q)
                        if not has_non_conflict:
                            q.pop()  # remove the one we just appended
                            bucket.append(g)
                            stats.fallback_adds += 1
            else:
                if q:
                    g = q.popleft()
                    bucket.append(g)
                    servers_in_bucket.add(g.server_id)
                else:
                    break

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
def pair_bucket_min_power_gap_avoid_same_server(bucket: List[Guild]) -> List[Pair]:
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

def analyze(buckets: List[List[Guild]], pairing_fn, stats: BucketBuildStats, thresholds):
    all_pairs = []
    bucket_unique_counts = []
    bucket_power_ranges = []
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

    rep = {
        "buckets_count": len(buckets),
        "total_pairs": total_pairs,
        "cross_server_pairs": cross_server,
        "same_server_pairs": same_server,
        "same_server_pair_rate": same_rate,
        "bucket_unique_servers_p50": percentile(bucket_unique_counts, 0.50),
        "bucket_unique_servers_p10": percentile(bucket_unique_counts, 0.10),
        "bucket_unique_servers_p90": percentile(bucket_unique_counts, 0.90),
        "match_power_gap_p50": percentile(gaps, 0.50),
        "match_power_gap_p90": percentile(gaps, 0.90),
        "match_power_gap_max": max(gaps) if gaps else float("nan"),
        "bucket_power_range_p50": percentile(bucket_power_ranges, 0.50),
        "bucket_power_range_p90": percentile(bucket_power_ranges, 0.90),
        "fallback_adds": stats.fallback_adds,
        "fallback_rate_per_guild": fallback_rate,
        "ok_by_power_gap": (percentile(gaps, 0.90) <= thresholds["power_gap_ok_p90"]) if gaps else True,
        "ok_by_same_server_rate": (same_rate <= thresholds["same_server_rate_ok"]) if total_pairs else True,
        "gaps": gaps,
        "bucket_unique_counts": bucket_unique_counts,
        "bucket_power_ranges": bucket_power_ranges,
        "thresholds": thresholds,
    }
    return rep

def mm_health_score(rep: dict, fallback_rate_warn: float = 0.01) -> Tuple[int, int, List[str]]:
    """
    Lightweight overall health:
      +1 power balance ok (p90 gap <= threshold)
      +1 cross-server ok (same-server rate <= threshold)
      +1 algorithm pressure ok (fallback_rate_per_guild <= warn)
    """
    score = 0
    max_score = 3
    notes = []

    if rep.get("ok_by_power_gap", True):
        score += 1
    else:
        notes.append("Power balance: p90 gap above target")

    if rep.get("ok_by_same_server_rate", True):
        score += 1
    else:
        notes.append("Cross-server: same-server rate above target")

    if rep.get("fallback_rate_per_guild", 0.0) <= fallback_rate_warn:
        score += 1
    else:
        notes.append("Bucket build: elevated fallback pressure")

    return score, max_score, notes

# -----------------------------
# Utilities: CSV read and synthetic generator
# -----------------------------
def read_guilds_csv(uploaded_file) -> List[Guild]:
    df = pd.read_csv(uploaded_file)
    must_cols = {"guild_id", "server_id", "power"}
    if not must_cols.issubset(set(df.columns)):
        raise ValueError(f"CSV must contain columns: {must_cols}")
    out = []
    for _, row in df.iterrows():
        out.append(Guild(guild_id=str(row["guild_id"]), server_id=str(row["server_id"]), power=float(row["power"])))
    return out

def gen_synthetic(servers: int, guilds_per_server: int, seed: int, power_mu: float, power_sigma: float, server_strength_sigma: float) -> List[Guild]:
    rnd = random.Random(seed)
    out = []
    server_offsets = [rnd.gauss(0, server_strength_sigma) for _ in range(servers)]
    for s in range(servers):
        for g in range(guilds_per_server):
            power = max(0.0, rnd.gauss(power_mu + server_offsets[s], power_sigma))
            out.append(Guild(guild_id=f"S{s}_G{g}", server_id=f"S{s}", power=power))
    return out

# -----------------------------
# Pair-aware sorting + coloring in the SAME preview table
# -----------------------------
def build_pair_meta_maps(bucket: List[Guild], pairing_fn):
    """
    Returns:
      - key_to_pair_id: (guild_id, server_id) -> int (1..num_pairs), unpaired -> 10^9
      - key_to_label:   (guild_id, server_id) -> "same" / "cross" / None
    """
    pairs = pairing_fn(bucket)
    key_to_pair_id: Dict[tuple, int] = {}
    key_to_label: Dict[tuple, str] = {}

    for idx, p in enumerate(pairs, start=1):
        label = "same" if (p.a.server_id == p.b.server_id) else "cross"
        ka = (p.a.guild_id, p.a.server_id)
        kb = (p.b.guild_id, p.b.server_id)
        key_to_pair_id[ka] = idx
        key_to_pair_id[kb] = idx
        key_to_label[ka] = label
        key_to_label[kb] = label

    # Guilds that didn't get paired (odd bucket or pairing break)
    UNPAIRED = 10**9
    for g in bucket:
        k = (g.guild_id, g.server_id)
        if k not in key_to_pair_id:
            key_to_pair_id[k] = UNPAIRED

    return key_to_pair_id, key_to_label

def sort_bucket_df_by_pairs_then_power(df_bucket: pd.DataFrame, key_to_pair_id: Dict[tuple, int]) -> pd.DataFrame:
    df = df_bucket.copy()
    df["_pair_id"] = df.apply(lambda r: key_to_pair_id.get((str(r["guild_id"]), str(r["server_id"])), 10**9), axis=1)
    df = df.sort_values(by=["_pair_id", "power"], ascending=[True, False], kind="mergesort").drop(columns=["_pair_id"])
    return df

def style_bucket_df_by_pairs(df_bucket: pd.DataFrame, key_to_label: Dict[tuple, str]) -> "pd.io.formats.style.Styler":
    # Font-only coloring for theme-agnostic readability
    GREEN = "#2ECC71"  # cross-server
    RED = "#FF5C5C"    # same-server
    NEUTRAL = ""

    def row_style(row):
        k = (str(row.get("guild_id", "")), str(row.get("server_id", "")))
        label = key_to_label.get(k)
        if label == "cross":
            return [f"color: {GREEN}; font-weight: 600"] * len(row)
        if label == "same":
            return [f"color: {RED}; font-weight: 700"] * len(row)
        return [NEUTRAL] * len(row)

    if df_bucket.empty:
        return df_bucket.style
    return df_bucket.style.apply(row_style, axis=1)

def dataframe_height_for_rows(n_rows: int, row_px: int = 35, header_px: int = 38, padding_px: int = 6) -> int:
    # Streamlit dataframe row height is ~35px (varies slightly), this avoids inner scroll for small tables.
    n = max(1, int(n_rows))
    return header_px + n * row_px + padding_px

# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="MM Prototype (RU)", layout="wide")
st.title("Прототип MM")
st.markdown("Демонстрация алгоритма, визуализация бакетов и аналитика пар матчей.")

with st.sidebar:
    st.header("Входные данные")
    uploaded = st.file_uploader("Загрузить CSV (columns: guild_id, server_id, power)", type=["csv"])
    st.markdown("---")
    st.header("Синтетика (если CSV не загружен)")
    servers = st.number_input("Кол-во серверов", value=2000, min_value=2, step=1)
    guilds_per_server = st.number_input("Гильдий на сервер", value=200, min_value=1, step=1)
    seed = st.number_input("Seed", value=1, step=1)
    power_mu = st.number_input("Power μ", value=100000.0, step=1000.0, format="%.1f")
    power_sigma = st.number_input("Power σ", value=15000.0, step=100.0, format="%.1f")
    server_strength_sigma = st.number_input("Server strength σ", value=8000.0, step=100.0, format="%.1f")
    st.markdown("---")
    st.header("Алгоритм / настройки")
    bucket_size = st.number_input("Размер бакета", value=16, min_value=2, step=1)
    power_gap_ok_p90 = st.number_input("Target: power gap p90", value=5000.0, step=100.0, format="%.1f")
    same_server_rate_ok = st.number_input("Target: same-server rate", value=0.02, step=0.001, format="%.3f")
    show_buckets = st.number_input("Показать N бакетов (preview)", value=3, min_value=1, step=1)

    # Instead of partial bucket, default to full bucket view (no inner scroll)
    show_rows = st.number_input("Строк в бакете (preview)", value=int(bucket_size), min_value=1, step=1)
    run_button = st.button("Запустить прототип")

st.sidebar.markdown("## Формат CSV пример")
st.sidebar.code("guild_id,server_id,power\ng001,s01,123456\ng002,s02,122900")

if run_button:
    try:
        if uploaded is not None:
            guilds = read_guilds_csv(uploaded)
        else:
            with st.spinner("Генерируем синтетические данные..."):
                guilds = gen_synthetic(
                    servers=int(servers),
                    guilds_per_server=int(guilds_per_server),
                    seed=int(seed),
                    power_mu=float(power_mu),
                    power_sigma=float(power_sigma),
                    server_strength_sigma=float(server_strength_sigma),
                )

        st.write(f"Всего гильдий: {len(guilds)}")

        guilds_sorted = sorted(guilds, key=lambda g: g.power, reverse=True)
        buckets, stats = build_buckets_as_is(guilds_sorted, bucket_size=int(bucket_size))

        st.subheader("Preview бакетов")
        st.caption("Сортировка: сначала по парам, затем по power. Подсветка: зелёный=cross-server, красный=same-server (обе гильдии пары).")

        for bi in range(min(len(buckets), int(show_buckets))):
            b = buckets[bi]
            uniq = len({g.server_id for g in b})
            st.markdown(f"**Бакет #{bi+1} (size={len(b)}, unique_servers={uniq})**")

            df = pd.DataFrame([{"guild_id": g.guild_id, "server_id": g.server_id, "power": g.power} for g in b])

            key_to_pair_id, key_to_label = build_pair_meta_maps(b, pairing_fn=pair_bucket_min_power_gap_avoid_same_server)
            df_sorted = sort_bucket_df_by_pairs_then_power(df, key_to_pair_id)

            # show full (or user-limited) bucket list, but without inner scroll
            df_preview = df_sorted.head(int(show_rows)).copy()
            styled = style_bucket_df_by_pairs(df_preview, key_to_label)
            h = dataframe_height_for_rows(len(df_preview))

            st.dataframe(styled, use_container_width=True, height=h)

        rep = analyze(
            buckets=buckets,
            pairing_fn=pair_bucket_min_power_gap_avoid_same_server,
            stats=stats,
            thresholds={"power_gap_ok_p90": float(power_gap_ok_p90), "same_server_rate_ok": float(same_server_rate_ok)},
        )

        # -----------------------------
        # Improved analytics (compact, readable)
        # -----------------------------
        st.subheader("MM Analytics")

        score, score_max, notes = mm_health_score(rep, fallback_rate_warn=0.01)
        # 3 columns: Match balance / Cross-server / Bucket build
        colA, colB, colC = st.columns(3)

        # A) Match balance
        with colA:
            st.markdown("**Match balance**")
            st.metric("Gap p50", f'{rep["match_power_gap_p50"]:.0f}')
            st.metric(
                f'Gap p90 (target ≤ {rep["thresholds"]["power_gap_ok_p90"]:.0f})',
                f'{rep["match_power_gap_p90"]:.0f}',
            )
            st.metric("Gap max", f'{rep["match_power_gap_max"]:.0f}')

        # B) Cross-server
        with colB:
            st.markdown("**Cross-server quality**")
            st.metric(
                f'Same-server rate (target ≤ {rep["thresholds"]["same_server_rate_ok"]:.3f})',
                f'{rep["same_server_pair_rate"]:.3%}',
            )
            st.metric("Same-server matches", f'{rep["same_server_pairs"]}')
            st.metric("Matches total", f'{rep["total_pairs"]}')

        # C) Bucket build
        with colC:
            st.markdown("**Bucket build**")
            st.metric("Unique servers / bucket (p50)", f'{rep["bucket_unique_servers_p50"]:.1f}')
            st.metric("Bucket power spread (p90)", f'{rep["bucket_power_range_p90"]:.0f}')
            st.metric("Fallback pressure", f'{rep["fallback_rate_per_guild"]:.4f}')

        # Overall verdict line (compact)
        verdict_icon = "✅" if score == score_max else ("⚠️" if score >= 2 else "❌")
        st.markdown(f"**MM Health:** {score}/{score_max} {verdict_icon}")

        if notes:
            # One compact, readable line (no wall of text)
            st.caption(" • ".join(notes))

        # Keep detailed stuff collapsed
        with st.expander("Technical details"):
            st.write(f'Power gap p90 OK: {rep["ok_by_power_gap"]} — (target {power_gap_ok_p90})')
            st.write(f'Same-server rate OK: {rep["ok_by_same_server_rate"]} — (target {same_server_rate_ok})')
            st.write(f"Buckets: {rep['buckets_count']}")
            st.write(f"Fallback adds: {stats.fallback_adds}")

            # optional extra percentiles if needed
            st.write(f"Unique servers / bucket p10/p90: {rep['bucket_unique_servers_p10']:.1f} / {rep['bucket_unique_servers_p90']:.1f}")
            st.write(f"Bucket power spread p50: {rep['bucket_power_range_p50']:.0f}")

        # -----------------------------
        # Existing charts + diagnostics (unchanged)
        # -----------------------------
        gaps = rep["gaps"]
        if gaps:
            st.subheader("Гистограмма разницы power в парах")
            fig, ax = plt.subplots(figsize=(6, 3))
            ax.hist(gaps, bins=40)
            ax.set_xlabel("abs(power_a - power_b)")
            ax.set_ylabel("count")
            st.pyplot(fig)

        counts = rep["bucket_unique_counts"]
        if counts:
            st.subheader("Распределение уникальности серверов в бакетах")
            fig2, ax2 = plt.subplots(figsize=(6, 3))
            ax2.hist(counts, bins=range(min(counts), max(counts) + 2))
            ax2.set_xlabel("Уникальных серверов в бакете")
            ax2.set_ylabel("count")
            st.pyplot(fig2)

        server_internal = Counter()
        for b in buckets:
            pairs = pair_bucket_min_power_gap_avoid_same_server(b)
            for p in pairs:
                if p.a.server_id == p.b.server_id:
                    server_internal[p.a.server_id] += 1
        if server_internal:
            st.subheader("Топ серверов по внутр. матчам (same-server)")
            top_df = pd.DataFrame(server_internal.most_common(20), columns=["server_id", "same_server_matches"])
            st.dataframe(top_df)

        # Export results: buckets & pairs as csv downloadable
        export_buckets = []
        for bi, b in enumerate(buckets):
            for g in b:
                export_buckets.append({"bucket_id": bi + 1, "guild_id": g.guild_id, "server_id": g.server_id, "power": g.power})
        df_export_buckets = pd.DataFrame(export_buckets)

        export_pairs = []
        for bi, b in enumerate(buckets):
            pairs = pair_bucket_min_power_gap_avoid_same_server(b)
            for p in pairs:
                export_pairs.append(
                    {
                        "bucket_id": bi + 1,
                        "a_guild": p.a.guild_id,
                        "a_server": p.a.server_id,
                        "a_power": p.a.power,
                        "b_guild": p.b.guild_id,
                        "b_server": p.b.server_id,
                        "b_power": p.b.power,
                    }
                )
        df_export_pairs = pd.DataFrame(export_pairs)

        st.download_button(
            "Скачать buckets.csv",
            df_export_buckets.to_csv(index=False).encode("utf-8"),
            "buckets.csv",
            "text/csv",
        )
        st.download_button(
            "Скачать pairs.csv",
            df_export_pairs.to_csv(index=False).encode("utf-8"),
            "pairs.csv",
            "text/csv",
        )

    except Exception as e:
        st.error(f"Ошибка: {e}")

else:
    st.info("Настройте параметры в сайдбаре и нажмите 'Запустить прототип' для генерации бакетов и аналитики.")
