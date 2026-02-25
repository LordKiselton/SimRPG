# app.py
# Lawforge — Streamlit прототип (баланс + UI)
# - Boost удалён: игрок управляет ТОЛЬКО законами
# - Скорость реально работает: атаки/тик зависят от speed
# - 12 законов + синергии
# - UI: слева карточки законов, центр — последние события, справа — вертикально герой/враги
# - Графики и полный лог — под катом внизу
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

st.set_page_config(layout="wide", page_title="Lawforge — прототип (законы)")


# ---------------- Models ----------------
@dataclass
class Unit:
    name: str
    hp: float
    max_hp: float
    atk: float
    speed: float = 1.0  # affects attacks per tick
    tags: List[str] = field(default_factory=list)
    statuses: Dict[str, int] = field(default_factory=dict)  # e.g., {"bleed":2}

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


# ---------------- Utils ----------------
def ss(key, default):
    if key not in st.session_state:
        st.session_state[key] = default


def clamp(x, a, b):
    return max(a, min(b, x))


def short(msg: str):
    st.session_state.recent.append(msg)
    if len(st.session_state.recent) > 10:
        st.session_state.recent = st.session_state.recent[-10:]


def log_full(tag: str, msg: str):
    st.session_state.log.append(f"[{tag}] {msg}")
    if len(st.session_state.log) > 800:
        st.session_state.log = st.session_state.log[-800:]


def compute_avg_enemy_hp(enemies: List[Unit]) -> float:
    alive = [e for e in enemies if e.is_alive()]
    if not alive:
        return 0.0
    return sum(e.hp for e in alive) / len(alive)


def attacks_per_tick(speed: float) -> int:
    """
    Converts speed into number of attacks in a tick.
    - 0.7 => usually 1, sometimes 0 (handled via probabilistic extra below)
    - 1.0 => 1
    - 1.6 => 1 + sometimes 1 extra
    """
    base = int(speed)  # floor
    frac = speed - base
    extra = 1 if random.random() < frac else 0
    return max(0, base + extra)


# ---------------- Laws: effects contract ----------------
# sim = {
#   "hero": Unit,
#   "enemies": List[Unit],
#   "events": List[str]  # short events
#   "tick_mods": {...},
#   "target_mods": {target_name: {"damage_mul":..., "taken_mul":...}},
#   "global_mods": {...},
#   "counters": {...},
# }
#
# Convention:
# - "damage_mul" affects outgoing damage to that target (attacker side multiplier)
# - "taken_mul" affects damage taken by that target (defender side multiplier)
# - You can also add simple statuses like bleed

def law_echo(sim: Dict):
    # Every 2nd hit repeats for 50% damage (any unit)
    sim["global_mods"]["echo"] = True

def law_third(sim: Dict):
    # Every 3rd hit deals x2 (any unit)
    sim["global_mods"]["third_double"] = True

def law_thorns(sim: Dict):
    # 20% of damage reflects to attacker (any unit)
    sim["global_mods"]["thorns"] = 0.20

def law_feast(sim: Dict):
    # Killer heals 30% of damage dealt (any unit)
    sim["global_mods"]["feast"] = 0.30

def law_bleed(sim: Dict):
    # Hits apply bleed: 2 dmg for 2 ticks (any unit)
    sim["global_mods"]["bleed"] = (2, 2)

def law_lowhp(sim: Dict):
    # Targets below 50% HP take x1.4 (defender)
    for u in [sim["hero"]] + sim["enemies"]:
        if u.is_alive() and u.hp_ratio() < 0.5:
            sim["target_mods"].setdefault(u.name, {})["taken_mul"] = (
                sim["target_mods"].get(u.name, {}).get("taken_mul", 1.0) * 1.4
            )

def law_slow(sim: Dict):
    # Everyone speed -0.25 (min 0.2)
    sim["tick_mods"]["speed_delta"] -= 0.25

def law_haste(sim: Dict):
    # Everyone speed +0.25
    sim["tick_mods"]["speed_delta"] += 0.25

def law_glass(sim: Dict):
    # All outgoing damage x1.25, but everyone takes x1.15 (global risk)
    sim["tick_mods"]["damage_out_mul"] *= 1.25
    sim["tick_mods"]["damage_taken_mul"] *= 1.15

