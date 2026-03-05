import math
import random
from dataclasses import dataclass
from typing import List, Tuple, Set, Dict

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
    # Евклид
    return math.hypot(dx, dy)

def score_sum_distances(bases: List[Base], metric: str) -> List[float]:
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
        "S_i = Σ d(i,j)": scores,
    }).sort_values("S_i = Σ d(i,j)", ascending=True).reset_index(drop=True)
    best_id = int(df.loc[0, "id"])
    best = next(b for b in bases if b.id == best_id)
    return best, df

def cells_in_radius(cx: int, cy: int, R: int, shape: str, w: int, h: int) -> List[Tuple[int, int]]:
    """
    Возвращает список клеток в радиусе R вокруг (cx,cy).
    shape:
      - "Круг (Евклид)" => dx^2 + dy^2 <= R^2
      - "Ромб (Манхэттен)" => |dx|+|dy| <= R
      - "Квадрат (Чебышёв)" => max(|dx|,|dy|) <= R
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
            if shape == "Круг (Евклид)":
                if dx * dx + dy * dy <= r2:
                    res.append((x, y))
            elif shape == "Ромб (Манхэттен)":
                if abs(dx) + abs(dy) <= R:
                    res.append((x, y))
            else:  # "Квадрат (Чебышёв)"
                if max(abs(dx), abs(dy)) <= R:
                    res.append((x, y))
    return res

def teleport_players(
    best: Base,
    occupied_set: Set[Tuple[int, int]],
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
    forbidden = set(occupied_set) | set(blocked_set)

    free = [c for c in candidates if c not in forbidden]
    rng.shuffle(free)

    teleports = []
    used = set()
    fails = 0

    if unique_cells:
        for _ in range(n_players):
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
        for _ in range(n_players):
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

def gen_uniform(w: int, h: int, n: int, seed: int, used_global: Set[Tuple[int, int]] = None) -> List[Base]:
    rng = random.Random(seed)
    used = set() if used_global is None else used_global
    bases = []
    tries = 0
    while len(bases) < n and tries < n * 1000:
        tries += 1
        x = rng.randrange(w)
        y = rng.randrange(h)
        if (x, y) in used:
            continue
        used.add((x, y))
        bases.append(Base(id=len(bases), x=x, y=y))
    return bases

def gen_cluster(w: int, h: int, n: int, seed: int, spread: float = 6.0, used_global: Set[Tuple[int, int]] = None) -> List[Base]:
    rng = random.Random(seed)
    cx = rng.randrange(w)
    cy = rng.randrange(h)
    used = set() if used_global is None else used_global
    bases = []
    tries = 0
    while len(bases) < n and tries < n * 3000:
        tries += 1
        x = int(round(rng.gauss(cx, spread)))
        y = int(round(rng.gauss(cy, spread)))
        if not (0 <= x < w and 0 <= y < h):
            continue
        if (x, y) in used:
            continue
        used.add((x, y))
        bases.append(Base(id=len(bases), x=x, y=y))
    return bases

def gen_two_clusters(w: int, h: int, n: int, seed: int, spread: float = 5.0, balance: float = 0.6, used_global: Set[Tuple[int, int]] = None) -> List[Base]:
    rng = random.Random(seed)
    n1 = max(1, int(round(n * balance)))
    n2 = n - n1
    c1 = (rng.randrange(w), rng.randrange(h))
    c2 = (rng.randrange(w), rng.randrange(h))
    used = set() if used_global is None else used_global
    bases = []

    def sample(center, count):
        nonlocal bases, used
        cx, cy = center
        tries = 0
        while count > 0 and tries < 500000:
            tries += 1
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
    # добиваем, если не хватило
    while len(bases) < n:
        x = rng.randrange(w); y = rng.randrange(h)
        if (x, y) in used:
            continue
        used.add((x, y))
        bases.append(Base(id=len(bases), x=x, y=y))
    return bases

def gen_line(w: int, h: int, n: int, seed: int, used_global: Set[Tuple[int, int]] = None) -> List[Base]:
    rng = random.Random(seed)
    used = set() if used_global is None else used_global

    x0, y0 = rng.randrange(w), rng.randrange(h)
    x1, y1 = rng.randrange(w), rng.randrange(h)

    bases = []
    for i in range(n):
        t = 0 if n == 1 else i / (n - 1)
        x = int(round(x0 + (x1 - x0) * t))
        y = int(round(y0 + (y1 - y0) * t))
        x = max(0, min(w - 1, x))
        y = max(0, min(h - 1, y))

        if (x, y) in used:
            for _ in range(25):
                nx = max(0, min(w - 1, x + rng.choice([-1, 0, 1])))
                ny = max(0, min(h - 1, y + rng.choice([-1, 0, 1])))
                if (nx, ny) not in used:
                    x, y = nx, ny
                    break

        if (x, y) in used:
            continue
        used.add((x, y))
        bases.append(Base(id=len(bases), x=x, y=y))

    while len(bases) < n:
        x = rng.randrange(w); y = rng.randrange(h)
        if (x, y) in used:
            continue
        used.add((x, y))
        bases.append(Base(id=len(bases), x=x, y=y))
    return bases

def gen_ring(w: int, h: int, n: int, seed: int, radius: float = 20.0, used_global: Set[Tuple[int, int]] = None) -> List[Base]:
    rng = random.Random(seed)
    used = set() if used_global is None else used_global

    cx = w // 2
    cy = h // 2

    bases = []
    for i in range(n):
        ang = 2 * math.pi * (i / n)
        rr = max(1.0, rng.gauss(radius, radius * 0.08))
        x = int(round(cx + rr * math.cos(ang)))
        y = int(round(cy + rr * math.sin(ang)))
        x = max(0, min(w - 1, x))
        y = max(0, min(h - 1, y))
        if (x, y) in used:
            continue
        used.add((x, y))
        bases.append(Base(id=len(bases), x=x, y=y))

    while len(bases) < n:
        x = rng.randrange(w); y = rng.randrange(h)
        if (x, y) in used:
            continue
        used.add((x, y))
        bases.append(Base(id=len(bases), x=x, y=y))
    return bases

def parse_manual_bases(text: str, w: int, h: int, used_global: Set[Tuple[int, int]] = None) -> List[Base]:
    used = set() if used_global is None else used_global
    bases = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        parts = [p.strip() for p in (ln.split(",") if "," in ln else ln.split())]
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
    while len(blocked) < k and tries < k * 30 + 2000:
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
    enemy_bases: List[Base],
    neutral_bases: List[Base],
    best_enemy: Base,
    blocked: Set[Tuple[int,int]],
    teleports: List[Tuple[int,int]],
    R: int,
    show_grid: bool,
):
    fig, ax = plt.subplots(figsize=(7.2, 7.2))

    # obstacles (gray)
    if blocked:
        bx = [c[0] for c in blocked]
        by = [c[1] for c in blocked]
        ax.scatter(bx, by, s=10, marker="s", color="gray", label="Обстаклы")

    # neutrals (yellow)
    if neutral_bases:
        nx = [b.x for b in neutral_bases]
        ny = [b.y for b in neutral_bases]
        ax.scatter(nx, ny, s=35, marker="o", color="gold", label="Базы нейтралов")

    # enemy bases (red)
    ex = [b.x for b in enemy_bases]
    ey = [b.y for b in enemy_bases]
    ax.scatter(ex, ey, s=35, marker="o", color="red", label="Базы врага")

    # best enemy (red star)
    ax.scatter([best_enemy.x], [best_enemy.y], s=180, marker="*", color="red", label="Выбранная база")

    # teleports (green)
    if teleports:
        tx = [t[0] for t in teleports]
        ty = [t[1] for t in teleports]
        ax.scatter(tx, ty, s=28, marker="x", color="green", label="Телепорты")

    # radius outline (neutral dashed)
    circ = plt.Circle((best_enemy.x, best_enemy.y), R, fill=False, linestyle="--")
    ax.add_patch(circ)

    ax.set_xlim(-1, w)
    ax.set_ylim(-1, h)
    ax.set_aspect("equal", adjustable="box")
    ax.set_title(f"Карта {w}x{h} | R={R}")
    ax.legend(loc="upper right")

    if show_grid:
        ax.set_xticks(range(0, w + 1, max(1, w // 10)))
        ax.set_yticks(range(0, h + 1, max(1, h // 10)))
        ax.grid(True, linewidth=0.3)

    st.pyplot(fig)


# =========================
# Streamlit UI
# =========================

st.set_page_config(page_title="VS: Точка входа телепорта (прототип)", layout="wide")
st.title("VS: Прототип точки входа телепорта к базам противника")

with st.expander("Формула выбора базы (как в дизайне)", expanded=False):
    st.markdown(
        r"""
