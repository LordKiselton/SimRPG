import streamlit as st
import numpy as np
import matplotlib.pyplot as plt

# -----------------------------
# Helpers
# -----------------------------
def rng_from_seed(seed: int):
    return np.random.default_rng(seed)

def clamp_int(x, lo, hi):
    return int(max(lo, min(hi, x)))

def euclid(a, b):
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))

def manhattan(a, b):
    return float(abs(a[0] - b[0]) + abs(a[1] - b[1]))

def get_distance_fn(metric: str):
    return euclid if metric == "Euclidean" else manhattan

def in_bounds(p, W, H):
    return 0 <= p[0] < W and 0 <= p[1] < H

def circle_points(center, r, W, H):
    # All points with distance <= r in grid (cheaper than perfect circle: use squared euclid)
    cx, cy = center
    pts = []
    r2 = r * r
    x0 = max(0, cx - r)
    x1 = min(W - 1, cx + r)
    y0 = max(0, cy - r)
    y1 = min(H - 1, cy + r)
    for x in range(x0, x1 + 1):
        dx = x - cx
        for y in range(y0, y1 + 1):
            dy = y - cy
            if dx * dx + dy * dy <= r2:
                pts.append((x, y))
    return pts

def sample_free_cells(rng, W, H, occupied_set, n):
    free = [(x, y) for x in range(W) for y in range(H) if (x, y) not in occupied_set]
    if n > len(free):
        n = len(free)
    if n <= 0:
        return []
    idx = rng.choice(len(free), size=n, replace=False)
    return [free[i] for i in idx]

def place_obstacles(rng, W, H, obstacle_ratio, occupied):
    n_obs = int(W * H * obstacle_ratio)
    obs = sample_free_cells(rng, W, H, occupied, n_obs)
    for p in obs:
        occupied.add(p)
    return obs

def place_points_random(rng, W, H, count, occupied):
    pts = sample_free_cells(rng, W, H, occupied, count)
    for p in pts:
        occupied.add(p)
    return pts

def place_points_cluster(rng, W, H, count, occupied, spread):
    # one cluster around random center
    center = (int(rng.integers(0, W)), int(rng.integers(0, H)))
    pts = []
    tries = 0
    while len(pts) < count and tries < count * 200:
        tries += 1
        x = int(np.round(rng.normal(center[0], spread)))
        y = int(np.round(rng.normal(center[1], spread)))
        p = (x, y)
        if in_bounds(p, W, H) and p not in occupied:
            pts.append(p)
            occupied.add(p)
    # fallback random if not enough
    if len(pts) < count:
        pts += place_points_random(rng, W, H, count - len(pts), occupied)
    return pts

def place_points_kclusters(rng, W, H, count, occupied, k, spread):
    k = max(1, k)
    centers = [(int(rng.integers(0, W)), int(rng.integers(0, H))) for _ in range(k)]
    pts = []
    tries = 0
    while len(pts) < count and tries < count * 300:
        tries += 1
        c = centers[int(rng.integers(0, k))]
        x = int(np.round(rng.normal(c[0], spread)))
        y = int(np.round(rng.normal(c[1], spread)))
        p = (x, y)
        if in_bounds(p, W, H) and p not in occupied:
            pts.append(p)
            occupied.add(p)
    if len(pts) < count:
        pts += place_points_random(rng, W, H, count - len(pts), occupied)
    return pts

def compute_entry_base(enemy_bases, active_mask, own_players, dist_fn):
    # enemy_bases: list[(x,y)]
    # active_mask: bool array same length
    active_pts = [p for p, a in zip(enemy_bases, active_mask) if a]
    if len(active_pts) == 0:
        return None, None, None

    N1 = len(active_pts)
    N2 = int(own_players)

    # N = min(N1, max(4, floor(sqrt(2*N2))))
    N = min(N1, max(4, int(np.floor(np.sqrt(2 * max(1, N2))))))

    # For each base compute weighted sum of distances to N nearest (including itself? — исключим себя)
    scores = []
    details = []
    for j, pj in enumerate(active_pts):
        dists = []
        for i, pi in enumerate(active_pts):
            if i == j:
                continue
            dists.append(dist_fn(pj, pi))
        if len(dists) == 0:
            # only one active base
            scores.append(0.0)
            details.append((N, [], 1.0))
            continue

        dists_sorted = np.sort(np.array(dists, dtype=float))
        n_take = min(N, len(dists_sorted))
        nearest = dists_sorted[:n_take]

        # K = median(d1..dN)
        K = float(np.median(nearest)) if n_take > 0 else 1.0
        if K <= 1e-9:
            K = 1.0  # protect from divide by zero in ultra-dense / duplicates

        weights = np.exp(-nearest / K)
        S = float(np.sum(nearest * weights))
        scores.append(S)
        details.append((N, nearest.tolist(), K))

    idx = int(np.argmin(scores))
    return active_pts[idx], float(scores[idx]), {"N": N, "scores": scores, "details": details, "active_pts": active_pts}

