# app.py
# Lawforge — Streamlit прототип (исправленная версия)
# - единая отрисовка (не прыгает UI)
# - autoplay без NameError (через state + rerun)
# - явные состояния боя: RUNNING / VICTORY / DEFEAT
# - хаос (instability overflow) срабатывает строго в тик, 1 раз за пересечение порога
# - выбор законов через multiselect (макс 2) без рассинхрона UI
# - отображение >5 врагов (ряды карточек)
#
# Запуск:
#   pip install streamlit pandas
#   streamlit run app.py

import time
import random
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

import pandas as pd
import streamlit as st

st.set_page_config(layout="wide", page_title="Lawforge — визуальный прототип")


# ---------------- Models ----------------
@dataclass
class Unit:
    name: str
    hp: float
    max_hp: float
    atk: float
    speed: float = 1.0
    tags: List[str] = field(default_factory=list)

    def is_alive(self) -> bool:
        return self.hp > 0

    def hp_ratio(self) -> float:
        if self.max_hp <= 0:
            return 0.0
        return max(0.0, min(1.0, self.hp / self.max_hp))


@dataclass
class Law:
    id: str
    name: str
    desc: str
    instability_cost: float
    apply_fn: callable  # fn(sim) -> None
    can_boost: bool = True


# ---------------- Helpers (session init) ----------------
def ss(key, default):
    if key not in st.session_state:
        st.session_state[key] = default


def clamp(x, a, b):
    return max(a, min(b, x))


def log_event(tag: str, txt: str):
    st.session_state.log.append(f"[{tag}] {txt}")
    if len(st.session_state.log) > 600:
        st.session_state.log = st.session_state.log[-600:]


def compute_avg_enemy_hp(enemies: List[Unit]) -> float:
    alive = [e for e in enemies if e.is_alive()]
    if not alive:
        return 0.0
    return sum(e.hp for e in alive) / len(alive)


# ---------------- Laws ----------------
def law_double_every_third_hit(sim: Dict):
    # every 3rd hit (global counter) -> damage x2 for that hit
    # applies by setting a flag; actual doubling done in resolve_hit
    sim["events"].append(("law", "Третий удар готовит удвоение (каждые 3 попадания)"))


def law_vulnerable_if_slow(sim: Dict):
    # slow enemies take x2 damage
    for e in sim["enemies"]:
        if e.speed < 1.0:
            sim["target_mods"].setdefault(e.name, {})["damage_mul"] = (
                sim["target_mods"].get(e.name, {}).get("damage_mul", 1.0) * 2.0
            )
    sim["events"].append(("law", "Замедленные цели уязвимы (x2 входящий урон)"))


def law_crit_on_low_hp(sim: Dict):
    # targets below 50% hp take x1.5 damage; if hero below 30% hp -> enemies deal x1.2
    for e in sim["enemies"]:
        if e.hp_ratio() < 0.5:
            sim["target_mods"].setdefault(e.name, {})["damage_mul"] = (
                sim["target_mods"].get(e.name, {}).get("damage_mul", 1.0) * 1.5
            )
    if sim["hero"].hp_ratio() < 0.3:
        sim["tick_mods"]["enemy_damage_mul"] *= 1.2
    sim["events"].append(("law", "Крит по беде (ниже 50% HP: x1.5; герой <30%: враги сильнее)"))


def law_death_bloom(sim: Dict):
    sim["tick_mods"]["death_bloom"] = True
    sim["events"].append(("law", "Взрыв при смерти активен (в этом тике)"))


ALL_LAWS: Dict[str, Law] = {
    "double3": Law(
        id="double3",
        name="Третий удар удваивается",
        desc="Каждое 3-е попадание любого источника удваивает урон.",
        instability_cost=0.25,
        apply_fn=law_double_every_third_hit,
    ),
    "vuln_slow": Law(
        id="vuln_slow",
        name="Уязвимость замедленных",
        desc="Замедленные враги получают x2 входящий урон.",
        instability_cost=0.20,
        apply_fn=law_vulnerable_if_slow,
    ),
    "crit_low": Law(
        id="crit_low",
        name="Крит по беде",
        desc="Цели <50% HP получают x1.5 урон; герой <30% HP — враги бьют x1.2.",
        instability_cost=0.18,
        apply_fn=law_crit_on_low_hp,
    ),
    "death_bloom": Law(
        id="death_bloom",
        name="Взрыв при смерти",
        desc="При смерти врага — бьёт соседей (упрощённо).",
        instability_cost=0.30,
        apply_fn=law_death_bloom,
    ),
}