**Выбор центральной базы врага (дискретная 1-медиана среди баз врага):**

Для каждой базы \(i\) считаем:
\[
S_i = \sum_{j\ne i} d(i,j)
\]
и выбираем:
\[
b^* = \arg\min_i S_i
\]

Для квадратной клеточной сетки по умолчанию логично тестировать **Манхэттен**:
\[
d(i,j)=|x_i-x_j|+|y_i-y_j|
\]
(в прототипе можно переключиться на Евклид).

**Телепортация:** выбираем свободные клетки в радиусе \(R\) вокруг \(b^*\), учитывая занятые клетки (базы врага/нейтралов) и обстаклы.
"""
    )

st.sidebar.header("Карта / Симуляция")
w = st.sidebar.slider("Ширина карты", 30, 300, 120, step=10)
h = st.sidebar.slider("Высота карты", 30, 300, 120, step=10)

seed = st.sidebar.number_input("Seed (общий)", min_value=0, max_value=10_000_000, value=12345, step=1)

st.sidebar.header("Базы врага")
enemy_mode = st.sidebar.selectbox(
    "Способ расстановки баз врага",
    ["Равномерно (случайно)", "Один кластер", "Два кластера", "Линия", "Кольцо", "Ручной ввод"],
)
n_enemy = st.sidebar.slider("Кол-во баз врага", 3, 300, 35)

metric = st.sidebar.selectbox("Метрика для выбора базы", ["Манхэттен", "Евклид"])

# Global used set to avoid overlaps between enemy and neutral (optional but usually desired)
used_global: Set[Tuple[int, int]] = set()

def gen_bases(mode: str, n: int, seed_local: int, used: Set[Tuple[int,int]]) -> List[Base]:
    if mode == "Равномерно (случайно)":
        return gen_uniform(w, h, n, seed_local, used_global=used)
    if mode == "Один кластер":
        spread = st.sidebar.slider("Разброс кластера (σ)", 1.0, 30.0, 7.0, step=0.5, key=f"spread_{mode}_{n}_{seed_local}")
        return gen_cluster(w, h, n, seed_local, spread=spread, used_global=used)
    if mode == "Два кластера":
        spread = st.sidebar.slider("Разброс кластеров (σ)", 1.0, 30.0, 6.0, step=0.5, key=f"spread2_{mode}_{n}_{seed_local}")
        balance = st.sidebar.slider("Доля кластера 1", 0.1, 0.9, 0.6, step=0.05, key=f"bal_{mode}_{n}_{seed_local}")
        return gen_two_clusters(w, h, n, seed_local, spread=spread, balance=balance, used_global=used)
    if mode == "Линия":
        return gen_line(w, h, n, seed_local, used_global=used)
    if mode == "Кольцо":
        radius = st.sidebar.slider("Радиус кольца", 3.0, float(min(w, h)) / 2, float(min(w, h)) / 3, step=1.0, key=f"rad_{mode}_{n}_{seed_local}")
        return gen_ring(w, h, n, seed_local, radius=radius, used_global=used)
    # Manual
    st.sidebar.markdown("Формат: одна база на строку: `x,y` (или `x y`)")
    default_text = "10,10\n15,12\n18,20\n40,35\n42,38\n44,34\n70,80\n72,82\n74,78"
    manual_text = st.sidebar.text_area("Координаты баз врага", value=default_text, height=160, key="enemy_manual")
    bases = parse_manual_bases(manual_text, w, h, used_global=used)
    return bases

enemy_bases = gen_bases(enemy_mode, n_enemy, seed_local=seed, used=used_global)
if len(enemy_bases) < 3:
    st.warning("Нужно минимум 3 валидные базы врага в пределах карты.")
    st.stop()

# Neutral bases
st.sidebar.header("Базы нейтралов")
enable_neutrals = st.sidebar.checkbox("Генерировать базы нейтралов", value=True)
neutral_bases: List[Base] = []
if enable_neutrals:
    neutral_mode = st.sidebar.selectbox(
        "Способ расстановки баз нейтралов",
        ["Равномерно (случайно)", "Один кластер", "Два кластера", "Линия", "Кольцо", "Ручной ввод"],
        key="neutral_mode",
    )
    n_neutral = st.sidebar.slider("Кол-во баз нейтралов", 0, 300, 25)
    neutral_seed = st.sidebar.number_input("Seed (нейтралы)", min_value=0, max_value=10_000_000, value=int(seed) + 111, step=1)

    if n_neutral > 0:
        # ВАЖНО: нейтралы не должны пересекаться с врагом => используем used_global
        if neutral_mode != "Ручной ввод":
            neutral_bases = gen_bases(neutral_mode, n_neutral, seed_local=int(neutral_seed), used=used_global)
        else:
            st.sidebar.markdown("Формат: одна база на строку: `x,y` (или `x y`)")
            neutral_default = "20,20\n22,21\n90,30\n95,32\n60,100"
            neutral_text = st.sidebar.text_area("Координаты баз нейтралов", value=neutral_default, height=140, key="neutral_manual")
            neutral_bases = parse_manual_bases(neutral_text, w, h, used_global=used_global)

# Reassign IDs for clarity in view (optional)
enemy_bases = [Base(id=i, x=b.x, y=b.y) for i, b in enumerate(enemy_bases)]
neutral_bases = [Base(id=i, x=b.x, y=b.y) for i, b in enumerate(neutral_bases)] if neutral_bases else []

# Best base among enemy
best_enemy, ranking_df = pick_best_base(enemy_bases, metric=metric)

st.sidebar.header("Телепорт")
R = st.sidebar.slider("Радиус телепорта R (клеток)", 1, 80, 12)
area_shape = st.sidebar.selectbox(
    "Форма зоны выбора точки телепорта",
    ["Круг (Евклид)", "Ромб (Манхэттен)", "Квадрат (Чебышёв)"],
    help="Это множество клеток, из которых выбирается точка телепорта в радиусе R.",
)
n_players = st.sidebar.slider("Сколько игроков телепортировать", 1, 300, 60)
unique_cells = st.sidebar.checkbox("Требовать уникальную клетку на игрока", value=True)

st.sidebar.header("Обстаклы / свободные клетки")
blocked_density = st.sidebar.slider("Плотность случайных обстаклов", 0.0, 0.5, 0.06, step=0.01)
blocked_seed = st.sidebar.number_input("Seed (обстаклы)", min_value=0, max_value=10_000_000, value=777, step=1)
show_grid = st.sidebar.checkbox("Показать сетку", value=False)

enemy_set = {(b.x, b.y) for b in enemy_bases}
neutral_set = {(b.x, b.y) for b in neutral_bases} if neutral_bases else set()
occupied_set = enemy_set | neutral_set

blocked = gen_blocked_random(w, h, blocked_density, int(blocked_seed), forbidden=occupied_set)

tp = teleport_players(
    best=best_enemy,
    occupied_set=occupied_set,
    blocked_set=blocked,
    w=w,
    h=h,
    R=R,
    area_shape=area_shape,
    n_players=n_players,
    seed=int(seed) + 999,
    unique_cells=unique_cells,
)

teleports = tp["teleports"]
fails = tp["fails"]

# Layout
left, right = st.columns([1.35, 1.0], gap="large")

with left:
    st.subheader("Визуализация карты")
    plot_map(
        w=w,
        h=h,
        enemy_bases=enemy_bases,
        neutral_bases=neutral_bases,
        best_enemy=best_enemy,
        blocked=blocked,
        teleports=teleports,
        R=R,
        show_grid=show_grid,
    )

with right:
    st.subheader("Сводка результата")

    candidates = tp["candidate_count"]
    free_count = tp["free_count"]
    success = len(teleports)
    total = n_players
    success_rate = 0.0 if total == 0 else (success / total) * 100.0

    st.markdown(
        f"""
- **Выбранная база врага:** `id={best_enemy.id}` в **({best_enemy.x}, {best_enemy.y})**
- **Метрика выбора:** **{metric}**
- **Радиус телепорта:** **R={R}**
- **Форма зоны:** **{area_shape}**
- **Баз врага:** **{len(enemy_bases)}**
- **Баз нейтралов:** **{len(neutral_bases)}**
- **Плотность обстаклов:** **{blocked_density:.2f}** → **{len(blocked)}** клеток
"""
    )

    st.markdown(
        f"""
**Симуляция телепорта**
- Клеток-кандидатов в зоне: **{candidates}**
- Свободных клеток после фильтра (базы+обстаклы): **{free_count}**
- Успешно телепортировано: **{success}/{total}** (**{success_rate:.1f}%**)
- Не удалось (нет свободных клеток под ограничениями): **{fails}**
"""
    )

    st.subheader("Топ кандидатов (минимум суммы дистанций)")
    st.dataframe(ranking_df.head(15), use_container_width=True)

    with st.expander("Полный рейтинг", expanded=False):
        st.dataframe(ranking_df, use_container_width=True)

st.caption("Подсказка: попробуйте режим 'Два кластера' и переключение метрики — хорошо видно, как меняется выбранная центральная база.")