def pick_teleport_cell(rng, entry_base, W, H, occupied, start_radius, max_extra=200):
    r = start_radius
    # find any free cell within radius; if none expand radius by 1
    for _ in range(max_extra):
        candidates = circle_points(entry_base, r, W, H)
        free = [p for p in candidates if p not in occupied]
        if free:
            return free[int(rng.integers(0, len(free)))], r
        r += 1
    return None, None

# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="Teleport Entry Selector Simulator", layout="wide")
st.title("Симуляция выбора точки входа при телепорте (PvP)")

with st.sidebar:
    st.header("Параметры (минимум)")
    seed = st.number_input("Seed", min_value=0, value=42, step=1)
    W = st.slider("Ширина карты", 20, 120, 60, 5)
    H = st.slider("Высота карты", 20, 120, 60, 5)

    dist_metric = st.selectbox("Метрика расстояния", ["Euclidean", "Manhattan"], index=0)

    own_players = st.slider("Активные игроки своей гильдии (N2)", 1, 200, 30, 1)
    enemy_count = st.slider("Базы противника (N1, всего)", 1, 300, 60, 1)

    enemy_layout = st.selectbox("Расстановка противника", ["Скопление", "Кластеры", "Случайно"], index=0)

    # keep minimal, but need a single knob for how tight clusters are
    cluster_spread = st.slider("Плотность (меньше = плотнее)", 1, 15, 4, 1)

    k_clusters = 3
    if enemy_layout == "Кластеры":
        k_clusters = st.slider("Число кластеров", 2, 8, 3, 1)

    wall_destroyed_pct = st.slider("Доля баз со сломанной стеной (неактивны)", 0, 90, 20, 5)

    obstacles_ratio = st.slider("Препятствия (% клеток)", 0, 40, 10, 1) / 100.0
    neutrals_count = st.slider("Нейтралы (кол-во)", 0, 200, 30, 1)
    our_bases_count = st.slider("Свои базы (кол-во для контекста)", 0, 200, 25, 1)

    tp_radius = st.slider("Радиус телепорта от точки входа", 1, 20, 5, 1)

rng = rng_from_seed(int(seed))
dist_fn = get_distance_fn(dist_metric)

occupied = set()

# Place obstacles first
obstacles = place_obstacles(rng, W, H, obstacles_ratio, occupied)

# Place neutrals
neutrals = place_points_random(rng, W, H, int(neutrals_count), occupied)

# Place our bases (just for visualization / occupation)
our_bases = place_points_random(rng, W, H, int(our_bases_count), occupied)

# Place enemy bases depending on scenario
if enemy_layout == "Случайно":
    enemy_bases = place_points_random(rng, W, H, int(enemy_count), occupied)
elif enemy_layout == "Скопление":
    enemy_bases = place_points_cluster(rng, W, H, int(enemy_count), occupied, spread=float(cluster_spread))
else:
    enemy_bases = place_points_kclusters(rng, W, H, int(enemy_count), occupied, k=int(k_clusters), spread=float(cluster_spread))

# Active bases by wall status
enemy_count_actual = len(enemy_bases)
destroy_n = int(np.floor(enemy_count_actual * wall_destroyed_pct / 100.0))
active_mask = np.ones(enemy_count_actual, dtype=bool)
if destroy_n > 0:
    idx = rng.choice(enemy_count_actual, size=destroy_n, replace=False)
    active_mask[idx] = False

entry_base, entry_score, debug = compute_entry_base(enemy_bases, active_mask, own_players, dist_fn)

