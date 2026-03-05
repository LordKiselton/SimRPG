import math
import random
from dataclasses import dataclass
from typing import List, Tuple, Set, Optional, Dict

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
    if metric == "Manhattan":
        return abs(dx) + abs(dy)
    # Euclidean
    return math.hypot(dx, dy)

def score_sum_distances(bases: List[Base], metric: str) -> List[float]:
    # O(n^2) – достаточно для прототипа
    n = len(bases)
    scores = [0.0] * n
    for i in range(n):
        s = 0.0
        ai = bases[i]
        for j in range(n):
            if i == j:
                continue
            s += dist(ai, bases[j], metric)
        scores[i] = s
    return scores

def pick_best_base(bases: List[Base], metric: str) -> Tuple[Base, pd.DataFrame]:
    scores = score_sum_distances(bases, metric)
    df = pd.DataFrame({
        "id": [b.id for b in bases],
        "x": [b.x for b in bases],
        "y": [b.y for b in bases],
        "score_sum_dist": scores,
    }).sort_values("score_sum_dist", ascending=True).reset_index(drop=True)
    best_id = int(df.loc[0, "id"])
    best = next(b for b in bases if b.id == best_id)
    return best, df

def cells_in_radius(cx: int, cy: int, R: int, shape: str, w: int, h: int) -> List[Tuple[int, int]]:
    """
    Возвращает список клеток в радиусе R вокруг (cx,cy).
    shape:
      - "Circle (Euclid)" => dx^2 + dy^2 <= R^2
      - "Diamond (Manhattan)" => |dx|+|dy| <= R
      - "Square (Chebyshev)" => max(|dx|,|dy|) <= R
    """
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
            if shape == "Circle (Euclid)":
                if dx * dx + dy * dy <= r2:
                    res.append((x, y))
            elif shape == "Diamond (Manhattan)":
                if abs(dx) + abs(dy) <= R:
                    res.append((x, y))
            else:  # Square (Chebyshev)
                if max(abs(dx), abs(dy)) <= R:
                    res.append((x, y))
    return res

def teleport_players(
    best: Base,
    bases_set: Set[Tuple[int, int]],
    blocked_set: Set[Tuple[int, int]],
    w: int,
    h: int,
    R: int,
    area_shape: str,
    n_players: int,
    seed: int,
    unique_cells: bool,
) -> Dict:
    rng = random.Random(seed)

    candidates = cells_in_radius(best.x, best.y, R, area_shape, w, h)
    # запрещаем клетку самой базы + любые занятые/заблокированные
    forbidden = set(bases_set) | set(blocked_set)

    free = [c for c in candidates if c not in forbidden]
    rng.shuffle(free)

    teleports = []
    used = set()
    fails = 0

    if unique_cells:
        # каждому игроку — уникальная клетка
        for i in range(n_players):
            pick = None
            while free:
                c = free.pop()
                if c in used:
                    continue
                pick = c
                break
            if pick is None:
                fails += 1
            else:
                used.add(pick)
                teleports.append(pick)
    else:
        # можно в одну и ту же клетку (иногда полезно проверить плотность)
        for i in range(n_players):
            if not free:
                fails += 1
                continue
            teleports.append(rng.choice(free))

    return {
        "teleports": teleports,
        "fails": fails,
        "free_count": len(free),
        "candidate_count": len(candidates),
    }


# =========================
# Base generation
# =========================

def gen_uniform(w: int, h: int, n: int, seed: int) -> List[Base]:
    rng = random.Random(seed)
    used = set()
    bases = []
    while len(bases) < n:
        x = rng.randrange(w)
        y = rng.randrange(h)
        if (x, y) in used:
            continue
        used.add((x, y))
        bases.append(Base(id=len(bases), x=x, y=y))
    return bases

def gen_cluster(w: int, h: int, n: int, seed: int, spread: float = 6.0) -> List[Base]:
    rng = random.Random(seed)
    cx = rng.randrange(w)
    cy = rng.randrange(h)
    used = set()
    bases = []
    # гаусс вокруг центра
    while len(bases) < n:
        x = int(round(rng.gauss(cx, spread)))
        y = int(round(rng.gauss(cy, spread)))
        if not (0 <= x < w and 0 <= y < h):
            continue
        if (x, y) in used:
            continue
        used.add((x, y))
        bases.append(Base(id=len(bases), x=x, y=y))
    return bases

