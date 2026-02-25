# app.py
# Lawforge — Streamlit прототип (UI правки + законы/баланс из предыдущей версии)
# - Законы (левый блок) уже ~в 1.75 раза
# - Блок "Бой" (правый) уже ~в 2 раза
# - Управление игрой (Ход/Бой/Стоп) перенесено наверх над "Бой"
# - В "Последние события" сверху: Волна + Нестабильность
# - Кнопки: при ПОБЕДЕ показываем "Следующая Волна", при ПОРАЖЕНИИ — "Начать заново" (видно и близко к событиям)
# - Убраны подписи "Герой/Враг" — оставлены только эмоджи + имя акторов

import time
import random
from dataclasses import dataclass, field
from typing import List, Dict, Tuple

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
    speed: float = 1.0
    tags: List[str] = field(default_factory=list)
    statuses: Dict[str, int] = field(default_factory=dict)

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
    apply_fn: callable


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
    base = int(speed)
    frac = speed - base
    extra = 1 if random.random() < frac else 0
    return max(0, base + extra)


# ---------------- Laws ----------------
def law_echo(sim: Dict):
    sim["global_mods"]["echo"] = True

def law_third(sim: Dict):
    sim["global_mods"]["third_double"] = True

def law_thorns(sim: Dict):
    sim["global_mods"]["thorns"] = 0.20

def law_feast(sim: Dict):
    sim["global_mods"]["feast"] = 0.30

def law_bleed(sim: Dict):
    sim["global_mods"]["bleed"] = (2, 2)

def law_lowhp(sim: Dict):
    for u in [sim["hero"]] + sim["enemies"]:
        if u.is_alive() and u.hp_ratio() < 0.5:
            sim["target_mods"].setdefault(u.name, {})["taken_mul"] = (
                sim["target_mods"].get(u.name, {}).get("taken_mul", 1.0) * 1.4
            )

def law_slow(sim: Dict):
    sim["tick_mods"]["speed_delta"] -= 0.25

def law_haste(sim: Dict):
    sim["tick_mods"]["speed_delta"] += 0.25

def law_glass(sim: Dict):
    sim["tick_mods"]["damage_out_mul"] *= 1.25
    sim["tick_mods"]["damage_taken_mul"] *= 1.15

def law_shield(sim: Dict):
    sim["global_mods"]["shield_flat"] = 6

def law_bloom(sim: Dict):
    sim["global_mods"]["bloom"] = 8

def law_focus(sim: Dict):
    sim["global_mods"]["focus"] = True


ALL_LAWS: Dict[str, Law] = {
    "echo":   Law("echo",   "Эхо",     "Каждый 2-й удар повторяется на 50%.",           0.22, law_echo),
    "third":  Law("third",  "Третий",  "Каждый 3-й удар наносит x2.",                   0.25, law_third),
    "thorn":  Law("thorn",  "Шипы",    "20% урона отражается атакующему.",              0.18, law_thorns),
    "feast":  Law("feast",  "Пир",     "Убийца лечится; урон даёт небольшое лечение.",  0.20, law_feast),
    "bleed":  Law("bleed",  "Кровь",   "Удар даёт кровоток (2 урона × 2 тика).",        0.19, law_bleed),
    "lowhp":  Law("lowhp",  "Надлом",  "Цели <50% HP получают x1.4 урона.",             0.16, law_lowhp),
    "slow":   Law("slow",   "Тягость", "Скорость всех -0.25.",                          0.14, law_slow),
    "haste":  Law("haste",  "Порыв",   "Скорость всех +0.25.",                          0.18, law_haste),
    "glass":  Law("glass",  "Стекло",  "Урон x1.25, но входящий x1.15.",                 0.23, law_glass),
    "shield": Law("shield", "Щит",     "Первый удар по цели в тике -6 урона.",          0.17, law_shield),
    "bloom":  Law("bloom",  "Всплеск", "Смерть вызывает отскок урона (8).",             0.21, law_bloom),
    "focus":  Law("focus",  "Фокус",   "Повтор по цели усиливает урон (в тике).",       0.17, law_focus),
}

# ---------------- Synergies ----------------
def syn_apply_third_echo(sim: Dict):
    sim["tick_mods"]["echo_repeat_mul"] = 0.70
    sim["tick_mods"]["echo_can_third"] = True

def syn_apply_bleed_feast(sim: Dict):
    sim["tick_mods"]["bleed_feast_bonus"] = True

def syn_apply_slow_lowhp(sim: Dict):
    sim["tick_mods"]["slow_lowhp_bonus"] = True

