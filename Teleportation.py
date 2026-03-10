import math
import random
from dataclasses import dataclass
from typing import List, Tuple, Set, Dict, Optional

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt


# =========================
# Core geometry / metrics
# =========================

@dataclass(frozen=True)
class Base:
    id: int
    x: int
    y: int


def dist(a: Base, b: Base, metric: str) -> float:
    dx = a.x - b.x
    dy = a.y - b.y
    if metric == "Манхэттен":
        return abs(dx) + abs(dy)
    return math.hypot(dx, dy)


def score_sum_distances(bases: List[Base], metric: str) -> List[float]:
    """Текущий алгоритм: сумма дистанций до всех остальных."""
    n = len(bases)
    scores = [0.0] * n
    for i in range(n):
        s = 0.0
        for j in range(n):
            if i == j:
                continue
            s += dist(bases[i], bases[j], metric)
        scores[i] = s
    return scores


def pick_best_base_global(bases: List[Base], metric: str) -> Tuple[Base, pd.DataFrame]:
    """Текущий алгоритм (глобальный медоид): выбираем базу с минимальной суммой дистанций до всех."""
    scores = score_sum_distances(bases, metric)
    df = pd.DataFrame({
        "id": [b.id for b in bases],
        "x": [b.x for b in bases],
        "y": [b.y for b in bases],
        "Сумма дистанций S_i": scores,
    }).sort_values("Сумма дистанций S_i", ascending=True).reset_index(drop=True)
    best_id = int(df.loc[0, "id"])
    best = next(b for b in bases if b.id == best_id)
    return best, df


# =========================
# Clustering (graph components)
# =========================

def k3_median_distance(bases: List[Base], metric: str) -> float:
    """
    Авто-оценка 'типичной близости':
    берём дистанцию до 3-го ближайшего соседа для каждой базы,
    возвращаем медиану.
    """
    n = len(bases)
    if n <= 3:
        return 1.0
    third = []
    for i in range(n):
        ds = []
        for j in range(n):
            if i == j:
                continue
            ds.append(dist(bases[i], bases[j], metric))
        ds.sort()
        # 3-й ближайший -> index 2
        third.append(ds[min(2, len(ds) - 1)])
    m = float(np.median(third))
    return max(1.0, m)


def build_clusters_components(
    bases: List[Base],
    metric: str,
    link_radius: float,
) -> List[List[int]]:
    """
    Кластеризация через компоненты связности:
    соединяем i-j, если dist(i,j) <= link_radius.
    """
    n = len(bases)
    if n == 0:
        return []
    adj: List[List[int]] = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if dist(bases[i], bases[j], metric) <= link_radius:
                adj[i].append(j)
                adj[j].append(i)

    seen = [False] * n
    clusters: List[List[int]] = []
    for i in range(n):
        if seen[i]:
            continue
        # BFS/DFS
        stack = [i]
        seen[i] = True
        comp = []
        while stack:
            v = stack.pop()
            comp.append(v)
            for u in adj[v]:
                if not seen[u]:
                    seen[u] = True
                    stack.append(u)
        clusters.append(sorted(comp))
    # для стабильности — сортируем кластеры по размеру убыв., потом по min id
    clusters.sort(key=lambda c: (-len(c), min(c)))
    return clusters


def pick_cluster(
    bases: List[Base],
    clusters: List[List[int]],
    pick_mode: str,
) -> int:
    """
    Возвращает индекс кластера в списке clusters.
    - 'Самый большой': max size
    - 'Самый плотный': max средняя внутренняя степень (упрощённо)
    """
    if not clusters:
        return 0
    if pick_mode == "Самый большой":
        return 0

    # Самый плотный (простая эвристика):
    # плотность ~ average pairwise distance inversed (меньше -> плотнее)
    best_idx = 0
    best_score = None
    for idx, comp in enumerate(clusters):
        if len(comp) <= 1:
            score = -1e9
        else:
            # средняя дистанция внутри кластера (меньше = лучше)
            ds = []
            for a_i in range(len(comp)):
                for b_i in range(a_i + 1, len(comp)):
                    a = bases[comp[a_i]]
                    b = bases[comp[b_i]]
                    ds.append(dist(a, b, metric_global_for_density))
            score = -float(np.mean(ds))  # максимизируем -mean
        if best_score is None or score > best_score:
            best_score = score
            best_idx = idx
    return best_idx