def law_shield(sim: Dict):
    # First hit each tick against each unit is reduced by 6 (flat)
    sim["global_mods"]["shield_flat"] = 6

def law_bloom(sim: Dict):
    # On death, deal 8 to a random other opponent of the killer (simple bloom)
    sim["global_mods"]["bloom"] = 8

def law_focus(sim: Dict):
    # Repeated hits on same target: +15% per stack this tick (per attacker)
    sim["global_mods"]["focus"] = True


# Law registry (short names)
ALL_LAWS: Dict[str, Law] = {
    "echo":  Law("echo",  "Эхо",     "Каждый 2-й удар повторяется на 50%.", 0.22, law_echo),
    "third": Law("third", "Третий",  "Каждый 3-й удар наносит x2.",        0.25, law_third),
    "thorn": Law("thorn", "Шипы",    "20% урона отражается атакующему.",   0.18, law_thorns),
    "feast": Law("feast", "Пир",     "Убийца лечится на 30% нанесённого.", 0.20, law_feast),
    "bleed": Law("bleed", "Кровь",   "Удар даёт кровоток (2 урона × 2 тика).", 0.19, law_bleed),
    "lowhp": Law("lowhp", "Надлом",  "Цели <50% HP получают x1.4 урона.",  0.16, law_lowhp),
    "slow":  Law("slow",  "Тягость", "Скорость всех -0.25.",              0.14, law_slow),
    "haste": Law("haste", "Порыв",   "Скорость всех +0.25.",              0.18, law_haste),
    "glass": Law("glass", "Стекло",  "Урон x1.25, но входящий x1.15.",     0.23, law_glass),
    "shield":Law("shield","Щит",     "Первый удар по цели в тике -6 урона.",0.17, law_shield),
    "bloom": Law("bloom", "Всплеск", "Смерть вызывает отскок урона (8).",  0.21, law_bloom),
    "focus": Law("focus", "Фокус",   "Повтор по цели усиливает урон (в тике).", 0.17, law_focus),
}

# Synergies (pairs)
# Each synergy is (description, apply_fn(sim))
def syn_apply_third_echo(sim: Dict):
    # Third+Echo => repeats deal 70% and can also trigger third-double again for repeat
    sim["tick_mods"]["echo_repeat_mul"] = 0.70
    sim["tick_mods"]["echo_can_third"] = True

def syn_apply_bleed_feast(sim: Dict):
    # Bleed+Feast => bleed also heals the applier a little (tracked on tick)
    sim["tick_mods"]["bleed_feast_bonus"] = True

def syn_apply_slow_lowhp(sim: Dict):
    # Slow+LowHP => slowed targets take even more (extra x1.15)
    sim["tick_mods"]["slow_lowhp_bonus"] = True

def syn_apply_glass_shield(sim: Dict):
    # Glass+Shield => shield flat increases to 9
    sim["tick_mods"]["shield_bonus"] = 9

def syn_apply_focus_bloom(sim: Dict):
    # Focus+Bloom => bloom damage increases to 12
    sim["tick_mods"]["bloom_bonus"] = 12

def syn_apply_thorn_haste(sim: Dict):
    # Thorns+Haste => reflection increases to 28%
    sim["tick_mods"]["thorns_bonus"] = 0.28

SYNERGIES: Dict[frozenset, Tuple[str, callable]] = {
    frozenset(("third","echo")):  ("СИНЕРГИЯ: Эхо усиливается и может прокать «Третий».", syn_apply_third_echo),
    frozenset(("bleed","feast")): ("СИНЕРГИЯ: Кровь питает «Пир» (доп. лечение).", syn_apply_bleed_feast),
    frozenset(("slow","lowhp")):  ("СИНЕРГИЯ: «Тягость» добивает «Надлом» (ещё больнее).", syn_apply_slow_lowhp),
    frozenset(("glass","shield")):("СИНЕРГИЯ: «Щит» крепче под «Стеклом».", syn_apply_glass_shield),
    frozenset(("focus","bloom")): ("СИНЕРГИЯ: «Всплеск» сильнее при «Фокусе».", syn_apply_focus_bloom),
    frozenset(("thorn","haste")): ("СИНЕРГИЯ: «Шипы» злее на «Порыве».", syn_apply_thorn_haste),
}