def syn_apply_glass_shield(sim: Dict):
    sim["tick_mods"]["shield_bonus"] = 9

def syn_apply_focus_bloom(sim: Dict):
    sim["tick_mods"]["bloom_bonus"] = 12

def syn_apply_thorn_haste(sim: Dict):
    sim["tick_mods"]["thorns_bonus"] = 0.28

SYNERGIES: Dict[frozenset, Tuple[str, callable]] = {
    frozenset(("third","echo")):   ("СИНЕРГИЯ: Эхо сильнее и может прокать «Третий».", syn_apply_third_echo),
    frozenset(("bleed","feast")):  ("СИНЕРГИЯ: Кровь подпитывает «Пир».",              syn_apply_bleed_feast),
    frozenset(("slow","lowhp")):   ("СИНЕРГИЯ: «Тягость» усиливает «Надлом».",         syn_apply_slow_lowhp),
    frozenset(("glass","shield")): ("СИНЕРГИЯ: «Щит» крепче под «Стеклом».",           syn_apply_glass_shield),
    frozenset(("focus","bloom")):  ("СИНЕРГИЯ: «Всплеск» сильнее при «Фокусе».",       syn_apply_focus_bloom),
    frozenset(("thorn","haste")):  ("СИНЕРГИЯ: «Шипы» злее на «Порыве».",              syn_apply_thorn_haste),
}


# ---------------- Balance: waves & hero ----------------
def spawn_wave(wave: int) -> List[Unit]:
    n = 3 + wave  # wave1 -> 4 enemies
    enemies: List[Unit] = []
    for i in range(n):
        t = random.choices(["grunt","brute","skirm"], weights=[0.55,0.20,0.25], k=1)[0]
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
    if not unit.is_alive():
        return
    if unit.statuses.get("bleed", 0) > 0:
        dmg = 2
        unit.hp -= dmg
        unit.statuses["bleed"] -= 1
        if side == "hero":
            short(f"🩸 -{dmg} {unit.name}")
        else:
            short(f"🩸 -{dmg} {unit.name}")
        log_full("status", f"Bleed tick on {unit.name}: -{dmg} (remain {unit.statuses['bleed']})")


def maybe_trigger_chaos(sim: Dict):
    if st.session_state.instability < 1.0:
        return
    if sim.get("chaos_done"):
        return
    sim["chaos_done"] = True

    effect = random.choice(["shock_hero", "heal_enemies", "erase_law"])
    if effect == "shock_hero":
        st.session_state.hero.hp -= 18
        short("⚡ Хаос: -18")
        log_full("chaos", "Shock hero -18")
    elif effect == "heal_enemies":
        for e in st.session_state.enemies:
            if e.is_alive():
                e.hp = min(e.max_hp, e.hp + 14)
        short("🌀 Хаос: враги +14")
        log_full("chaos", "Heal enemies +14")
    else:
        if st.session_state.active_laws:
            lid = random.choice(st.session_state.active_laws)
            st.session_state.active_laws.remove(lid)
            short(f"🧿 Хаос: -{ALL_LAWS[lid].name}")
            log_full("chaos", f"Erase law {lid}")

    st.session_state.instability *= 0.45


def damage_pipeline(attacker: Unit, defender: Unit, base: float, sim: Dict, hit_index: int) -> float:
    dmg = base
    dmg *= sim["tick_mods"]["damage_out_mul"]
    dmg *= sim["tick_mods"]["damage_taken_mul"]

    tm = sim["target_mods"].get(defender.name, {})
    dmg *= tm.get("taken_mul", 1.0)

    # Focus: repeat target ramp (per attacker)
    if sim["global_mods"].get("focus"):
        key = attacker.name
        last = st.session_state.counters["last_target_by"].get(key)
        if last == defender.name:
            sim["counters_focus"][key] = sim["counters_focus"].get(key, 0) + 1
        else:
            sim["counters_focus"][key] = 0
        stacks = sim["counters_focus"][key]
        if stacks > 0:
            dmg *= (1.0 + 0.15 * stacks)

    # Third hit double
    if sim["global_mods"].get("third_double"):
        if hit_index > 0 and hit_index % 3 == 0:
            dmg *= 2.0
            short("✨ Третий x2")
            log_full("proc", f"Third doubled (hit={hit_index})")

    # Shield flat: first hit to defender per tick
    shield_flat = sim["global_mods"].get("shield_flat", 0)
    if shield_flat > 0:
        if not sim["shield_used"].get(defender.name, False):
            flat = shield_flat
            if sim["tick_mods"].get("shield_bonus") is not None:
                flat = max(flat, sim["tick_mods"]["shield_bonus"])
            dmg = max(0.0, dmg - flat)
            sim["shield_used"][defender.name] = True
            short("🛡️ Щит")
            log_full("proc", f"Shield -{flat} on {defender.name}")

    # Slow+LowHP synergy bonus
    if sim["tick_mods"].get("slow_lowhp_bonus") and defender.hp_ratio() < 0.5:
        dmg *= 1.15

    return dmg


