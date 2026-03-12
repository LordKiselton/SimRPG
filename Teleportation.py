import streamlit as st
import numpy as np
import matplotlib.pyplot as plt

# -----------------------------
# Helpers
# -----------------------------
def rng_from_seed(seed: int):
    return np.random.default_rng(seed)

def euclid(a, b):
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))

def manhattan(a, b):
    return float(abs(a[0] - b[0]) + abs(a[1] - b[1]))

def get_distance_fn(metric: str):
    return euclid if metric == "Euclidean" else manhattan

def in_bounds(p, W, H):
    return 0 <= p[0] < W and 0 <= p[1] < H

def circle_points(center, r, W, H):
    # points with squared euclidean <= r^2 (good enough for "radius on grid")
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

def compute_entry_enemy_base(enemy_bases, active_mask, own_players, dist_fn):
    # Select enemy base in densest active cluster (your algorithm)
    active_pts = [p for p, a in zip(enemy_bases, active_mask) if a]
    if len(active_pts) == 0:
        return None, None, None

    N1 = len(active_pts)
    N2 = int(own_players)

    # N = min(N1, max(4, floor(sqrt(2*N2))))
    N = min(N1, max(4, int(np.floor(np.sqrt(2 * max(1, N2))))))

    scores = []
    details = []
    for j, pj in enumerate(active_pts):
        dists = []
        for i, pi in enumerate(active_pts):
            if i == j:
                continue
            dists.append(dist_fn(pj, pi))

        if len(dists) == 0:
            scores.append(0.0)
            details.append((N, [], 1.0))
            continue

        dists_sorted = np.sort(np.array(dists, dtype=float))
        n_take = min(N, len(dists_sorted))
        nearest = dists_sorted[:n_take]

        K = float(np.median(nearest)) if n_take > 0 else 1.0
        if K <= 1e-9:
            K = 1.0

        weights = np.exp(-nearest / K)
        S = float(np.sum(nearest * weights))
        scores.append(S)
        details.append((N, nearest.tolist(), K))

    idx = int(np.argmin(scores))
    return active_pts[idx], float(scores[idx]), {"N": N, "scores": scores, "details": details, "active_pts": active_pts}

def pick_teleport_cell(rng, anchor, W, H, occupied, start_radius, max_expand=400):
    """
    Pick a free cell within radius around anchor.
    If none are free, expand radius by 1 until found (or max_expand steps).
    """
    r = int(start_radius)
    for _ in range(max_expand):
        candidates = circle_points(anchor, r, W, H)
        free = [p for p in candidates if p not in occupied]
        if free:
            return free[int(rng.integers(0, len(free)))], r
        r += 1
    return None, None

def teleport_group_sequentially(rng, anchor, W, H, occupied, group_size, start_radius):
    """
    Sequentially place group_size players as points (our new bases).
    Each placement uses the same logic: free cell within radius (expand if needed).
    Occupied is updated after each placement.
    """
    placements = []
    used_radii = []
    for _ in range(int(group_size)):
        cell, used_r = pick_teleport_cell(rng, anchor, W, H, occupied, start_radius)
        if cell is None:
            break
        placements.append(cell)
        used_radii.append(used_r)
        occupied.add(cell)
    return placements, used_radii