def score_within_subset(bases: List[Base], subset_idx: List[int], metric: str) -> Dict[int, float]:
    """Сумма дистанций, но только внутри subset."""
    scores: Dict[int, float] = {}
    for ii in subset_idx:
        s = 0.0
        for jj in subset_idx:
            if ii == jj:
                continue
            s += dist(bases[ii], bases[jj], metric)
        scores[ii] = s
    return scores


def pick_best_base_clustered(
    bases: List[Base],
    metric: str,
    link_radius: float,
    cluster_pick_mode: str,
) -> Tuple[Base, pd.DataFrame, List[List[int]], int]:
    """
    Новый алгоритм:
    1) режем на кластеры (компоненты связности по link_radius)
    2) выбираем один кластер (обычно крупнейший)
    3) внутри кластера выбираем медоид (минимальная сумма дистанций внутри кластера)
    """
    clusters = build_clusters_components(bases, metric, link_radius)
    chosen_cluster_idx = 0
    if clusters:
        # "Самый плотный" требует metric внутри функции — чуть костыльно, но прозрачно
        global metric_global_for_density
        metric_global_for_density = metric
        if cluster_pick_mode == "Самый большой":
            chosen_cluster_idx = 0
        else:
            # пересчёт плотности внутри здесь (чтобы без лишних параметров в pick_cluster)
            best_idx = 0
            best_score = None
            for idx, comp in enumerate(clusters):
                if len(comp) <= 1:
                    score = -1e9
                else:
                    ds = []
                    for a_i in range(len(comp)):
                        for b_i in range(a_i + 1, len(comp)):
                            a = bases[comp[a_i]]
                            b = bases[comp[b_i]]
                            ds.append(dist(a, b, metric))
                    score = -float(np.mean(ds))  # меньше средняя дистанция -> выше score
                if best_score is None or score > best_score:
                    best_score = score
                    best_idx = idx
            chosen_cluster_idx = best_idx

    chosen = clusters[chosen_cluster_idx] if clusters else list(range(len(bases)))
    scores_in = score_within_subset(bases, chosen, metric)

    # Для таблицы: покажем и глобальный скор, и скор внутри кластера
    global_scores = score_sum_distances(bases, metric)
    cluster_id_of = {}
    for cid, comp in enumerate(clusters):
        for ii in comp:
            cluster_id_of[ii] = cid

    rows = []
    for idx, b in enumerate(bases):
        rows.append({
            "id": b.id,
            "x": b.x,
            "y": b.y,
            "cluster": cluster_id_of.get(idx, -1),
            "cluster_size": len(clusters[cluster_id_of[idx]]) if idx in cluster_id_of else 0,
            "S_global": global_scores[idx],
            "S_in_cluster": scores_in.get(idx, np.nan),
            "В выбранном кластере": (idx in chosen),
        })
    df = pd.DataFrame(rows)

    # Ранжируем по S_in_cluster (только для выбранного кластера), иначе вверх не тянем
    df_rank = df[df["В выбранном кластере"]].copy()
    df_rank = df_rank.sort_values("S_in_cluster", ascending=True).reset_index(drop=True)

    # лучший — минимальный S_in_cluster
    best_id = int(df_rank.loc[0, "id"])
    best = next(b for b in bases if b.id == best_id)

    return best, df, clusters, chosen_cluster_idx


# =========================
# Teleport zone
# =========================

def cells_in_radius(cx, cy, R, shape, w, h):
    res = []
    x0 = max(0, cx - R)
    x1 = min(w - 1, cx + R)
    y0 = max(0, cy - R)
    y1 = min(h - 1, cy + R)

    r2 = R * R
    for x in range(x0, x1 + 1):
        dx = x - cx
        for y in range(y0, y1 + 1):
            dy = y - cy
            if shape == "Круг":
                if dx * dx + dy * dy <= r2:
                    res.append((x, y))
            elif shape == "Ромб":
                if abs(dx) + abs(dy) <= R:
                    res.append((x, y))
            else:
                if max(abs(dx), abs(dy)) <= R:
                    res.append((x, y))
    return res