# ---------------- Balance: waves & hero ----------------
def spawn_wave(wave: int) -> List[Unit]:
    """
    Баланс: wave1 проходима даже без законов.
    Scaling умеренный: больше врагов + чуть растут статы.
    """
    n = 3 + wave  # wave1 => 4 врага
    enemies: List[Unit] = []

    # базовые шаблоны
    for i in range(n):
        t = random.choices(
            population=["grunt","brute","skirm"],
            weights=[0.55, 0.20, 0.25],
            k=1
        )[0]

        if t == "grunt":
            hp = 16 + wave * 2.0
            atk = 3.2 + wave * 0.25
            spd = 1.0
            enemies.append(Unit(f"Пехотинец#{i+1}", hp=hp, max_hp=hp, atk=atk, speed=spd, tags=["grunt"]))
        elif t == "brute":
            hp = 44 + wave * 4.0
            atk = 7.5 + wave * 0.45
            spd = 0.75
            enemies.append(Unit(f"Огр#{i+1}", hp=hp, max_hp=hp, atk=atk, speed=spd, tags=["brute"]))
        else:
            hp = 11 + wave * 1.4
            atk = 2.4 + wave * 0.18
            spd = 1.55
            enemies.append(Unit(f"Бегун#{i+1}", hp=hp, max_hp=hp, atk=atk, speed=spd, tags=["skirm"]))

    return enemies


def reset_run(full_metrics: bool = True):
    st.session_state.wave = 1
    st.session_state.hero = Unit("Чернокнижник", hp=115.0, max_hp=115.0, atk=12.0, speed=1.0, tags=["hero"])
    st.session_state.enemies = spawn_wave(st.session_state.wave)
    st.session_state.instability = 0.0
    st.session_state.tick = 0
    st.session_state.counters = {"hit": 0, "last_target_by": {}}
    st.session_state.battle_state = "RUNNING"
    st.session_state.log = []
    st.session_state.recent = []
    st.session_state.tick_history = {"tick": [], "hero_hp": [], "avg_enemy_hp": []}
    st.session_state.counted_end = False
    if full_metrics:
        st.session_state.metrics = {"runs": 0, "avg_ticks": [], "dominant_builds": {}}


def start_next_wave():
    st.session_state.wave += 1
    st.session_state.hero = Unit("Чернокнижник", hp=115.0, max_hp=115.0, atk=12.0, speed=1.0, tags=["hero"])
    st.session_state.enemies = spawn_wave(st.session_state.wave)
    st.session_state.instability = 0.0
    st.session_state.tick = 0
    st.session_state.counters = {"hit": 0, "last_target_by": {}}
    st.session_state.battle_state = "RUNNING"
    st.session_state.log = []
    st.session_state.recent = []
    st.session_state.tick_history = {"tick": [], "hero_hp": [], "avg_enemy_hp": []}
    st.session_state.counted_end = False


# ---------------- Combat core ----------------
def apply_statuses(unit: Unit, side: str):
    # bleed tick
    if not unit.is_alive():
        return
    if "bleed" in unit.statuses and unit.statuses["bleed"] > 0:
        dmg = 2
        unit.hp -= dmg
        unit.statuses["bleed"] -= 1
        if side == "hero":
            short(f"🩸 Кровь: -{dmg} герою")
        else:
            short(f"🩸 Кровь: -{dmg} {unit.name}")
        log_full("status", f"Bleed tick on {unit.name}: -{dmg} (remain {unit.statuses['bleed']})")


def maybe_trigger_chaos(sim: Dict):
    # Chaos only inside tick, on threshold
    if st.session_state.instability < 1.0:
        return
    if sim.get("chaos_done"):
        return
    sim["chaos_done"] = True

    effect = random.choice(["shock_hero", "heal_enemies", "erase_law"])
    if effect == "shock_hero":
        st.session_state.hero.hp -= 18
        short("⚡ Хаос: разряд по герою (-18)")
        log_full("chaos", "Shock hero -18")
    elif effect == "heal_enemies":
        for e in st.session_state.enemies:
            if e.is_alive():
                e.hp = min(e.max_hp, e.hp + 14)
        short("🌀 Хаос: враги исцелились (+14)")
        log_full("chaos", "Heal enemies +14")
    else:
        if st.session_state.active_laws:
            lid = random.choice(st.session_state.active_laws)
            st.session_state.active_laws.remove(lid)
            short(f"🧿 Хаос: исчез закон «{ALL_LAWS[lid].name}»")
            log_full("chaos", f"Erase law {lid}")

    st.session_state.instability *= 0.45


