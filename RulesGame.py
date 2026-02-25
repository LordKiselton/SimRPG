# app.py
# Lawforge — Streamlit прототип (Вариант A для текста событий)
#
# Изменения:
# ✅ "Последние события" переименовано в "Ход Боя"
# ✅ Тексты событий — Вариант A (человеческий боевой лог, чуть более развернутый)
# ✅ Итог хода и свёртка серий — НЕ добавлялись (как просил)
# ✅ Лечим баг "со второго клика":
#    - кнопки на on_click + key
#    - любое ручное действие выключает autoplay
#    - multiselect key + on_change
# ✅ При "Ход" события текущего тика показываются по одному (0.5s)

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


# ---------------- Session helpers ----------------
def ss(key, default):
    if key not in st.session_state:
        st.session_state[key] = default


def clamp(x, a, b):
    return max(a, min(b, x))


# ---------------- Formatting (events) ----------------
def html_badge(text: str, color: str) -> str:
    return f"<span style='color:{color}; font-weight:700'>{text}</span>"


def fmt_dmg(n: float) -> str:
    return html_badge(f"-{int(round(n))}", "#ff6b6b")


def fmt_heal(n: float) -> str:
    return html_badge(f"+{int(round(n))}", "#51cf66")


def fmt_tag(text: str) -> str:
    return html_badge(text, "#ffd43b")


def push_recent(msg_html: str):
    """Store short event (HTML) with tick prefix."""
    t = st.session_state.tick
    st.session_state.recent.append(f"<span style='opacity:0.6'>#{t}</span> {msg_html}")
    if len(st.session_state.recent) > 12:
        st.session_state.recent = st.session_state.recent[-12:]


def log_full(tag: str, msg: str):
    st.session_state.log.append(f"[{tag}] {msg}")
    if len(st.session_state.log) > 900:
        st.session_state.log = st.session_state.log[-900:]


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

def syn_apply_slow_lowhp(sim: Dict):
    sim["tick_mods"]["slow_lowhp_bonus"] = True

def syn_apply_glass_shield(sim: Dict):
    sim["tick_mods"]["shield_bonus"] = 9

def syn_apply_focus_bloom(sim: Dict):
    sim["tick_mods"]["bloom_bonus"] = 12

def syn_apply_thorn_haste(sim: Dict):
    sim["tick_mods"]["thorns_bonus"] = 0.28