SYNERGIES: Dict[frozenset, Tuple[str, str, object]] = {
    frozenset(("double3", "vuln_slow")): ("СИНЕРГИЯ: каждый 3-й удар по замедленным становится ещё сильнее", "hero_damage_mul", 2.0),
    frozenset(("crit_low", "death_bloom")): ("СИНЕРГИЯ: смерть на низком HP усиливает взрыв", "death_bloom_bonus", True),
}


# ---------------- Wave / Run control ----------------
def spawn_wave(wave: int) -> List[Unit]:
    n = 4 + wave
    enemies: List[Unit] = []
    for i in range(n):
        t = random.choice(["grunt", "brute", "skirm"])
        if t == "grunt":
            hp = 20 + wave * 2
            enemies.append(Unit(f"Пехотинец#{i+1}", hp=hp, max_hp=hp, atk=4 + wave * 0.2, speed=1.0, tags=["grunt"]))
        elif t == "brute":
            hp = 60 + wave * 5
            enemies.append(Unit(f"Огр#{i+1}", hp=hp, max_hp=hp, atk=12 + wave * 0.5, speed=0.7, tags=["brute"]))
        else:
            hp = 12 + wave * 1.2
            enemies.append(Unit(f"Бегун#{i+1}", hp=hp, max_hp=hp, atk=3 + wave * 0.15, speed=1.6, tags=["skirm"]))
    return enemies


def reset_run(full: bool = True):
    st.session_state.wave = 1
    st.session_state.hero = Unit("Чернокнижник", hp=100.0, max_hp=100.0, atk=10.0, speed=1.0, tags=["hero"])
    st.session_state.enemies = spawn_wave(st.session_state.wave)
    st.session_state.log = []
    st.session_state.instability = 0.0
    st.session_state.counters = {"hit_count": 0}
    st.session_state.battle_state = "RUNNING"  # RUNNING / VICTORY / DEFEAT
    st.session_state.autoplay = False
    st.session_state.chaos_last_tick = -999
    st.session_state.tick = 0
    st.session_state.tick_history = {"tick": [], "hero_hp": [], "avg_enemy_hp": []}
    st.session_state.boost_state = {"active": False, "remaining": 0, "law": None}
    st.session_state.boost_cooldown = 0
    if full:
        st.session_state.metrics = {"runs": 0, "avg_ticks": [], "dominant_builds": {}, "boosts": 0}


def start_next_wave():
    st.session_state.wave += 1
    st.session_state.hero = Unit("Чернокнижник", hp=100.0, max_hp=100.0, atk=10.0, speed=1.0, tags=["hero"])
    st.session_state.enemies = spawn_wave(st.session_state.wave)
    st.session_state.log = []
    st.session_state.instability = 0.0
    st.session_state.counters = {"hit_count": 0}
    st.session_state.battle_state = "RUNNING"
    st.session_state.autoplay = False
    st.session_state.chaos_last_tick = -999
    st.session_state.tick = 0
    st.session_state.tick_history = {"tick": [], "hero_hp": [], "avg_enemy_hp": []}
    st.session_state.boost_state = {"active": False, "remaining": 0, "law": None}
    st.session_state.boost_cooldown = 0


# ---------------- Combat resolution ----------------
def maybe_trigger_chaos(sim: Dict):
    # Chaos should only trigger inside sim_tick, when instability >= 1.0
    # and not multiple times in the same tick.
    if st.session_state.instability < 1.0:
        return
    if st.session_state.chaos_last_tick == st.session_state.tick:
        return

    st.session_state.chaos_last_tick = st.session_state.tick

    effect = random.choice(["mass_heal_enemies", "hero_shock", "corrupt_law"])
    if effect == "mass_heal_enemies":
        for e in st.session_state.enemies:
            if e.is_alive():
                e.hp = min(e.max_hp, e.hp + 20)
        sim["events"].append(("chaos", "ХАОС: враги исцеляются (+20 HP)"))
    elif effect == "hero_shock":
        st.session_state.hero.hp -= 25
        sim["events"].append(("chaos", "ХАОС: разряд по герою (-25 HP)"))
    else:
        if st.session_state.active_laws:
            lid = random.choice(st.session_state.active_laws)
            st.session_state.active_laws.remove(lid)
            sim["events"].append(("chaos", f"ХАОС: закон «{ALL_LAWS[lid].name}» искажён и исчез"))

    # reduce instability to avoid chain chaos
    st.session_state.instability *= 0.4