def on_hit_apply_effects(attacker: Unit, defender: Unit, dealt: float, sim: Dict):
    # Thorns reflect
    th = sim["global_mods"].get("thorns", 0.0)
    if sim["tick_mods"].get("thorns_bonus") is not None:
        th = sim["tick_mods"]["thorns_bonus"]
    if th and dealt > 0:
        r = dealt * th
        attacker.hp -= r
        short("🌵 Шипы")
        log_full("proc", f"Thorns reflect {r:.1f} to {attacker.name}")

    # Bleed
    if sim["global_mods"].get("bleed") and dealt > 0:
        _, ticks = sim["global_mods"]["bleed"]
        defender.statuses["bleed"] = max(defender.statuses.get("bleed", 0), ticks)
        short("🩸 Кровь")
        log_full("proc", f"Bleed applied to {defender.name} ({ticks} ticks)")

    # Feast sustain per hit (small)
    if sim["global_mods"].get("feast") and dealt > 0:
        heal = dealt * sim["global_mods"]["feast"] * 0.35
        attacker.hp = min(attacker.max_hp, attacker.hp + heal)
        log_full("proc", f"Feast heal {heal:.1f} to {attacker.name}")

    # Echo repeat: every 2nd global hit repeats at mul
    if sim["global_mods"].get("echo"):
        if sim["hit_count"] % 2 == 0:
            mul = sim["tick_mods"].get("echo_repeat_mul", 0.5)
            rep = damage_pipeline(attacker, defender, attacker.atk * mul, sim, sim["hit_count"])
            defender.hp -= rep
            short("🔁 Эхо")
            log_full("proc", f"Echo repeat {rep:.1f} to {defender.name}")