# Teleport cell: must not be on occupied. But note: entry_base itself is occupied by enemy base;
# teleport happens near it, so keep occupied set as-is.
tp_cell, tp_used_radius = (None, None)
if entry_base is not None:
    tp_cell, tp_used_radius = pick_teleport_cell(rng, entry_base, W, H, occupied, int(tp_radius))

# -----------------------------
# Plot
# -----------------------------
fig = plt.figure(figsize=(10, 10))
ax = plt.gca()
ax.set_xlim(-0.5, W - 0.5)
ax.set_ylim(-0.5, H - 0.5)
ax.set_aspect("equal", adjustable="box")
ax.set_xticks([])
ax.set_yticks([])
ax.set_title("Карта (цвета: враг красный, свой синий, нейтрал жёлтый, препятствие серый)")

# grid faint
for x in range(W):
    ax.axvline(x - 0.5, linewidth=0.2, alpha=0.15)
for y in range(H):
    ax.axhline(y - 0.5, linewidth=0.2, alpha=0.15)

if obstacles:
    ox, oy = zip(*obstacles)
    ax.scatter(ox, oy, s=18, marker="s", alpha=0.8)  # default color
    # make obstacles gray explicitly
    ax.collections[-1].set_color("gray")

if neutrals:
    nx, ny = zip(*neutrals)
    ax.scatter(nx, ny, s=22, marker="o", alpha=0.9)
    ax.collections[-1].set_color("yellow")

if our_bases:
    bx, by = zip(*our_bases)
    ax.scatter(bx, by, s=26, marker="o", alpha=0.9)
    ax.collections[-1].set_color("blue")

# enemies: active and inactive
active_enemy = [p for p, a in zip(enemy_bases, active_mask) if a]
inactive_enemy = [p for p, a in zip(enemy_bases, active_mask) if not a]

if inactive_enemy:
    ex, ey = zip(*inactive_enemy)
    ax.scatter(ex, ey, s=26, marker="x", alpha=0.8)
    ax.collections[-1].set_color("red")

if active_enemy:
    ex, ey = zip(*active_enemy)
    ax.scatter(ex, ey, s=30, marker="o", alpha=0.95)
    ax.collections[-1].set_color("red")

# entry base = red star
if entry_base is not None:
    ax.scatter([entry_base[0]], [entry_base[1]], s=220, marker="*", linewidths=1.5)
    ax.collections[-1].set_color("red")

    # show teleport radius ring (approx)
    ring = circle_points(entry_base, int(tp_radius), W, H)
    if ring:
        rx, ry = zip(*ring)
        ax.scatter(rx, ry, s=6, alpha=0.08)  # subtle hint
        ax.collections[-1].set_color("red")

# teleport chosen cell (optional mark): keep minimal; mark as blue plus for clarity
if tp_cell is not None:
    ax.scatter([tp_cell[0]], [tp_cell[1]], s=120, marker="P", linewidths=1.0)
    ax.collections[-1].set_color("blue")

st.pyplot(fig, clear_figure=True)

# -----------------------------
# Readout
# -----------------------------
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("Результат")
    if entry_base is None:
        st.warning("Нет активных баз противника (все стены разрушены) — точка входа не выбрана.")
    else:
        st.write(f"**Выбранная база (точка входа):** {entry_base}")
        st.write(f"**Score (взвешенная сумма):** {entry_score:.3f}")
        st.write(f"**N (соседей в расчёте):** {debug['N']} (из {len(debug['active_pts'])} активных баз)")
        if tp_cell is None:
            st.error("Не удалось найти свободную клетку для телепорта (слишком плотная занятость/препятствия).")
        else:
            if tp_used_radius == tp_radius:
                st.write(f"**Клетка телепорта:** {tp_cell} (в радиусе {tp_radius})")
            else:
                st.write(f"**Клетка телепорта:** {tp_cell} (радиус расширен до {tp_used_radius})")

with col2:
    st.subheader("Быстрая проверка логики")
    st.write("- Враги **активны**, если стена не разрушена (неактивные отмечены красным крестиком).")
    st.write("- Точка входа — активная база с **минимальным взвешенным суммарным расстоянием** до N ближайших.")
    st.write("- Вес: **w(d)=exp(-d/K)**, где **K=median(d1..dN)**.")
    st.write("- Телепорт ищет **свободную** клетку в радиусе; если занято — **расширяет радиус**.")

st.caption("Примечание: метку телепорта (синий 'P') можно убрать, если хочешь строго только звездочку на базе.")