def damage_pipeline(attacker: Unit, defender: Unit, base: float, sim: Dict, hit_index: int) -> float:
    dmg = base

    # global outgoing / taken multipliers
    dmg *= sim["tick_mods"]["damage_out_mul"]
    dmg *= sim["tick_mods"]["damage_taken_mul"]  # global risk (applies to everyone taking dmg)

    # per-target taken
    tm = sim["target_mods"].get(defender.name, {})
    dmg *= tm.get("taken_mul", 1.0)

    # focus: repeated hits by same attacker to same defender in this tick sequence
    if sim["global_mods"].get("focus"):
        key = attacker.name
        last = st.session_state.counters["last_target_by"].get(key)
        if last == defender.name:
            sim["counters_focus"].setdefault(key, 0)
            sim["counters_focus"][key] += 1
        else:
            sim["counters_focus"][key] = 0
        stacks = sim["counters_focus"][key]
        if stacks > 0:
            dmg *= (1.0 + 0.15 * stacks)

    # third hit double
    if sim["global_mods"].get("third_double"):
        if hit_index > 0 and hit_index % 3 == 0:
            dmg *= 2.0
            short("✨ Прок: «Третий» (x2)")
            log_full("proc", f"Third hit doubled (hit={hit_index})")

    # shield flat (first hit per target per tick)
    shield_flat = sim["global_mods"].get("shield_flat", 0)
    if shield_flat > 0:
        used = sim["shield_used"].get(defender.name, False)
        if not used:
            flat = shield_flat
            # synergy bonus
            if sim["tick_mods"].get("shield_bonus"):
                flat = max(flat, sim["tick_mods"]["shield_bonus"])
            dmg = max(0.0, dmg - flat)
            sim["shield_used"][defender.name] = True
            short("🛡️ Щит сработал")
            log_full("proc", f"Shield flat -{flat} on {defender.name}")

    # slow+lowhp synergy: if slow law active and target <50% hp => extra taken
    if sim["tick_mods"].get("slow_lowhp_bonus") and defender.hp_ratio() < 0.5:
        dmg *= 1.15

    return dmg


def on_hit_apply_effects(attacker: Unit, defender: Unit, dealt: float, sim: Dict):
    # thorns reflect
    th = sim["global_mods"].get("thorns", 0.0)
    if sim["tick_mods"].get("thorns_bonus") is not None and "thorn" in st.session_state.active_laws and "haste" in st.session_state.active_laws:
        th = sim["tick_mods"]["thorns_bonus"]
    if th and dealt > 0:
        r = dealt * th
        attacker.hp -= r
        short("🌵 Шипы: ответный урон")
        log_full("proc", f"Thorns reflect {r:.1f} to {attacker.name}")

    # bleed apply
    if sim["global_mods"].get("bleed") and dealt > 0:
        dmg_tick, ticks = sim["global_mods"]["bleed"]
        defender.statuses["bleed"] = max(defender.statuses.get("bleed", 0), ticks)
        short("🩸 Наложена кровь")
        log_full("proc", f"Bleed applied to {defender.name} ({ticks} ticks)")

    # feast heal on damage (and more on kill handled elsewhere)
    if sim["global_mods"].get("feast") and dealt > 0:
        heal = dealt * sim["global_mods"]["feast"] * 0.35  # small sustain per hit
        attacker.hp = min(attacker.max_hp, attacker.hp + heal)
        log_full("proc", f"Feast small heal {heal:.1f} to {attacker.name}")

    # echo repeat
    if sim["global_mods"].get("echo"):
        # every 2nd hit repeats
        if sim["hit_count"] % 2 == 0:
            mul = sim["tick_mods"].get("echo_repeat_mul", 0.5)
            # repeat can also third-double in synergy
            repeat_hit_index = sim["hit_count"]
            rep = damage_pipeline(attacker, defender, attacker.atk * mul, sim, repeat_hit_index)
            defender.hp -= rep
            short("🔁 Эхо: повтор")
            log_full("proc", f"Echo repeat {rep:.1f} to {defender.name}")

            # can third proc on repeat only if synergy enabled
            if not sim["tick_mods"].get("echo_can_third", False):
                # prevent third from accidentally doubling twice: we already ran pipeline, but it might have doubled.
                pass


