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
    return math.hypot(dx, dy)

def score_sum_distances(bases: List[Base], metric: str) -> List[float]:
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

def pick_best_base(bases: List[Base], metric: str) -> Tuple[Base, pd.DataFrame]:
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
mode = st.sidebar.selectbox("Тип генерации", ["Равномерно", "Кластер"])
metric = st.sidebar.selectbox("Метрика", ["Манхэттен", "Евклид"])

used_global = set()

if mode == "Равномерно":
    enemy_bases = gen_uniform(w, h, n_enemy, seed, used_global)
else:
    spread = st.sidebar.slider("Разброс кластера", 1.0, 20.0, 6.0)
    enemy_bases = gen_cluster(w, h, n_enemy, seed, spread, used_global)

st.sidebar.header("Базы нейтралов")
enable_neutral = st.sidebar.checkbox("Добавить нейтралов", True)
neutral_bases = []
if enable_neutral:
    n_neutral = st.sidebar.slider("Количество нейтралов", 0, 200, 20)
    neutral_bases = gen_uniform(w, h, n_neutral, seed + 999, used_global)

enemy_set = {(b.x, b.y) for b in enemy_bases}
neutral_set = {(b.x, b.y) for b in neutral_bases}
occupied = enemy_set | neutral_set

st.sidebar.header("Обстаклы")
density = st.sidebar.slider("Плотность", 0.0, 0.4, 0.05)
blocked = set()
rng = random.Random(seed + 555)
for _ in range(int(w * h * density)):
    x = rng.randrange(w)
    y = rng.randrange(h)
    if (x, y) not in occupied:
        blocked.add((x, y))

best_enemy, ranking = pick_best_base(enemy_bases, metric)

st.sidebar.header("Телепорт")
R = st.sidebar.slider("Радиус", 1, 50, 10)
shape = st.sidebar.selectbox("Форма зоны", ["Круг", "Ромб", "Квадрат"])
players = st.sidebar.slider("Игроков", 1, 200, 50)

tp = teleport_players(best_enemy, occupied, blocked, w, h, R, shape, players, seed + 777, True)

left, right = st.columns([1.4, 1])

with left:
    fig, ax = plt.subplots(figsize=(7,7))

    if blocked:
        bx = [c[0] for c in blocked]
        by = [c[1] for c in blocked]
        ax.scatter(bx, by, s=10, color="gray", marker="s", label="Обстаклы")

    if neutral_bases:
        nx = [b.x for b in neutral_bases]
        ny = [b.y for b in neutral_bases]
        ax.scatter(nx, ny, s=35, color="gold", label="Нейтралы")

    ex = [b.x for b in enemy_bases]
    ey = [b.y for b in enemy_bases]
    ax.scatter(ex, ey, s=35, color="red", label="Враг")

    ax.scatter([best_enemy.x], [best_enemy.y], s=180, marker="*", color="red", label="Выбранная база")

    if tp["teleports"]:
        tx = [t[0] for t in tp["teleports"]]
        ty = [t[1] for t in tp["teleports"]]
        ax.scatter(tx, ty, s=30, marker="x", color="green", label="Телепорт")

    circ = plt.Circle((best_enemy.x, best_enemy.y), R, fill=False, linestyle="--")
    ax.add_patch(circ)

    ax.set_xlim(-1, w)
    ax.set_ylim(-1, h)
    ax.set_aspect("equal")
    ax.legend()
    st.pyplot(fig)

with right:
    st.subheader("Результат")
    st.write(f"Выбранная база: id={best_enemy.id} ({best_enemy.x},{best_enemy.y})")
    st.write(f"Успешных телепортов: {len(tp['teleports'])}/{players}")
    st.write(f"Не удалось разместить: {tp['fails']}")

    st.subheader("Топ баз по центральности")
    st.dataframe(ranking.head(10), use_container_width=True)