def on_kill(attacker: Unit, victim: Unit, sim: Dict):
    # Feast heal on kill
    if sim["global_mods"].get("feast"):
        heal = victim.max_hp * 0.18
        attacker.hp = min(attacker.max_hp, attacker.hp + heal)
        short("🍖 Пир")
        log_full("proc", f"Feast kill heal {heal:.1f} to {attacker.name}")

    # Bloom collateral
    if sim["global_mods"].get("bloom"):
        bounce = sim["global_mods"]["bloom"]
        if sim["tick_mods"].get("bloom_bonus") is not None:
            bounce = max(bounce, sim["tick_mods"]["bloom_bonus"])
        pool = [e for e in st.session_state.enemies if e.is_alive()]
        if pool:
            t = random.choice(pool)
            t.hp -= bounce
            short("💥 Всплеск")
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

    sim = {
        "hero": hero,
        "enemies": enemies,
        "tick_mods": {
            "damage_out_mul": 1.0,
            "damage_taken_mul": 1.0,
            "speed_delta": 0.0,
            "echo_repeat_mul": 0.5,
            "echo_can_third": False,  # reserved (we don't need special-casing due to pipeline)
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

    # instability
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

    # apply speed delta (temporary)
    for u in [hero] + enemies:
        u.speed = max(0.2, u.speed + sim["tick_mods"]["speed_delta"])

    # chaos
    maybe_trigger_chaos(sim)

    # statuses tick
    apply_statuses(hero, "hero")
    for e in enemies:
        apply_statuses(e, "enemy")

    if hero.hp <= 0:
        st.session_state.battle_state = "DEFEAT"
        short("☠️ Поражение")
        log_full("end", "DEFEAT by status")
        return

    enemies = [e for e in st.session_state.enemies if e.is_alive()]
    if not enemies:
        st.session_state.battle_state = "VICTORY"
        short("🏆 Победа")
        log_full("end", "VICTORY by status")
        return

    # hero attacks
    target = min(enemies, key=lambda x: x.hp)
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

        short(f"🧙 {hero.name} → {target.name} (-{dmg:.0f})")
        log_full("hero", f"{hero.name} hits {target.name} for {dmg:.1f}")

        on_hit_apply_effects(hero, target, dmg, sim)

        if target.hp <= 0:
            short(f"💀 {target.name}")
            log_full("death", f"{target.name} dies")
            on_kill(hero, target, sim)

    # enemies attack
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

            short(f"👹 {e.name} → {hero.name} (-{dmg:.0f})")
            log_full("enemy", f"{e.name} hits {hero.name} for {dmg:.1f}")

            on_hit_apply_effects(e, hero, dmg, sim)

            if hero.hp <= 0:
                break

    # end
    if hero.hp <= 0:
        st.session_state.battle_state = "DEFEAT"
        short("☠️ Поражение")
        log_full("end", "DEFEAT")
    else:
        alive = [x for x in st.session_state.enemies if x.is_alive()]
        if not alive:
            st.session_state.battle_state = "VICTORY"
            short("🏆 Победа")
            log_full("end", "VICTORY")

    # history
    st.session_state.tick_history["tick"].append(st.session_state.tick)
    st.session_state.tick_history["hero_hp"].append(max(0.0, hero.hp))
    st.session_state.tick_history["avg_enemy_hp"].append(compute_avg_enemy_hp(st.session_state.enemies))


# ---------------- UI helpers ----------------
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
            font-weight:750;
            font-size: 15px;
            margin-bottom: 4px;
        }
        .law-desc{
            font-size: 13px;
            opacity: 0.86;
            line-height: 1.25;
        }
        .tiny{
            font-size:12px;
            opacity:0.68;
        }
        </style>
        """,
        unsafe_allow_html=True
    )


def render_left_laws():
    st.subheader("Выбери до двух законов")
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

    # cards list (read-only visual)
    for lid in options:
        law = ALL_LAWS[lid]
        picked = "✅ " if lid in st.session_state.active_laws else ""
        st.markdown(
            f"""
            <div class="law-card">
              <div class="law-title">{picked}{law.name}</div>
              <div class="law-desc">{law.desc}</div>
              <div class="tiny">+{law.instability_cost:.2f} нестаб./тик</div>
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


def unit_line(u: Unit, emoji: str):
    st.markdown(f"**{emoji} {u.name}**")
    st.caption(f"ATK {u.atk:.1f} · SPD {u.speed:.2f}")
    st.progress(u.hp_ratio(), text=f"HP {max(0,u.hp):.1f}/{u.max_hp:.1f}")


def render_right_controls_and_battle():
    # controls above battle
    disabled = st.session_state.battle_state != "RUNNING"
    c1, c2, c3 = st.columns(3)
    if c1.button("Ход", disabled=disabled):
        sim_tick()
    if c2.button("Бой", disabled=disabled):
        st.session_state.autoplay = True
    if c3.button("Стоп"):
        st.session_state.autoplay = False

    st.slider("Скорость (сек/тик)", 0.05, 0.6, st.session_state.autoplay_delay, 0.01, key="autoplay_delay")

    st.divider()
    st.subheader("Бой")

    unit_line(st.session_state.hero, "🧙")

    alive = [e for e in st.session_state.enemies if e.is_alive()]
    if alive:
        for e in alive[:10]:
            unit_line(e, "👹")
        if len(alive) > 10:
            st.caption(f"…и ещё {len(alive)-10}")
    else:
        st.write("—")


def render_middle_events():
    # header: wave + instability + action button (victory/defeat)
    top = st.container()
    with top:
        st.markdown(f"### Волна #{st.session_state.wave}")
        inst = clamp(st.session_state.instability, 0.0, 1.0)
        st.progress(inst, text=f"Нестабильность: {st.session_state.instability:.2f}/1.00")

        # visible action buttons depending on outcome
        if st.session_state.battle_state == "VICTORY":
            if st.button("Следующая Волна"):
                start_next_wave()
        elif st.session_state.battle_state == "DEFEAT":
            if st.button("Начать заново"):
                reset_run(full_metrics=False)

    st.divider()
    st.subheader("Последние события")

    if not st.session_state.recent:
        st.write("—")
    else:
        for m in st.session_state.recent[-10:][::-1]:
            st.write(m)


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
ss("battle_state", "RUNNING")  # RUNNING / VICTORY / DEFEAT
ss("log", [])
ss("recent", [])
ss("tick_history", {"tick": [], "hero_hp": [], "avg_enemy_hp": []})
ss("metrics", {"runs": 0, "avg_ticks": [], "dominant_builds": {}})
ss("autoplay", False)
ss("autoplay_delay", 0.22)
ss("counted_end", False)


# ---------------- UI layout ----------------
st.title("Lawforge — RPG про переписывание законов")

# Column widths:
# - laws narrower ~1.75x: was ~1.45 -> ~0.83
# - battle narrower ~2x: was ~1.30 -> ~0.65
left, mid, right = st.columns([0.85, 2.55, 0.65])

with left:
    render_left_laws()

with mid:
    render_middle_events()

with right:
    render_right_controls_and_battle()

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