def resolve_hit_damage(base: float, sim: Dict, target: Unit) -> float:
    dmg = base * sim["tick_mods"]["hero_damage_mul"]
    # per-target modifiers
    tm = sim["target_mods"].get(target.name, {})
    dmg *= tm.get("damage_mul", 1.0)

    # third hit doubling law: if hit_count % 3 == 0 -> x2
    if "double3" in st.session_state.active_laws:
        if st.session_state.counters["hit_count"] > 0 and st.session_state.counters["hit_count"] % 3 == 0:
            dmg *= 2.0
            sim["events"].append(("proc", "ПРОК: третий удар удвоен"))

    return dmg


def sim_tick():
    if st.session_state.battle_state != "RUNNING":
        return

    hero: Unit = st.session_state.hero
    enemies: List[Unit] = [e for e in st.session_state.enemies if e.is_alive()]

    # Edge: nothing to fight (should instantly be victory)
    if not enemies:
        st.session_state.battle_state = "VICTORY"
        return

    st.session_state.tick += 1

    sim = {
        "hero": hero,
        "enemies": enemies,
        "events": [],
        "tick_mods": {"hero_damage_mul": 1.0, "enemy_damage_mul": 1.0, "death_bloom": False},
        "target_mods": {},
    }

    # Instability accumulation from active laws
    for lid in st.session_state.active_laws:
        st.session_state.instability += ALL_LAWS[lid].instability_cost

    # Boost adds slight instability
    if st.session_state.boost_state["active"]:
        st.session_state.instability += 0.05

    # Apply laws
    for lid in st.session_state.active_laws:
        ALL_LAWS[lid].apply_fn(sim)
        # Boost: repeat application (simple but effective for prototype)
        if st.session_state.boost_state["active"] and st.session_state.boost_state["law"] == lid:
            ALL_LAWS[lid].apply_fn(sim)
            sim["events"].append(("boost", f"BOOST: усилен «{ALL_LAWS[lid].name}»"))

    # Synergy
    if len(st.session_state.active_laws) == 2:
        pair = frozenset(st.session_state.active_laws)
        if pair in SYNERGIES:
            desc, key, val = SYNERGIES[pair]
            sim["events"].append(("synergy", desc))
            if key == "hero_damage_mul":
                sim["tick_mods"]["hero_damage_mul"] *= float(val)
            elif key == "death_bloom_bonus":
                sim["tick_mods"]["death_bloom_bonus"] = True

    # Chaos (only inside tick)
    maybe_trigger_chaos(sim)

    # Hero action: attack lowest HP enemy
    enemies = [e for e in st.session_state.enemies if e.is_alive()]
    if enemies and hero.is_alive():
        target = min(enemies, key=lambda x: x.hp)
        st.session_state.counters["hit_count"] += 1
        dmg = resolve_hit_damage(hero.atk, sim, target)
        target.hp -= dmg
        sim["events"].append(("hero", f"Герой наносит {dmg:.1f} → {target.name} (HP {max(0, target.hp):.1f})"))

        if target.hp <= 0:
            sim["events"].append(("death", f"{target.name} погибает"))
            # death bloom
            if sim["tick_mods"].get("death_bloom", False):
                others = [e for e in st.session_state.enemies if e.is_alive() and e.name != target.name]
                if others:
                    o = random.choice(others)
                    splash = 8
                    if sim["tick_mods"].get("death_bloom_bonus", False):
                        splash = 14
                    o.hp -= splash
                    sim["events"].append(("death_bloom", f"Взрыв ранит {o.name} на {splash} (HP {max(0, o.hp):.1f})"))

    # Enemies attack hero
    if hero.is_alive():
        for e in [x for x in st.session_state.enemies if x.is_alive()]:
            dmg = e.atk * sim["tick_mods"]["enemy_damage_mul"]
            hero.hp -= dmg
            sim["events"].append(("enemy", f"{e.name} бьёт героя на {dmg:.1f} (HP героя {max(0, hero.hp):.1f})"))
            if hero.hp <= 0:
                break

    # Battle end conditions
    if hero.hp <= 0:
        st.session_state.battle_state = "DEFEAT"
        sim["events"].append(("end", "ПОРАЖЕНИЕ: герой пал"))
        st.session_state.autoplay = False
    else:
        alive_enemies = [e for e in st.session_state.enemies if e.is_alive()]
        if not alive_enemies:
            st.session_state.battle_state = "VICTORY"
            sim["events"].append(("end", "ПОБЕДА: враги уничтожены"))
            st.session_state.autoplay = False

    # Tick history
    st.session_state.tick_history["tick"].append(st.session_state.tick)
    st.session_state.tick_history["hero_hp"].append(max(0.0, hero.hp))
    st.session_state.tick_history["avg_enemy_hp"].append(compute_avg_enemy_hp(st.session_state.enemies))

    # Cooldowns
    if st.session_state.boost_state["active"]:
        st.session_state.boost_state["remaining"] -= 1
        if st.session_state.boost_state["remaining"] <= 0:
            st.session_state.boost_state = {"active": False, "remaining": 0, "law": None}
            st.session_state.boost_cooldown = 8

    if st.session_state.boost_cooldown > 0:
        st.session_state.boost_cooldown -= 1

    # Push events to log
    for tag, txt in sim["events"]:
        log_event(tag, txt)