def teleport_players(best, occupied, blocked, w, h, R, shape, n_players, seed, unique):
    rng = random.Random(seed)
    candidates = cells_in_radius(best.x, best.y, R, shape, w, h)
    forbidden = occupied | blocked
    free = [c for c in candidates if c not in forbidden]
    rng.shuffle(free)

    teleports = []
    fails = 0
    used = set()

    for _ in range(n_players):
        if not free:
            fails += 1
            continue
        if unique:
            pick = None
            while free:
                c = free.pop()
                if c not in used:
                    pick = c
                    used.add(c)
                    break
            if pick:
                teleports.append(pick)
            else:
                fails += 1
        else:
            teleports.append(rng.choice(free))

    return {
        "teleports": teleports,
        "fails": fails,
        "candidate_count": len(candidates),
        "free_count": len(free),
    }


# =========================
# Base generation
# =========================

def gen_uniform(w, h, n, seed, used):
    rng = random.Random(seed)
    bases = []
    while len(bases) < n:
        x = rng.randrange(w)
        y = rng.randrange(h)
        if (x, y) in used:
            continue
        used.add((x, y))
        bases.append(Base(len(bases), x, y))
    return bases


def gen_cluster(w, h, n, seed, spread, used):
    rng = random.Random(seed)
    cx = rng.randrange(w)
    cy = rng.randrange(h)
    bases = []
    while len(bases) < n:
        x = int(round(rng.gauss(cx, spread)))
        y = int(round(rng.gauss(cy, spread)))
        if not (0 <= x < w and 0 <= y < h):
            continue
        if (x, y) in used:
            continue
        used.add((x, y))
        bases.append(Base(len(bases), x, y))
    return bases