def relocate_inactive_to_edge(rng, W, H, occupied, enemy_bases, active_mask):
    """
    Bases with destroyed wall (active_mask=False) must ALWAYS be on the map edge,
    regardless of other factors.

    Implementation goals:
    - Do not change existing generation logic
    - Do not move obstacles/neutrals (they stay in occupied)
    - Best effort guarantee even when edge is crowded:
        * place on free edge cells first
        * if insufficient, swap with ACTIVE enemy bases already on the edge
    """
    n = len(enemy_bases)
    if n == 0:
        return enemy_bases

    inactive_idx = [i for i, a in enumerate(active_mask) if not a]
    if not inactive_idx:
        return enemy_bases

    def is_edge(p):
        x, y = p
        return x == 0 or y == 0 or x == W - 1 or y == H - 1

    # Remember old inactive positions (become free for swaps)
    old_inactive_positions = [enemy_bases[i] for i in inactive_idx]

    # Free old inactive positions from occupied
    for p in old_inactive_positions:
        occupied.discard(p)

    # Build edge cell list (unique perimeter)
    edge_cells = []
    for x in range(W):
        edge_cells.append((x, 0))
        edge_cells.append((x, H - 1))
    for y in range(1, H - 1):
        edge_cells.append((0, y))
        edge_cells.append((W - 1, y))

    free_edge = [p for p in edge_cells if p not in occupied]

    # 1) Place as many inactive bases as possible on truly free edge cells
    need = len(inactive_idx)
    take = min(need, len(free_edge))
    if take > 0:
        chosen = rng.choice(len(free_edge), size=take, replace=False)
        for k in range(take):
            base_i = inactive_idx[k]
            new_p = free_edge[int(chosen[k])]
            enemy_bases[base_i] = new_p
            occupied.add(new_p)

    remaining = need - take
    if remaining <= 0:
        return enemy_bases

    # 2) If edge is crowded: swap remaining inactive with ACTIVE enemy bases on the edge.
    active_edge_indices = [i for i, a in enumerate(active_mask) if a and is_edge(enemy_bases[i])]
    if not active_edge_indices:
        # Edge fully blocked by obstacles/neutrals/other bases.
        # At this point "always on edge" is impossible without moving obstacles/neutrals.
        # We keep best-effort result.
        return enemy_bases

    # We need free non-edge targets to move swapped active bases into.
    # Prefer freed old inactive positions to preserve density.
    swap_targets = list(old_inactive_positions)

    # Ensure swap_targets are free (they should be after discard, but be safe)
    swap_targets = [p for p in swap_targets if p not in occupied]

    if len(swap_targets) < remaining:
        extra = sample_free_cells(rng, W, H, occupied, remaining - len(swap_targets))
        swap_targets += extra

    for t in range(remaining):
        idx_inactive = inactive_idx[take + t]

        # pick a random active edge base to swap with
        pick_k = int(rng.integers(0, len(active_edge_indices)))
        idx_active_edge = active_edge_indices.pop(pick_k)

        edge_pos = enemy_bases[idx_active_edge]  # this edge cell will host inactive
        target_pos = swap_targets[t] if t < len(swap_targets) else None

        if target_pos is None or target_pos in occupied:
            fallback = sample_free_cells(rng, W, H, occupied, 1)
            if not fallback:
                # nowhere to move active base
                # Still place inactive to the edge cell (keeping occupied consistent)
                enemy_bases[idx_inactive] = edge_pos
                occupied.add(edge_pos)
                continue
            target_pos = fallback[0]

        # Move active base off the edge into target_pos
        occupied.discard(edge_pos)
        enemy_bases[idx_active_edge] = target_pos
        occupied.add(target_pos)

        # Put inactive base onto the freed edge position
        enemy_bases[idx_inactive] = edge_pos
        occupied.add(edge_pos)

    return enemy_bases

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

    dist_metric = st.selectbox("Метрика расстояния (для кластеризации врага)", ["Euclidean", "Manhattan"], index=0)

    own_players = st.slider("Активные игроки своей гильдии (N2) = сколько телепортируем", 1, 200, 30, 1)
    enemy_count = st.slider("Базы противника (N1, всего)", 1, 300, 60, 1)

    enemy_layout = st.selectbox("Расстановка противника", ["Скопление", "Кластеры", "Случайно"], index=0)

    cluster_spread = st.slider("Плотность врага (меньше = плотнее)", 1, 15, 4, 1)

    k_clusters = 3
    if enemy_layout == "Кластеры":
        k_clusters = st.slider("Число кластеров", 2, 8, 3, 1)

    wall_destroyed_pct = st.slider("Доля баз со сломанной стеной (неактивны)", 0, 90, 20, 5)

    obstacles_ratio = st.slider("Препятствия (% клеток)", 0, 40, 10, 1) / 100.0
    neutrals_count = st.slider("Нейтралы (кол-во)", 0, 200, 30, 1)

    tp_radius = st.slider("Радиус телепорта от выбранной вражеской базы", 1, 20, 5, 1)

rng = rng_from_seed(int(seed))
dist_fn = get_distance_fn(dist_metric)

occupied = set()

# Place obstacles first
obstacles = place_obstacles(rng, W, H, obstacles_ratio, occupied)

# Place neutrals (occupy cells)
neutrals = place_points_random(rng, W, H, int(neutrals_count), occupied)

# Place enemy bases (occupy cells)
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
if destroy_n > 0 and enemy_count_actual > 0:
    idx = rng.choice(enemy_count_actual, size=destroy_n, replace=False)
    active_mask[idx] = False