# ---------------- Rendering ----------------
def render_arena():
    st.markdown(f"### Волна #{st.session_state.wave}  ·  Состояние: **{st.session_state.battle_state}**")

    inst = clamp(st.session_state.instability, 0.0, 1.0)
    st.progress(inst, text=f"Instability: {st.session_state.instability:.2f} / 1.00")
    if st.session_state.instability >= 1.0:
        st.warning("Нестабильность пересекла порог — в этом тике может случиться ХАОС.")

    # Active laws badges
    badges = []
    for lid in st.session_state.active_laws:
        name = ALL_LAWS[lid].name
        if st.session_state.boost_state["active"] and st.session_state.boost_state["law"] == lid:
            name = f"⚡ {name} (boost)"
        badges.append(f"`{name}`")
    st.markdown("Активные законы: " + (" ".join(badges) if badges else "_—_"))

    # Synergy readout
    if len(st.session_state.active_laws) == 2:
        pair = frozenset(st.session_state.active_laws)
        if pair in SYNERGIES:
            st.info(SYNERGIES[pair][0])

    # Hero + enemies cards (chunk enemies into rows of 5)
    hero = st.session_state.hero
    st.markdown("#### Арена")

    def unit_card(u: Unit, is_hero=False):
        title = "🧙 Герой" if is_hero else "👹 Враг"
        st.markdown(f"**{title}: {u.name}**")
        st.caption(f"ATK {u.atk:.1f} · SPD {u.speed:.2f}")
        st.progress(u.hp_ratio(), text=f"HP {max(0, u.hp):.1f}/{u.max_hp:.1f}")

    # first row: hero + up to 5 enemies
    alive_enemies = [e for e in st.session_state.enemies if e.is_alive()]
    rows = []
    while alive_enemies:
        rows.append(alive_enemies[:5])
        alive_enemies = alive_enemies[5:]

    # render hero + first row enemies
    cols = st.columns(6)
    with cols[0]:
        unit_card(hero, is_hero=True)
    first = rows[0] if rows else []
    for i in range(5):
        with cols[i + 1]:
            if i < len(first):
                unit_card(first[i], is_hero=False)
            else:
                st.write("")

    # remaining rows (enemies only)
    for r in rows[1:]:
        cols = st.columns(6)
        with cols[0]:
            st.write("")  # spacer under hero column
        for i in range(5):
            with cols[i + 1]:
                if i < len(r):
                    unit_card(r[i], is_hero=False)
                else:
                    st.write("")

    st.markdown("#### Последние события")
    for ln in st.session_state.log[-10:]:
        st.write(ln)


def render_charts_and_logs():
    st.markdown("### Диаграммы")
    if st.session_state.tick_history["tick"]:
        df = pd.DataFrame(
            {
                "tick": st.session_state.tick_history["tick"],
                "hero_hp": st.session_state.tick_history["hero_hp"],
                "avg_enemy_hp": st.session_state.tick_history["avg_enemy_hp"],
            }
        ).set_index("tick")
        st.line_chart(df)
    else:
        st.write("Пока нет данных — сделай пару тиков.")

    st.markdown("### Лог (полный)")
    st.text_area("Журнал", value="\n".join(st.session_state.log[-250:]), height=260)