def gen_two_clusters(w: int, h: int, n: int, seed: int, spread: float = 5.0, balance: float = 0.6) -> List[Base]:
    rng = random.Random(seed)
    n1 = max(1, int(round(n * balance)))
    n2 = n - n1
    c1 = (rng.randrange(w), rng.randrange(h))
    c2 = (rng.randrange(w), rng.randrange(h))
    used = set()
    bases = []

    def sample(center, count):
        nonlocal bases, used
        cx, cy = center
        while count > 0:
            x = int(round(rng.gauss(cx, spread)))
            y = int(round(rng.gauss(cy, spread)))
            if not (0 <= x < w and 0 <= y < h):
                continue
            if (x, y) in used:
                continue
            used.add((x, y))
            bases.append(Base(id=len(bases), x=x, y=y))
            count -= 1

    sample(c1, n1)
    sample(c2, n2)
    return bases

def gen_line(w: int, h: int, n: int, seed: int) -> List[Base]:
    rng = random.Random(seed)
    # случайная линия: выбираем 2 точки и интерполируем
    x0, y0 = rng.randrange(w), rng.randrange(h)
    x1, y1 = rng.randrange(w), rng.randrange(h)
    used = set()
    bases = []
    for i in range(n):
        t = 0 if n == 1 else i / (n - 1)
        x = int(round(x0 + (x1 - x0) * t))
        y = int(round(y0 + (y1 - y0) * t))
        x = max(0, min(w - 1, x))
        y = max(0, min(h - 1, y))
        # если дубликат — слегка смещаем
        if (x, y) in used:
            for _ in range(20):
                nx = max(0, min(w - 1, x + rng.choice([-1, 0, 1])))
                ny = max(0, min(h - 1, y + rng.choice([-1, 0, 1])))
                if (nx, ny) not in used:
                    x, y = nx, ny
                    break
        if (x, y) in used:
            continue
        used.add((x, y))
        bases.append(Base(id=len(bases), x=x, y=y))
    # добиваем, если не хватило
    while len(bases) < n:
        x = rng.randrange(w); y = rng.randrange(h)
        if (x, y) in used: 
            continue
        used.add((x, y))
        bases.append(Base(id=len(bases), x=x, y=y))
    return bases

def gen_ring(w: int, h: int, n: int, seed: int, radius: float = 20.0) -> List[Base]:
    rng = random.Random(seed)
    cx = w // 2
    cy = h // 2
    used = set()
    bases = []
    for i in range(n):
        ang = 2 * math.pi * (i / n)
        # добавим немного шума
        rr = max(1.0, rng.gauss(radius, radius * 0.08))
        x = int(round(cx + rr * math.cos(ang)))
        y = int(round(cy + rr * math.sin(ang)))
        x = max(0, min(w - 1, x))
        y = max(0, min(h - 1, y))
        if (x, y) in used:
            continue
        used.add((x, y))
        bases.append(Base(id=len(bases), x=x, y=y))
    # добиваем
    while len(bases) < n:
        x = rng.randrange(w); y = rng.randrange(h)
        if (x, y) in used:
            continue
        used.add((x, y))
        bases.append(Base(id=len(bases), x=x, y=y))
    return bases

def parse_manual_bases(text: str, w: int, h: int) -> List[Base]:
    """
    Формат:
      x,y
      x,y
    или "x y"
    """
    bases = []
    used = set()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        sep = "," if "," in ln else None
        parts = [p.strip() for p in (ln.split(",") if sep else ln.split())]
        if len(parts) != 2:
            continue
        try:
            x = int(parts[0]); y = int(parts[1])
        except ValueError:
            continue
        if not (0 <= x < w and 0 <= y < h):
            continue
        if (x, y) in used:
            continue
        used.add((x, y))
        bases.append(Base(id=len(bases), x=x, y=y))
    return bases


# =========================
# Blocked cells generation
# =========================