def gen_multi_clusters(w, h, n, seed, k, spread, min_sep, used):
    """
    Генерация K кластеров:
    - выбираем K центров так, чтобы они были не слишком близко друг к другу (min_sep)
    - распределяем n баз по кластерам (почти равномерно)
    """
    rng = random.Random(seed)

    # 1) центры
    centers: List[Tuple[int, int]] = []
    tries = 0
    while len(centers) < k and tries < 50_000:
        tries += 1
        cx = rng.randrange(w)
        cy = rng.randrange(h)
        ok = True
        for (px, py) in centers:
            if math.hypot(cx - px, cy - py) < min_sep:
                ok = False
                break
        if ok:
            centers.append((cx, cy))
    if len(centers) < k:
        # если не смогли разнести — просто добьём без min_sep
        while len(centers) < k:
            centers.append((rng.randrange(w), rng.randrange(h)))

    # 2) размеры кластеров
    base_counts = [n // k] * k
    for i in range(n % k):
        base_counts[i] += 1
    rng.shuffle(base_counts)

    # 3) генерим
    bases: List[Base] = []
    for ci, cnt in enumerate(base_counts):
        cx, cy = centers[ci]
        made = 0
        guard = 0
        while made < cnt and guard < 200_000:
            guard += 1
            x = int(round(rng.gauss(cx, spread)))
            y = int(round(rng.gauss(cy, spread)))
            if not (0 <= x < w and 0 <= y < h):
                continue
            if (x, y) in used:
                continue
            used.add((x, y))
            bases.append(Base(len(bases), x, y))
            made += 1

    # если из-за коллизий/границ не добили — докидываем равномерно
    while len(bases) < n:
        x = rng.randrange(w)
        y = rng.randrange(h)
        if (x, y) in used:
            continue
        used.add((x, y))
        bases.append(Base(len(bases), x, y))

    return bases, centers


# =========================
# UI
# =========================

st.set_page_config(page_title="VS: Точка входа телепорта", layout="wide")
st.title("VS: Прототип точки входа телепорта")

st.sidebar.header("Карта")
w = st.sidebar.slider("Ширина", 30, 200, 120)
h = st.sidebar.slider("Высота", 30, 200, 120)
seed = st.sidebar.number_input("Seed", 0, 10_000_000, 12345)

st.sidebar.header("Базы врага")
n_enemy = st.sidebar.slider("Количество", 3, 200, 35)
mode = st.sidebar.selectbox("Тип генерации", ["Равномерно", "Кластер", "Мульти-кластеры"])
metric = st.sidebar.selectbox("Метрика", ["Манхэттен", "Евклид"])

used_global: Set[Tuple[int, int]] = set()
enemy_centers = None

if mode == "Равномерно":
    enemy_bases = gen_uniform(w, h, n_enemy, seed, used_global)
elif mode == "Кластер":
    spread = st.sidebar.slider("Разброс кластера", 1.0, 20.0, 6.0)
    enemy_bases = gen_cluster(w, h, n_enemy, seed, spread, used_global)
else:
    k = st.sidebar.slider("Количество кластеров", 2, 8, 3)
    spread = st.sidebar.slider("Разброс кластеров", 1.0, 25.0, 6.0)
    min_sep = st.sidebar.slider("Минимальная дистанция между центрами", 5.0, 120.0, 35.0)
    enemy_bases, enemy_centers = gen_multi_clusters(w, h, n_enemy, seed, k, spread, min_sep, used_global)

st.sidebar.header("Алгоритм точки входа")
algo = st.sidebar.radio(
    "Режим",
    ["Текущий (глобальная центральность)", "Кластеры (выбрать кластер -> центр кластера)"],
)

cluster_link_mode = None
cluster_pick_mode = None
link_radius = None

if algo.startswith("Кластеры"):
    cluster_pick_mode = st.sidebar.selectbox("Какой кластер выбирать", ["Самый большой", "Самый плотный"])
    cluster_link_mode = st.sidebar.selectbox("Как соединять в кластеры", ["Авто", "Ручной радиус связи"])
    if cluster_link_mode == "Авто":
        tau = k3_median_distance(enemy_bases, metric)
        # немного расширяем, чтобы “свои рядом” чаще попадали в один кластер
        link_radius = st.sidebar.slider("Авто-коэф. радиуса (kNN * coef)", 1.0, 3.0, 1.6, 0.05)
        link_radius = float(link_radius) * tau
        st.sidebar.caption(f"Авто-оценка kNN-масштаба ≈ {tau:.2f} → link_radius ≈ {link_radius:.2f}")
    else:
        link_radius = st.sidebar.slider("Радиус связи (link_radius)", 1.0, 120.0, 18.0, 1.0)

st.sidebar.header("Базы нейтралов")
enable_neutral = st.sidebar.checkbox("Добавить нейтралов", True)
neutral_bases: List[Base] = []
if enable_neutral:
    n_neutral = st.sidebar.slider("Количество нейтралов", 0, 200, 20)
    neutral_bases = gen_uniform(w, h, n_neutral, seed + 999, used_global)

enemy_set = {(b.x, b.y) for b in enemy_bases}
neutral_set = {(b.x, b.y) for b in neutral_bases}
occupied = enemy_set | neutral_set

st.sidebar.header("Обстаклы")
density = st.sidebar.slider("Плотность", 0.0, 0.4, 0.05)
blocked: Set[Tuple[int, int]] = set()
rng = random.Random(seed + 555)
for _ in range(int(w * h * density)):
    x = rng.randrange(w)
    y = rng.randrange(h)
    if (x, y) not in occupied:
        blocked.add((x, y))

# ---- Pick best base according to chosen algorithm
clusters = []
chosen_cluster_idx = -1

if algo.startswith("Текущий"):
    best_enemy, ranking = pick_best_base_global(enemy_bases, metric)
    algo_label = "Текущий: глобальная центральность (медоид по всем)"
else:
    best_enemy, df_all, clusters, chosen_cluster_idx = pick_best_base_clustered(
        enemy_bases, metric, float(link_radius), cluster_pick_mode
    )
    # ranking: топ по выбранному кластеру
    ranking = df_all[df_all["В выбранном кластере"]].copy()
    ranking = ranking.sort_values("S_in_cluster", ascending=True).reset_index(drop=True)
    algo_label = "Новый: кластеры -> выбранный кластер -> центр (медоид внутри кластера)"

st.sidebar.header("Телепорт")
R = st.sidebar.slider("Радиус", 1, 50, 10)
shape = st.sidebar.selectbox("Форма зоны", ["Круг", "Ромб", "Квадрат"])
players = st.sidebar.slider("Игроков", 1, 200, 50)

tp = teleport_players(best_enemy, occupied, blocked, w, h, R, shape, players, seed + 777, True)

left, right = st.columns([1.4, 1])

with left:
    fig, ax = plt.subplots(figsize=(7, 7))

    # obstacles
    if blocked:
        bx = [c[0] for c in blocked]
        by = [c[1] for c in blocked]
        ax.scatter(bx, by, s=10, color="gray", marker="s", label="Обстаклы")

    # neutral
    if neutral_bases:
        nx = [b.x for b in neutral_bases]
        ny = [b.y for b in neutral_bases]
        ax.scatter(nx, ny, s=35, color="gold", label="Нейтралы")

    # enemy plotting (cluster-aware)
    ex = [b.x for b in enemy_bases]
    ey = [b.y for b in enemy_bases]

    if algo.startswith("Кластеры") and clusters:
        # раскрасим кластеры разными цветами (простая палитра)
        palette = ["red", "blue", "purple", "orange", "brown", "pink", "olive", "cyan"]
        for cid, comp in enumerate(clusters):
            cx = [enemy_bases[i].x for i in comp]
            cy = [enemy_bases[i].y for i in comp]
            col = palette[cid % len(palette)]
            lbl = f"Враг (кластер {cid}, n={len(comp)})"
            ax.scatter(cx, cy, s=35, color=col, label=lbl, alpha=0.9 if cid == chosen_cluster_idx else 0.5)

        # подчёркиваем выбранный кластер
        chosen = set(clusters[chosen_cluster_idx])
        chx = [enemy_bases[i].x for i in chosen]
        chy = [enemy_bases[i].y for i in chosen]
        ax.scatter(chx, chy, s=85, facecolors="none", edgecolors="black", linewidths=1.3, label="Выбранный кластер")

        # если генерили мульти-кластеры — покажем центры
        if enemy_centers:
            ccx = [c[0] for c in enemy_centers]
            ccy = [c[1] for c in enemy_centers]
            ax.scatter(ccx, ccy, s=80, marker="P", color="black", label="Центры генерации")
    else:
        ax.scatter(ex, ey, s=35, color="red", label="Враг")

    # chosen base
    ax.scatter([best_enemy.x], [best_enemy.y], s=220, marker="*", color="black", label="Точка входа (база)")

    # teleports
    if tp["teleports"]:
        tx = [t[0] for t in tp["teleports"]]
        ty = [t[1] for t in tp["teleports"]]
        ax.scatter(tx, ty, s=30, marker="x", color="green", label="Телепорт")

    circ = plt.Circle((best_enemy.x, best_enemy.y), R, fill=False, linestyle="--", color="black", alpha=0.7)
    ax.add_patch(circ)

    ax.set_xlim(-1, w)
    ax.set_ylim(-1, h)
    ax.set_aspect("equal")
    ax.set_title(algo_label)
    ax.legend(loc="upper right", fontsize=8)
    st.pyplot(fig)

with right:
    st.subheader("Результат")
    st.write(f"**Алгоритм:** {algo_label}")
    if algo.startswith("Кластеры") and clusters:
        st.write(f"**Кластеры:** {len(clusters)} | **Выбран:** {chosen_cluster_idx} (n={len(clusters[chosen_cluster_idx])})")
        st.write(f"**link_radius:** {float(link_radius):.2f} ({'Авто' if cluster_link_mode=='Авто' else 'Ручной'})")

    st.write(f"**Точка входа (база):** id={best_enemy.id} ({best_enemy.x},{best_enemy.y})")
    st.write(f"**Успешных телепортов:** {len(tp['teleports'])}/{players}")
    st.write(f"**Не удалось разместить:** {tp['fails']}")

    st.subheader("Топ баз по ранжированию")
    if algo.startswith("Текущий"):
        st.dataframe(ranking.head(10), use_container_width=True)
    else:
        view = ranking[["id", "x", "y", "cluster", "cluster_size", "S_in_cluster", "S_global"]].copy()
        view = view.rename(columns={
            "S_in_cluster": "Сумма дистанций (внутри кластера)",
            "S_global": "Сумма дистанций (глобально)",
        })
        st.dataframe(view.head(10), use_container_width=True)

    with st.expander("Диагностика (таблица всех баз)"):
        if algo.startswith("Текущий"):
            st.dataframe(ranking, use_container_width=True)
        else:
            st.dataframe(
                df_all.sort_values(["В выбранном кластере", "S_in_cluster"], ascending=[False, True]),
                use_container_width=True
            )