def on_kill(attacker: Unit, victim: Unit, sim: Dict, victim_side: str):
    # feast heal on kill
    if sim["global_mods"].get("feast"):
        heal = victim.max_hp * 0.18
        attacker.hp = min(attacker.max_hp, attacker.hp + heal)
        short("🍖 Пир: лечение")
        log_full("proc", f"Feast kill heal {heal:.1f} to {attacker.name}")

    # bloom bounce
    if sim["global_mods"].get("bloom"):
        bounce = sim["global_mods"]["bloom"]
        if sim["tick_mods"].get("bloom_bonus") and ("focus" in st.session_state.active_laws and "bloom" in st.session_state.active_laws):
            bounce = max(bounce, sim["tick_mods"]["bloom_bonus"])

        if victim_side == "enemy":
            # enemy died => damage random other enemy? (to keep it neutral, bounce to same side as victim OR opposite?)
            # To keep tension and "rules for all", bounce goes to a random unit on VICTIM side (collateral).
            pool = [e for e in st.session_state.enemies if e.is_alive()]
            if pool:
                t = random.choice(pool)
                t.hp -= bounce
                short("💥 Всплеск: по врагам")
                log_full("proc", f"Bloom hits {t.name} for {bounce}")
        else:
            # hero died (rare mid-tick), bounce to enemies (collateral)
            pool = [e for e in st.session_state.enemies if e.is_alive()]
            if pool:
                t = random.choice(pool)
                t.hp -= bounce
                short("💥 Всплеск: по врагам")
                log_full("proc", f"Bloom hits {t.name} for {bounce}")


def sim_tick():
    if st.session_state.battle_state != "RUNNING":
        return

    hero: Unit = st.session_state.hero
    enemies: List[Unit] = [e for e in st.session_state.enemies if e.is_alive()]

    if not enemies:
        st.session_state.battle_state = "VICTORY"
        return

    st.session_state.tick += 1

    # base sim context
    sim = {
        "hero": hero,
        "enemies": enemies,
        "tick_mods": {
            "damage_out_mul": 1.0,
            "damage_taken_mul": 1.0,
            "speed_delta": 0.0,
            "echo_repeat_mul": 0.5,
            "echo_can_third": False,
            "shield_bonus": None,
            "bloom_bonus": None,
            "thorns_bonus": None,
            "slow_lowhp_bonus": False,
            "bleed_feast_bonus": False,
        },
        "target_mods": {},
        "global_mods": {},
        "shield_used": {},
        "counters_focus": {},
        "hit_count": st.session_state.counters["hit"],
    }

    # instability grows per active law
    for lid in st.session_state.active_laws:
        st.session_state.instability += ALL_LAWS[lid].instability_cost

    # apply laws
    for lid in st.session_state.active_laws:
        ALL_LAWS[lid].apply_fn(sim)

    # synergy apply
    if len(st.session_state.active_laws) == 2:
        pair = frozenset(st.session_state.active_laws)
        if pair in SYNERGIES:
            desc, fn = SYNERGIES[pair]
            fn(sim)
            short("🔗 " + desc.replace("СИНЕРГИЯ: ", ""))
            log_full("synergy", desc)

    # apply speed delta to all units this tick (temporary)
    all_units = [hero] + enemies
    for u in all_units:
        u.speed = max(0.2, u.speed + sim["tick_mods"]["speed_delta"])

    # chaos
    maybe_trigger_chaos(sim)

    # statuses tick first
    apply_statuses(hero, "hero")
    for e in enemies:
        apply_statuses(e, "enemy")

    # check deaths from statuses
    if hero.hp <= 0:
        st.session_state.battle_state = "DEFEAT"
        short("☠️ Герой пал")
        log_full("end", "DEFEAT by status")
        return
    enemies = [e for e in st.session_state.enemies if e.is_alive()]
    if not enemies:
        st.session_state.battle_state = "VICTORY"
        short("🏆 Победа")
        log_full("end", "VICTORY by status")
        return

    # --- Hero attacks ---
    # choose target: lowest HP enemy (readable)
    target = min(enemies, key=lambda x: x.hp)
    # hero attacks based on speed (usually 1)
    hero_hits = attacks_per_tick(hero.speed)
    for _ in range(hero_hits):
        if not target.is_alive():
            enemies = [e for e in st.session_state.enemies if e.is_alive()]
            if not enemies:
                break
            target = min(enemies, key=lambda x: x.hp)

        st.session_state.counters["hit"] += 1
        sim["hit_count"] = st.session_state.counters["hit"]
        st.session_state.counters["last_target_by"][hero.name] = target.name

        dmg = damage_pipeline(hero, target, hero.atk, sim, st.session_state.counters["hit"])
        target.hp -= dmg
        short(f"🧙 → {target.name}: -{dmg:.0f}")
        log_full("hero", f"Hero hits {target.name} for {dmg:.1f}")

        on_hit_apply_effects(hero, target, dmg, sim)

        if target.hp <= 0:
            short(f"💀 {target.name}")
            log_full("death", f"{target.name} dies")
            on_kill(hero, target, sim, "enemy")

    # --- Enemies attack ---
    # each enemy attacks based on its speed (fast can attack twice)
    for e in [x for x in st.session_state.enemies if x.is_alive()]:
        if not hero.is_alive():
            break
        hits = attacks_per_tick(e.speed)
        for _ in range(hits):
            if not hero.is_alive():
                break
            st.session_state.counters["hit"] += 1
            sim["hit_count"] = st.session_state.counters["hit"]
            st.session_state.counters["last_target_by"][e.name] = hero.name

            dmg = damage_pipeline(e, hero, e.atk, sim, st.session_state.counters["hit"])
            hero.hp -= dmg
            short(f"👹 {e.name} → герой: -{dmg:.0f}")
            log_full("enemy", f"{e.name} hits hero for {dmg:.1f}")

            on_hit_apply_effects(e, hero, dmg, sim)

            if hero.hp <= 0:
                log_full("end", "Hero dies in enemy phase")
                break

    # end conditions
    if hero.hp <= 0:
        st.session_state.battle_state = "DEFEAT"
        short("☠️ Герой пал")
        log_full("end", "DEFEAT")
    else:
        alive = [x for x in st.session_state.enemies if x.is_alive()]
        if not alive:
            st.session_state.battle_state = "VICTORY"
            short("🏆 Победа")
            log_full("end", "VICTORY")

    # tick history
    st.session_state.tick_history["tick"].append(st.session_state.tick)
    st.session_state.tick_history["hero_hp"].append(max(0.0, hero.hp))
    st.session_state.tick_history["avg_enemy_hp"].append(compute_avg_enemy_hp(st.session_state.enemies))