# ---------------- Init state ----------------
ss("wave", 1)
ss("hero", Unit("Чернокнижник", hp=100.0, max_hp=100.0, atk=10.0, speed=1.0, tags=["hero"]))
ss("enemies", spawn_wave(1))
ss("log", [])
ss("instability", 0.0)
ss("counters", {"hit_count": 0})
ss("battle_state", "RUNNING")
ss("autoplay", False)
ss("autoplay_delay", 0.22)
ss("chaos_last_tick", -999)
ss("tick", 0)
ss("tick_history", {"tick": [], "hero_hp": [], "avg_enemy_hp": []})
ss("boost_state", {"active": False, "remaining": 0, "law": None})
ss("boost_cooldown", 0)
ss("metrics", {"runs": 0, "avg_ticks": [], "dominant_builds": {}, "boosts": 0})
ss("active_laws", [])


# ---------------- UI ----------------
st.title("Lawforge — прототип: меняем правила боя")

left, mid, right = st.columns([1.35, 1.9, 1.05])

with left:
    st.subheader("Законы")
    law_options = [(lid, f"{ALL_LAWS[lid].name} — {ALL_LAWS[lid].desc}") for lid in ALL_LAWS.keys()]
    selected = st.multiselect(
        "Выбери до 2 законов:",
        options=[x[0] for x in law_options],
        format_func=lambda lid: next(t for (i, t) in law_options if i == lid),
        default=st.session_state.active_laws,
        max_selections=2,
    )
    st.session_state.active_laws = list(selected)

    st.divider()

    st.subheader("Управление боем")
    disabled = st.session_state.battle_state != "RUNNING"

    c1, c2, c3 = st.columns(3)
    if c1.button("Step", disabled=disabled):
        sim_tick()

    if c2.button("Run", disabled=disabled):
        st.session_state.autoplay = True

    if c3.button("Stop"):
        st.session_state.autoplay = False

    st.slider("Скорость autoplay (сек/тик)", 0.05, 0.6, st.session_state.autoplay_delay, 0.01, key="autoplay_delay")

    st.divider()

    st.subheader("Boost")
    active_for_boost = [""] + st.session_state.active_laws
    boost_law = st.selectbox("Какой закон усилить (3 тика)", options=active_for_boost, index=0)
    cd = st.session_state.boost_cooldown
    if st.button("Boost", disabled=(disabled or cd > 0 or boost_law == "")):
        st.session_state.boost_state = {"active": True, "remaining": 3, "law": boost_law}
        st.session_state.metrics["boosts"] += 1
        log_event("boost", f"Включён BOOST для «{ALL_LAWS[boost_law].name}»")

    if cd > 0:
        st.caption(f"Cooldown: {cd} тиков")
    if st.session_state.boost_state["active"]:
        st.caption(f"Boost активен: {st.session_state.boost_state['remaining']} тика(ов)")

    st.divider()

    st.subheader("Раунды / волны")
    r1, r2 = st.columns(2)
    if r1.button("Next wave"):
        start_next_wave()
    if r2.button("Restart run"):
        reset_run(full=False)

    st.divider()

    st.subheader("Счётчики / метрики")
    st.write(
        {
            "tick": st.session_state.tick,
            "hit_count": st.session_state.counters["hit_count"],
            "battle_state": st.session_state.battle_state,
        }
    )
    st.write(st.session_state.metrics)

with mid:
    render_arena()

with right:
    render_charts_and_logs()

# ---------------- Autoplay engine (stable, single render target) ----------------
# This runs AFTER UI is drawn; it advances one tick per rerun.
if st.session_state.autoplay and st.session_state.battle_state == "RUNNING":
    sim_tick()
    time.sleep(st.session_state.autoplay_delay)
    st.rerun()

# ---------------- End-of-battle bookkeeping ----------------
# Record run stats once at end (only when autoplay ended or user stepped to end).
# Avoid double counting: we count when battle_state != RUNNING and a marker wasn't set.
ss("counted_end", False)
if st.session_state.battle_state != "RUNNING" and not st.session_state.counted_end:
    st.session_state.counted_end = True
    # metrics
    st.session_state.metrics["runs"] += 1
    st.session_state.metrics["avg_ticks"].append(st.session_state.tick)
    key = ",".join(sorted(st.session_state.active_laws)) if st.session_state.active_laws else "(no_laws)"
    st.session_state.metrics["dominant_builds"][key] = st.session_state.metrics["dominant_builds"].get(key, 0) + 1
elif st.session_state.battle_state == "RUNNING":
    st.session_state.counted_end = False