# NEW: Force inactive (destroyed wall) bases to be on the edge
enemy_bases = relocate_inactive_to_edge(rng, W, H, occupied, enemy_bases, active_mask)

# 1) Choose enemy "entry base" (anchor)
entry_enemy_base, entry_score, debug = compute_entry_enemy_base(enemy_bases, active_mask, own_players, dist_fn)

# 2) Teleport OUR group sequentially as new "bases" (blue points)
our_teleports = []
our_used_radii = []
if entry_enemy_base is not None:
    our_teleports, our_used_radii = teleport_group_sequentially(
        rng=rng,
        anchor=entry_enemy_base,
        W=W, H=H,
        occupied=occupied,
        group_size=int(own_players),
        start_radius=int(tp_radius),
    )

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
ax.set_title("Карта (враг=красный, свои телепорты=синий, нейтралы=жёлтый, препятствия=серый)")

# faint grid
for x in range(W):
    ax.axvline(x - 0.5, linewidth=0.2, alpha=0.15)
for y in range(H):
    ax.axhline(y - 0.5, linewidth=0.2, alpha=0.15)

# Obstacles
if obstacles:
    ox, oy = zip(*obstacles)
    ax.scatter(ox, oy, s=18, marker="s", alpha=0.8)
    ax.collections[-1].set_color("gray")

# Neutrals
if neutrals:
    nx, ny = zip(*neutrals)
    ax.scatter(nx, ny, s=22, marker="o", alpha=0.9)
    ax.collections[-1].set_color("yellow")

# Enemies: inactive and active
inactive_enemy = [p for p, a in zip(enemy_bases, active_mask) if not a]
active_enemy = [p for p, a in zip(enemy_bases, active_mask) if a]

if inactive_enemy:
    ex, ey = zip(*inactive_enemy)
    ax.scatter(ex, ey, s=26, marker="x", alpha=0.8)
    ax.collections[-1].set_color("red")

if active_enemy:
    ex, ey = zip(*active_enemy)
    ax.scatter(ex, ey, s=30, marker="o", alpha=0.95)
    ax.collections[-1].set_color("red")

# Entry enemy base = red star (anchor)
if entry_enemy_base is not None:
    ax.scatter([entry_enemy_base[0]], [entry_enemy_base[1]], s=220, marker="*", linewidths=1.5)
    ax.collections[-1].set_color("red")

# Teleported OUR players as blue points
if our_teleports:
    tx, ty = zip(*our_teleports)
    ax.scatter(tx, ty, s=34, marker="o", alpha=0.95)
    ax.collections[-1].set_color("blue")
    # leader highlight (first teleport)
    ax.scatter([our_teleports[0][0]], [our_teleports[0][1]], s=140, marker="P", linewidths=1.0)
    ax.collections[-1].set_color("blue")

st.pyplot(fig, clear_figure=True)

# -----------------------------
# Readout
# -----------------------------
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("Результат")
    if entry_enemy_base is None:
        st.warning("Нет активных баз противника (все стены разрушены) — якорь/точка входа не выбраны.")
    else:
        st.write(f"**Выбранная вражеская база-якорь:** {entry_enemy_base} (помечена ⭐)")
        st.write(f"**Score (взвешенная сумма):** {entry_score:.3f}")
        st.write(f"**N (соседей в расчёте):** {debug['N']} (из {len(debug['active_pts'])} активных баз)")
        st.write(f"**Телепортировано своих игроков:** {len(our_teleports)} / {int(own_players)}")
        if our_teleports:
            st.write(f"**Лидер (первый телепорт):** {our_teleports[0]} (помечен P)")
            max_used = max(our_used_radii) if our_used_radii else None
            if max_used is not None and max_used > tp_radius:
                st.write(f"**Радиус расширялся до:** {max_used}")
        if len(our_teleports) < int(own_players):
            st.error("Не хватило свободных клеток вокруг якоря (препятствия/нейтралы/плотная занятость).")

with col2:
    st.subheader("Что считается занятым")
    st.write("- **Препятствия** и **нейтралы** занимают клетки.")
    st.write("- **Все вражеские базы** занимают клетки (активные и неактивные).")
    st.write("- **Синие точки** — это *ваши новые базы*, размещённые телепортом последовательно (лидер → остальные).")
    st.write("- Якорь (⭐) — только для выбора зоны; телепорт идёт в **свободные клетки вокруг**.")

st.caption("Если хочешь — могу добавить режим: телепортировать не всех N2, а только пачку (например, 5/10/20) без лишних параметров.")