def gen_blocked_random(w: int, h: int, density: float, seed: int, forbidden: Set[Tuple[int,int]]) -> Set[Tuple[int,int]]:
    rng = random.Random(seed)
    total = w * h
    k = int(round(total * density))
    blocked = set()
    tries = 0
    while len(blocked) < k and tries < k * 20 + 1000:
        tries += 1
        x = rng.randrange(w)
        y = rng.randrange(h)
        c = (x, y)
        if c in forbidden:
            continue
        blocked.add(c)
    return blocked


# =========================
# Plot
# =========================

def plot_map(
    w: int,
    h: int,
    bases: List[Base],
    best: Base,
    blocked: Set[Tuple[int,int]],
    teleports: List[Tuple[int,int]],
    R: int,
    area_shape: str,
    show_grid: bool,
):
    fig, ax = plt.subplots(figsize=(7, 7))

    # blocked
    if blocked:
        bx = [c[0] for c in blocked]
        by = [c[1] for c in blocked]
        ax.scatter(bx, by, s=10, marker="s", label="Blocked")

    # bases
    xs = [b.x for b in bases]
    ys = [b.y for b in bases]
    ax.scatter(xs, ys, s=35, label="Enemy bases")

    # best
    ax.scatter([best.x], [best.y], s=120, marker="*", label="Selected base")

    # teleports
    if teleports:
        tx = [t[0] for t in teleports]
        ty = [t[1] for t in teleports]
        ax.scatter(tx, ty, s=25, marker="x", label="Teleports")

    # radius outline (approx)
    # Draw as circle for visualization even if diamond/square to keep it simple;
    # user sees "area_shape" label in UI anyway.
    circ = plt.Circle((best.x, best.y), R, fill=False, linestyle="--")
    ax.add_patch(circ)

    ax.set_xlim(-1, w)
    ax.set_ylim(-1, h)
    ax.set_aspect("equal", adjustable="box")
    ax.set_title(f"Map {w}x{h} | R={R} | Area={area_shape}")
    ax.legend(loc="upper right")

    if show_grid:
        ax.set_xticks(range(0, w, max(1, w // 10)))
        ax.set_yticks(range(0, h, max(1, h // 10)))
        ax.grid(True, linewidth=0.3)

    st.pyplot(fig)


# =========================
# Streamlit UI
# =========================

st.set_page_config(page_title="VS Teleport Entry Prototype", layout="wide")

st.title("VS: Прототип точки входа телепорта к базам противника")

with st.expander("Что считается (формула)", expanded=False):
    st.markdown(
        """
**Выбор центральной базы (дискретная 1-медиана среди баз):**

Для каждой базы \(i\) считаем:
\[
S_i = \sum_{j\ne i} d(i,j)
\]
и выбираем:
\[
b^* = \\arg\\min_i S_i
\]

Где \(d(i,j)\) — метрика расстояния (**Manhattan** или **Euclidean** для квадратной сетки).

**Телепортация игроков:** выбираем случайную **свободную** клетку в радиусе \(R\) вокруг \(b^*\) (учитываем занятые базами и заблокированные клетки).
"""
    )

# Sidebar controls
st.sidebar.header("Map / Simulation")

w = st.sidebar.slider("Map width", 30, 300, 120, step=10)
h = st.sidebar.slider("Map height", 30, 300, 120, step=10)

gen_mode = st.sidebar.selectbox(
    "Enemy bases placement",
    [
        "Uniform random",
        "One cluster",
        "Two clusters",
        "Line",
        "Ring",
        "Manual input",
    ],
)

n_bases = st.sidebar.slider("Number of enemy bases", 3, 300, 35)

seed = st.sidebar.number_input("Seed", min_value=0, max_value=10_000_000, value=12345, step=1)

metric = st.sidebar.selectbox("Distance metric for selecting base", ["Manhattan", "Euclidean"])

st.sidebar.header("Teleport")

R = st.sidebar.slider("Teleport radius R (cells)", 1, 80, 12)
area_shape = st.sidebar.selectbox(
    "Allowed area shape for teleport sampling",
    ["Circle (Euclid)", "Diamond (Manhattan)", "Square (Chebyshev)"],
    help="Это форма множества клеток, из которых выбирается точка телепорта в радиусе R.",
)

n_players = st.sidebar.slider("Players to teleport (simulation)", 1, 300, 60)
unique_cells = st.sidebar.checkbox("Require unique cells per player", value=True)

st.sidebar.header("Obstacles / Free cells")

blocked_density = st.sidebar.slider("Random blocked density", 0.0, 0.5, 0.06, step=0.01)
blocked_seed = st.sidebar.number_input("Blocked seed", min_value=0, max_value=10_000_000, value=777, step=1)
show_grid = st.sidebar.checkbox("Show grid", value=False)

# Generate bases
if gen_mode == "Uniform random":
    bases = gen_uniform(w, h, n_bases, seed)
elif gen_mode == "One cluster":
    spread = st.sidebar.slider("Cluster spread (sigma)", 1.0, 30.0, 7.0, step=0.5)
    bases = gen_cluster(w, h, n_bases, seed, spread=spread)
elif gen_mode == "Two clusters":
    spread = st.sidebar.slider("Cluster spread (sigma)", 1.0, 30.0, 6.0, step=0.5)
    balance = st.sidebar.slider("Cluster 1 share", 0.1, 0.9, 0.6, step=0.05)
    bases = gen_two_clusters(w, h, n_bases, seed, spread=spread, balance=balance)
elif gen_mode == "Line":
    bases = gen_line(w, h, n_bases, seed)
elif gen_mode == "Ring":
    radius = st.sidebar.slider("Ring radius", 3.0, float(min(w, h)) / 2, float(min(w, h)) / 3, step=1.0)
    bases = gen_ring(w, h, n_bases, seed, radius=radius)
else:
    st.sidebar.markdown("Manual format: one base per line: `x,y`")
    default_text = "10,10\n15,12\n18,20\n40,35\n42,38\n44,34\n70,80\n72,82\n74,78"
    manual_text = st.sidebar.text_area("Bases (x,y)", value=default_text, height=160)
    bases = parse_manual_bases(manual_text, w, h)
    if len(bases) < 3:
        st.warning("Manual input: нужно минимум 3 валидные базы в пределах карты.")
        st.stop()

# Best base and ranking
best, ranking_df = pick_best_base(bases, metric=metric)

bases_set = {(b.x, b.y) for b in bases}
blocked = gen_blocked_random(w, h, blocked_density, blocked_seed, forbidden=bases_set)

tp = teleport_players(
    best=best,
    bases_set=bases_set,
    blocked_set=blocked,
    w=w,
    h=h,
    R=R,
    area_shape=area_shape,
    n_players=n_players,
    seed=seed + 999,  # avoid coupling too much with placement seed
    unique_cells=unique_cells,
)

teleports = tp["teleports"]
fails = tp["fails"]

# Layout
left, right = st.columns([1.35, 1.0], gap="large")

with left:
    st.subheader("Map view")
    plot_map(
        w=w,
        h=h,
        bases=bases,
        best=best,
        blocked=blocked,
        teleports=teleports,
        R=R,
        area_shape=area_shape,
        show_grid=show_grid,
    )

with right:
    st.subheader("Result summary")

    st.markdown(
        f"""
- **Selected base:** `id={best.id}` at **({best.x}, {best.y})**
- **Metric:** **{metric}**
- **Teleport radius:** **R={R}**
- **Allowed teleport area:** **{area_shape}**
- **Enemy bases:** **{len(bases)}**
- **Blocked density:** **{blocked_density:.2f}**  → blocked cells: **{len(blocked)}**
"""
    )

    candidates = tp["candidate_count"]
    free_count = tp["free_count"]
    success = len(teleports)
    total = n_players
    success_rate = 0.0 if total == 0 else (success / total) * 100.0

    st.markdown(
        f"""
**Teleport simulation**
- Candidate cells in area: **{candidates}**
- Free cells in area (after bases+blocked): **{free_count}**
- Teleported successfully: **{success}/{total}** (**{success_rate:.1f}%**)
- Failed (no free cell found under constraints): **{fails}**
"""
    )

    st.subheader("Top candidate bases (lowest sum distance)")
    st.dataframe(ranking_df.head(15), use_container_width=True)

    with st.expander("Full ranking table", expanded=False):
        st.dataframe(ranking_df, use_container_width=True)

st.caption(
    "Подсказка: переключи метрику Manhattan/Euclidean и режим расстановки (особенно Two clusters) — сразу видно, как меняется выбранная база."
)