SYNERGIES: Dict[frozenset, Tuple[str, callable]] = {
    frozenset(("third","echo")):   ("СИНЕРГИЯ: Эхо сильнее под «Третьим».", syn_apply_third_echo),
    frozenset(("slow","lowhp")):   ("СИНЕРГИЯ: «Тягость» усиливает «Надлом».", syn_apply_slow_lowhp),
    frozenset(("glass","shield")): ("СИНЕРГИЯ: «Щит» крепче под «Стеклом».", syn_apply_glass_shield),
    frozenset(("focus","bloom")):  ("СИНЕРГИЯ: «Всплеск» сильнее при «Фокусе».", syn_apply_focus_bloom),
    frozenset(("thorn","haste")):  ("СИНЕРГИЯ: «Шипы» злее на «Порыве».", syn_apply_thorn_haste),
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
    st.session_state.counters = {"hit": 0}
    st.session_state.battle_state = "RUNNING"
    st.session_state.log = []
    st.session_state.recent = []
    st.session_state.tick_history = {"tick": [], "hero_hp": [], "avg_enemy_hp": []}
    st.session_state.counted_end = False
    st.session_state.autoplay = False
    st.session_state.play_tick_events = []
    st.session_state.play_mode = False
    st.session_state.laws_sel = list(st.session_state.active_laws)
    if full_metrics:
        st.session_state.metrics = {"runs": 0, "avg_ticks": [], "dominant_builds": {}}


def start_next_wave():
    st.session_state.wave += 1
    st.session_state.hero = Unit("Чернокнижник", hp=115.0, max_hp=115.0, atk=12.0, speed=1.0, tags=["hero"])
    st.session_state.enemies = spawn_wave(st.session_state.wave)
    st.session_state.instability = 0.0
    st.session_state.tick = 0
    st.session_state.counters = {"hit": 0}
    st.session_state.battle_state = "RUNNING"
    st.session_state.log = []
    st.session_state.recent = []
    st.session_state.tick_history = {"tick": [], "hero_hp": [], "avg_enemy_hp": []}
    st.session_state.counted_end = False
    st.session_state.autoplay = False
    st.session_state.play_tick_events = []
    st.session_state.play_mode = False
    st.session_state.laws_sel = list(st.session_state.active_laws)


# ---------------- Combat core (Variant A text) ----------------
def apply_statuses(unit: Unit, tick_events: List[str]):
    if not unit.is_alive():
        return
    if unit.statuses.get("bleed", 0) > 0:
        dmg = 2
        unit.hp -= dmg
        unit.statuses["bleed"] -= 1
        tick_events.append(f"{fmt_tag('🩸 Кровоток')} {unit.name} теряет {fmt_dmg(dmg)}.")
        log_full("status", f"Bleed tick on {unit.name}: -{dmg} (remain {unit.statuses['bleed']})")


def maybe_trigger_chaos(sim: Dict, tick_events: List[str]):
    if st.session_state.instability < 1.0:
        return
    if sim.get("chaos_done"):
        return
    sim["chaos_done"] = True

    effect = random.choice(["shock_hero", "heal_enemies", "erase_law"])
    if effect == "shock_hero":
        st.session_state.hero.hp -= 18
        tick_events.append(f"{fmt_tag('🌀 Хаос')} бьёт по герою: {fmt_dmg(18)}.")
        log_full("chaos", "Shock hero -18")
    elif effect == "heal_enemies":
        for e in st.session_state.enemies:
            if e.is_alive():
                e.hp = min(e.max_hp, e.hp + 14)
        tick_events.append(f"{fmt_tag('🌀 Хаос')} враги восстанавливаются: {fmt_heal(14)}.")
        log_full("chaos", "Heal enemies +14")
    else:
        if st.session_state.active_laws:
            lid = random.choice(st.session_state.active_laws)
            st.session_state.active_laws.remove(lid)
            st.session_state.laws_sel = list(st.session_state.active_laws)
            tick_events.append(f"{fmt_tag('🌀 Хаос')} стирает закон «{ALL_LAWS[lid].name}».")
            log_full("chaos", f"Erase law {lid}")

    st.session_state.instability *= 0.45


def damage_pipeline(attacker: Unit, defender: Unit, base: float, sim: Dict, hit_index: int, tick_events: List[str]) -> float:
    dmg = base
    dmg *= sim["tick_mods"]["damage_out_mul"]
    dmg *= sim["tick_mods"]["damage_taken_mul"]

    tm = sim["target_mods"].get(defender.name, {})
    dmg *= tm.get("taken_mul", 1.0)

    # Third hit double
    if sim["global_mods"].get("third_double") and hit_index > 0 and hit_index % 3 == 0:
        dmg *= 2.0
        tick_events.append(f"{fmt_tag('✨ Третий')} это 3-е попадание — урон удвоен.")
        log_full("proc", f"Third doubled (hit={hit_index})")

    # Shield flat: first hit to defender per tick
    shield_flat = sim["global_mods"].get("shield_flat", 0)
    if shield_flat > 0 and not sim["shield_used"].get(defender.name, False):
        flat = shield_flat
        if sim["tick_mods"].get("shield_bonus") is not None:
            flat = max(flat, sim["tick_mods"]["shield_bonus"])
        dmg = max(0.0, dmg - flat)
        sim["shield_used"][defender.name] = True
        tick_events.append(f"{fmt_tag('🛡️ Щит')} спасает {defender.name}: -{int(flat)} урона срезано.")
        log_full("proc", f"Shield -{flat} on {defender.name}")

    # Slow+LowHP synergy bonus
    if sim["tick_mods"].get("slow_lowhp_bonus") and defender.hp_ratio() < 0.5:
        dmg *= 1.15

    return dmg


def on_hit_apply_effects(attacker: Unit, defender: Unit, dealt: float, sim: Dict, tick_events: List[str]):
    # Thorns reflect
    th = sim["global_mods"].get("thorns", 0.0)
    if sim["tick_mods"].get("thorns_bonus") is not None:
        th = sim["tick_mods"]["thorns_bonus"]
    if th and dealt > 0:
        r = dealt * th
        attacker.hp -= r
        tick_events.append(f"{fmt_tag('🌵 Шипы')} отвечают: {attacker.name} получает {fmt_dmg(r)}.")
        log_full("proc", f"Thorns reflect {r:.1f} to {attacker.name}")

    # Bleed
    if sim["global_mods"].get("bleed") and dealt > 0:
        _, ticks = sim["global_mods"]["bleed"]
        defender.statuses["bleed"] = max(defender.statuses.get("bleed", 0), ticks)
        tick_events.append(f"{fmt_tag('🩸 Кровь')} на {defender.name}: кровоток на {ticks} тика(ов).")
        log_full("proc", f"Bleed applied to {defender.name} ({ticks} ticks)")

    # Echo repeat: every 2nd global hit repeats at mul
    if sim["global_mods"].get("echo") and sim["hit_count"] % 2 == 0:
        mul = sim["tick_mods"].get("echo_repeat_mul", 0.5)
        rep = damage_pipeline(attacker, defender, attacker.atk * mul, sim, sim["hit_count"], tick_events)
        defender.hp -= rep
        tick_events.append(f"{fmt_tag('🔁 Эхо')} повторяет удар по {defender.name}: {fmt_dmg(rep)}.")
        log_full("proc", f"Echo repeat {rep:.1f} to {defender.name}")


def on_kill(sim: Dict, tick_events: List[str]):
    # Bloom collateral
    if sim["global_mods"].get("bloom"):
        bounce = sim["global_mods"]["bloom"]
        if sim["tick_mods"].get("bloom_bonus") is not None:
            bounce = max(bounce, sim["tick_mods"]["bloom_bonus"])
        pool = [e for e in st.session_state.enemies if e.is_alive()]
        if pool:
            t = random.choice(pool)
            t.hp -= bounce
            tick_events.append(f"{fmt_tag('💥 Всплеск')} задевает {t.name}: {fmt_dmg(bounce)}.")
            log_full("proc", f"Bloom hits {t.name} for {bounce}")


def sim_tick() -> List[str]:
    """Returns events of this tick (HTML strings)."""
    tick_events: List[str] = []

    if st.session_state.battle_state != "RUNNING":
        return tick_events

    hero: Unit = st.session_state.hero
    enemies: List[Unit] = [e for e in st.session_state.enemies if e.is_alive()]
    if not enemies:
        st.session_state.battle_state = "VICTORY"
        tick_events.append(f"{fmt_tag('🏆 Победа')} врагов больше нет.")
        return tick_events

    st.session_state.tick += 1

    sim = {
        "hero": hero,
        "enemies": enemies,
        "tick_mods": {
            "damage_out_mul": 1.0,
            "damage_taken_mul": 1.0,
            "speed_delta": 0.0,
            "echo_repeat_mul": 0.5,
            "shield_bonus": None,
            "bloom_bonus": None,
            "thorns_bonus": None,
            "slow_lowhp_bonus": False,
        },
        "target_mods": {},
        "global_mods": {},
        "shield_used": {},
        "hit_count": st.session_state.counters["hit"],
    }

    # instability grows per active law
    for lid in st.session_state.active_laws:
        st.session_state.instability += ALL_LAWS[lid].instability_cost

    # apply laws
    for lid in st.session_state.active_laws:
        ALL_LAWS[lid].apply_fn(sim)

    # synergies
    if len(st.session_state.active_laws) == 2:
        pair = frozenset(st.session_state.active_laws)
        if pair in SYNERGIES:
            desc, fn = SYNERGIES[pair]
            fn(sim)
            tick_events.append(f"{fmt_tag('🔗 Синергия')} {desc.replace('СИНЕРГИЯ: ', '')}")
            log_full("synergy", desc)

    # apply speed delta (temporary)
    for u in [hero] + enemies:
        u.speed = max(0.2, u.speed + sim["tick_mods"]["speed_delta"])

    # chaos
    maybe_trigger_chaos(sim, tick_events)

    # statuses tick
    apply_statuses(hero, tick_events)
    for e in enemies:
        apply_statuses(e, tick_events)

    # deaths by statuses
    if hero.hp <= 0:
        st.session_state.battle_state = "DEFEAT"
        tick_events.append(f"{fmt_tag('☠️ Поражение')} герой пал от эффектов.")
        log_full("end", "DEFEAT by status")
        for ev in tick_events:
            push_recent(ev)
        return tick_events

    enemies = [e for e in st.session_state.enemies if e.is_alive()]
    if not enemies:
        st.session_state.battle_state = "VICTORY"
        tick_events.append(f"{fmt_tag('🏆 Победа')} врагов больше нет.")
        log_full("end", "VICTORY by status")
        for ev in tick_events:
            push_recent(ev)
        return tick_events

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

        dmg = damage_pipeline(hero, target, hero.atk, sim, st.session_state.counters["hit"], tick_events)
        target.hp -= dmg

        tick_events.append(f"🧙 {hero.name} бьёт {target.name}: {fmt_dmg(dmg)}.")
        log_full("hero", f"{hero.name} hits {target.name} for {dmg:.1f}")

        on_hit_apply_effects(hero, target, dmg, sim, tick_events)

        if target.hp <= 0:
            tick_events.append(f"{fmt_tag('💀 Смерть')} {target.name} погибает.")
            log_full("death", f"{target.name} dies")
            on_kill(sim, tick_events)

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

            dmg = damage_pipeline(e, hero, e.atk, sim, st.session_state.counters["hit"], tick_events)
            hero.hp -= dmg

            tick_events.append(f"👹 {e.name} атакует героя: {fmt_dmg(dmg)}.")
            log_full("enemy", f"{e.name} hits {hero.name} for {dmg:.1f}")

            on_hit_apply_effects(e, hero, dmg, sim, tick_events)

            if hero.hp <= 0:
                break

    # end
    if hero.hp <= 0:
        st.session_state.battle_state = "DEFEAT"
        tick_events.append(f"{fmt_tag('☠️ Поражение')} герой пал.")
        log_full("end", "DEFEAT")
    else:
        alive = [x for x in st.session_state.enemies if x.is_alive()]
        if not alive:
            st.session_state.battle_state = "VICTORY"
            tick_events.append(f"{fmt_tag('🏆 Победа')} враги уничтожены.")
            log_full("end", "VICTORY")

    # history
    st.session_state.tick_history["tick"].append(st.session_state.tick)
    st.session_state.tick_history["hero_hp"].append(max(0.0, hero.hp))
    st.session_state.tick_history["avg_enemy_hp"].append(compute_avg_enemy_hp(st.session_state.enemies))

    # push into recent
    for ev in tick_events:
        push_recent(ev)

    return tick_events


# ---------------- UI callbacks (fix "second click") ----------------
def cb_laws_change():
    st.session_state.autoplay = False
    st.session_state.active_laws = list(st.session_state.laws_sel)


def cb_step():
    st.session_state.autoplay = False
    evs = sim_tick()
    st.session_state.play_tick_events = evs
    st.session_state.play_mode = True


def cb_run():
    st.session_state.autoplay = True


def cb_stop():
    st.session_state.autoplay = False


def cb_next_wave():
    st.session_state.autoplay = False
    start_next_wave()


def cb_restart():
    st.session_state.autoplay = False
    reset_run(full_metrics=False)


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
        .law-title{ font-weight:750; font-size:15px; margin-bottom:4px; }
        .law-desc{ font-size:13px; opacity:0.86; line-height:1.25; }
        .tiny{ font-size:12px; opacity:0.68; }
        </style>
        """,
        unsafe_allow_html=True
    )


def unit_line(u: Unit, emoji: str):
    st.markdown(f"**{emoji} {u.name}**")
    st.caption(f"ATK {u.atk:.1f} · SPD {u.speed:.2f}")
    st.progress(u.hp_ratio(), text=f"HP {max(0,u.hp):.1f}/{u.max_hp:.1f}")


def render_left_laws():
    st.subheader("Выбери до двух законов")

    options = list(ALL_LAWS.keys())
    st.multiselect(
        "Выбор",
        options=options,
        default=st.session_state.active_laws,
        max_selections=2,
        format_func=lambda lid: ALL_LAWS[lid].name,
        key="laws_sel",
        on_change=cb_laws_change,
        label_visibility="collapsed"
    )

    card_css()
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

    if len(st.session_state.active_laws) == 2:
        pair = frozenset(st.session_state.active_laws)
        if pair in SYNERGIES:
            desc, _ = SYNERGIES[pair]
            st.info(desc)


def render_right_controls_and_battle():
    disabled = st.session_state.battle_state != "RUNNING"

    c1, c2, c3 = st.columns(3)
    c1.button("Ход", disabled=disabled, on_click=cb_step, key="btn_step")
    c2.button("Бой", disabled=disabled, on_click=cb_run,  key="btn_run")
    c3.button("Стоп", on_click=cb_stop, key="btn_stop")

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
    st.markdown(f"### Волна #{st.session_state.wave}")
    inst = clamp(st.session_state.instability, 0.0, 1.0)
    st.progress(inst, text=f"Нестабильность: {st.session_state.instability:.2f}/1.00")

    if st.session_state.battle_state == "VICTORY":
        st.button("Следующая Волна", on_click=cb_next_wave, key="btn_next_wave")
    elif st.session_state.battle_state == "DEFEAT":
        st.button("Начать заново", on_click=cb_restart, key="btn_restart")

    st.divider()
    st.subheader("Ход Боя")

    # play tick events gradually (only after manual Step)
    if st.session_state.play_mode and st.session_state.play_tick_events:
        ph = st.empty()
        shown: List[str] = []
        for ev in st.session_state.play_tick_events:
            shown.append(f"<div style='margin:6px 0'>{ev}</div>")
            ph.markdown("\n".join(shown), unsafe_allow_html=True)
            time.sleep(0.5)
        st.session_state.play_mode = False
        st.session_state.play_tick_events = []

    if not st.session_state.recent:
        st.write("—")
    else:
        for m in st.session_state.recent[-10:][::-1]:
            st.markdown(f"<div style='margin:6px 0'>{m}</div>", unsafe_allow_html=True)


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
        st.text_area("log", value="\n".join(st.session_state.log[-500:]), height=320)


# ---------------- Init state ----------------
ss("active_laws", [])
ss("laws_sel", [])
ss("wave", 1)
ss("hero", Unit("Чернокнижник", hp=115.0, max_hp=115.0, atk=12.0, speed=1.0, tags=["hero"]))
ss("enemies", spawn_wave(1))
ss("instability", 0.0)
ss("tick", 0)
ss("counters", {"hit": 0})
ss("battle_state", "RUNNING")
ss("log", [])
ss("recent", [])
ss("tick_history", {"tick": [], "hero_hp": [], "avg_enemy_hp": []})
ss("metrics", {"runs": 0, "avg_ticks": [], "dominant_builds": {}})
ss("autoplay", False)
ss("autoplay_delay", 0.22)
ss("counted_end", False)
ss("play_tick_events", [])
ss("play_mode", False)

# Keep selector synced on first load
if not st.session_state.laws_sel and st.session_state.active_laws:
    st.session_state.laws_sel = list(st.session_state.active_laws)


# ---------------- UI layout ----------------
st.title("Lawforge — RPG про переписывание законов")

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
    # In autoplay we do not replay events one-by-one
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