# ---------------- Rendering ----------------
def card_css():
    st.markdown(
        """
        <style>
        .law-card{
            border:1px solid rgba(255,255,255,0.12);
            border-radius:14px;
            padding:10px 12px;
            margin:10px 0;
            background: rgba(255,255,255,0.03);
        }
        .law-title{
            font-weight:700;
            font-size: 15px;
            margin-bottom: 4px;
        }
        .law-desc{
            font-size: 13px;
            opacity: 0.85;
            line-height: 1.25;
        }
        .tiny{
            font-size:12px;
            opacity:0.7;
        }
        </style>
        """,
        unsafe_allow_html=True
    )


def render_left_laws():
    st.subheader("Законы (до 2)")
    # Better selection: multiselect + cards list below (read-only)
    options = list(ALL_LAWS.keys())
    selected = st.multiselect(
        "Выбор",
        options=options,
        default=st.session_state.active_laws,
        max_selections=2,
        format_func=lambda lid: ALL_LAWS[lid].name,
        label_visibility="collapsed"
    )
    st.session_state.active_laws = list(selected)

    card_css()

    # show cards (with selection hint)
    for lid in options:
        law = ALL_LAWS[lid]
        picked = "✅ " if lid in st.session_state.active_laws else ""
        st.markdown(
            f"""
            <div class="law-card">
              <div class="law-title">{picked}{law.name}</div>
              <div class="law-desc">{law.desc}</div>
              <div class="tiny">нестабильность: +{law.instability_cost:.2f}/тик</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    # synergy preview
    if len(st.session_state.active_laws) == 2:
        pair = frozenset(st.session_state.active_laws)
        if pair in SYNERGIES:
            desc, _ = SYNERGIES[pair]
            st.info(desc)

    st.divider()

    c1, c2, c3 = st.columns(3)
    disabled = st.session_state.battle_state != "RUNNING"
    if c1.button("Step", disabled=disabled):
        sim_tick()
    if c2.button("Run", disabled=disabled):
        st.session_state.autoplay = True
    if c3.button("Stop"):
        st.session_state.autoplay = False

    st.slider("Скорость (сек/тик)", 0.05, 0.6, st.session_state.autoplay_delay, 0.01, key="autoplay_delay")

    st.divider()
    w1, w2 = st.columns(2)
    if w1.button("Next wave"):
        start_next_wave()
    if w2.button("Restart"):
        reset_run(full_metrics=False)

    st.caption(f"Tick: {st.session_state.tick} · Состояние: {st.session_state.battle_state}")


def render_middle_recent():
    st.subheader("Последние события")
    if not st.session_state.recent:
        st.write("—")
    else:
        for m in st.session_state.recent[-10:][::-1]:
            st.write(m)

    st.divider()
    st.markdown(f"**Волна #{st.session_state.wave} · {st.session_state.battle_state}**")
    inst = clamp(st.session_state.instability, 0.0, 1.0)
    st.progress(inst, text=f"Нестабильность: {st.session_state.instability:.2f}/1.00")


def unit_block(u: Unit, is_hero=False):
    title = "🧙 Герой" if is_hero else "👹 Враг"
    st.markdown(f"**{title}: {u.name}**")
    st.caption(f"ATK {u.atk:.1f} · SPD {u.speed:.2f}")
    st.progress(u.hp_ratio(), text=f"HP {max(0,u.hp):.1f}/{u.max_hp:.1f}")


def render_right_units():
    st.subheader("Участники")
    unit_block(st.session_state.hero, is_hero=True)
    st.markdown("**Враги**")
    alive = [e for e in st.session_state.enemies if e.is_alive()]
    if not alive:
        st.write("—")
    else:
        for e in alive[:12]:
            unit_block(e, is_hero=False)
        if len(alive) > 12:
            st.caption(f"и ещё {len(alive)-12}...")


def render_bottom_expander():
    with st.expander("Диаграмма и полный лог", expanded=False):
        st.markdown("### Диаграмма")
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
            st.write("Пока нет данных.")

        st.markdown("### Полный лог")
        st.text_area("log", value="\n".join(st.session_state.log[-400:]), height=320)


# ---------------- Init state ----------------
ss("active_laws", [])
ss("wave", 1)
ss("hero", Unit("Чернокнижник", hp=115.0, max_hp=115.0, atk=12.0, speed=1.0, tags=["hero"]))
ss("enemies", spawn_wave(1))
ss("instability", 0.0)
ss("tick", 0)
ss("counters", {"hit": 0, "last_target_by": {}})
ss("battle_state", "RUNNING")
ss("log", [])
ss("recent", [])
ss("tick_history", {"tick": [], "hero_hp": [], "avg_enemy_hp": []})
ss("metrics", {"runs": 0, "avg_ticks": [], "dominant_builds": {}})
ss("autoplay", False)
ss("autoplay_delay", 0.22)
ss("counted_end", False)


# ---------------- UI ----------------
st.title("Lawforge — RPG про переписывание законов")

left, mid, right = st.columns([1.45, 1.25, 1.30])

with left:
    render_left_laws()

with mid:
    render_middle_recent()

with right:
    render_right_units()

st.divider()
render_bottom_expander()


# ---------------- Autoplay engine ----------------
if st.session_state.autoplay and st.session_state.battle_state == "RUNNING":
    sim_tick()
    time.sleep(st.session_state.autoplay_delay)
    st.rerun()


# ---------------- End-of-battle bookkeeping ----------------
if st.session_state.battle_state != "RUNNING" and not st.session_state.counted_end:
    st.session_state.counted_end = True
    st.session_state.metrics["runs"] += 1
    st.session_state.metrics["avg_ticks"].append(st.session_state.tick)
    key = ",".join(sorted(st.session_state.active_laws)) if st.session_state.active_laws else "(no_laws)"
    st.session_state.metrics["dominant_builds"][key] = st.session_state.metrics["dominant_builds"].get(key, 0) + 1
elif st.session_state.battle_state == "RUNNING":
    st.session_state.counted_end = False
