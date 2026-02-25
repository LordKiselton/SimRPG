# app.py
# Прототип "Законы боя" - Streamlit
# Запуск: streamlit run app.py

import streamlit as st
import random, time
from dataclasses import dataclass, field
from typing import List, Dict

st.set_page_config(layout="wide", page_title="Lawforge — прототип")

# ---------- Data models ----------
@dataclass
class Unit:
    name: str
    hp: float
    atk: float
    speed: float = 1.0
    tags: List[str] = field(default_factory=list)

    def is_alive(self):
        return self.hp > 0

@dataclass
class Law:
    id: str
    name: str
    desc: str
    apply_fn: callable  # function(sim_state) -> None
    passive: bool = True

# ---------- Simulation state ----------
if "wave" not in st.session_state:
    st.session_state.wave = 1
if "hero" not in st.session_state:
    st.session_state.hero = Unit("Чернокнижник", hp=100.0, atk=10.0, speed=1.0, tags=["hero"])
if "enemies" not in st.session_state:
    def spawn_wave(n):
        out=[]
        for i in range(n):
            t = random.choice(["grunt","brute","skirm"])
            if t=="grunt":
                out.append(Unit(f"Пехотинец#{i+1}", hp=20, atk=4, speed=1.0, tags=["grunt"]))
            elif t=="brute":
                out.append(Unit(f"Огр#{i+1}", hp=60, atk=12, speed=0.7, tags=["brute"]))
            else:
                out.append(Unit(f"Бегун#{i+1}", hp=12, atk=3, speed=1.6, tags=["skirm"]))
        return out
    st.session_state.enemies = spawn_wave(5)
if "log" not in st.session_state:
    st.session_state.log = []
if "metrics" not in st.session_state:
    st.session_state.metrics = {"runs":0,"avg_ticks":[],"dominant_builds":{}}
if "active_laws" not in st.session_state:
    st.session_state.active_laws = []

# ---------- Law definitions ----------
def law_double_every_third_hit(sim):
    """Каждый третий удар любого юнита наносит двойной урон (счёт общий)"""
    sim['counters']['hit_count'] += 1
    if sim['counters']['hit_count'] % 3 == 0:
        sim['current_tick_mods']['damage_mul'] *= 2
        sim['log'].append("Закон: третий удар двойной (в этом тике урон х2)")

def law_vulnerable_if_slow(sim):
    """Замедленные враги получают +100% урона"""
    for e in sim['enemies']:
        if e.speed < 1.0:
            sim['mod_targets'].setdefault(e.name, {})['damage_mul'] = sim['mod_targets'].get(e.name, {}).get('damage_mul',1)*2
    sim['log'].append("Закон: замедленные враги уязвимы (для текущего тика)")

def law_crit_on_low_hp(sim):
    """Если цель выше 50% HP, урон по ней уменьшается, иначе увеличивается"""
    sim['log'].append("Закон: урон изменяется в зависимости от HP цели (активен)")

def law_area_death_bloom(sim):
    """При смерти врага создаёт зону урона, ранящую ближайших (простой симулятивный эффект)"""
    sim['current_tick_mods']['death_bloom'] = True
    sim['log'].append("Закон: смертельный взрыв активирован (в этом тике)")

# Registry
ALL_LAWS = {
    "double3": Law("double3", "Третий удар удваивается", "Каждый третий удар любого юнита наносит двойной урон.", law_double_every_third_hit),
    "vuln_slow": Law("vuln_slow", "Уязвимость замедленных", "Замедленные получают +100% урона.", law_vulnerable_if_slow),
    "crit_low": Law("crit_low", "Крит по беде", "Цели ниже 50% HP получают повышенный урон.", law_crit_on_low_hp),
    "death_bloom": Law("death_bloom", "Взрыв при смерти", "При смерти — зона урона.", law_area_death_bloom),
}

# ---------- Helpers ----------
def reset_wave(n_enemies=5):
    st.session_state.hero = Unit("Чернокнижник", hp=100.0, atk=10.0, speed=1.0, tags=["hero"])
    st.session_state.enemies = []
    for i in range(n_enemies):
        t = random.choice(["grunt","brute","skirm"])
        if t=="grunt":
            st.session_state.enemies.append(Unit(f"Пехотинец#{i+1}", hp=20, atk=4, speed=1.0, tags=["grunt"]))
        elif t=="brute":
            st.session_state.enemies.append(Unit(f"Огр#{i+1}", hp=60, atk=12, speed=0.7, tags=["brute"]))
        else:
            st.session_state.enemies.append(Unit(f"Бегун#{i+1}", hp=12, atk=3, speed=1.6, tags=["skirm"]))
    st.session_state.log = []
    st.session_state.wave = 1
    st.session_state.active_laws = []

def log(msg):
    st.session_state.log.append(msg)
    # keep short
    if len(st.session_state.log) > 400:
        st.session_state.log = st.session_state.log[-400:]

# ---------- Simulation tick ----------
def sim_tick():
    sim = {
        "hero": st.session_state.hero,
        "enemies": [e for e in st.session_state.enemies if e.is_alive()],
        "log": st.session_state.log,
        "counters": st.session_state.get("counters", {"hit_count":0}),
        "current_tick_mods": {"damage_mul":1.0, "death_bloom":False},
        "mod_targets": {},
    }
    # apply passive law functions (they mutate sim)
    for lid in st.session_state.active_laws:
        ALL_LAWS[lid].apply_fn(sim)

    # Hero action: target the lowest HP enemy
    if sim["enemies"]:
        target = min(sim["enemies"], key=lambda x: x.hp)
        base = sim["hero"].atk
        dmg = base * sim["current_tick_mods"].get("damage_mul",1.0)
        # per-target modifiers
        td = sim["mod_targets"].get(target.name, {})
        dmg = dmg * td.get("damage_mul",1)
        # crit_low law check
        if "crit_low" in st.session_state.active_laws:
            if target.hp / (target.hp + dmg) < 0.5:  # rough proxy - if after hit below 50%
                dmg *= 1.5
        target.hp -= dmg
        sim["log"].append(f"Герой наносит {dmg:.1f} урона → {target.name} (HP={max(0,target.hp):.1f})")
        sim["counters"]['hit_count'] = sim['counters'].get('hit_count',0)+1
        # death
        if target.hp <= 0:
            sim["log"].append(f"{target.name} погибает")
            if sim["current_tick_mods"].get("death_bloom"):
                # simple bloom: damage random nearby enemy
                others = [e for e in sim["enemies"] if e.name!=target.name and e.is_alive()]
                if others:
                    o = random.choice(others)
                    o.hp -= 8
                    sim["log"].append(f"Взрыв при смерти ранит {o.name} на 8 → HP={max(0,o.hp):.1f}")

    # Enemies attack (each alive enemy attacks hero)
    for e in [x for x in sim["enemies"] if x.is_alive()]:
        # skip if died in hero phase
        base = e.atk
        dmg = base * sim["current_tick_mods"].get("damage_mul",1.0)
        # vuln_slow example: if e.speed < 1 -> they are slow (but law targets slow enemies to be vulnerable, not attackers)
        # simple: brute does more on low hp hero
        if "crit_low" in st.session_state.active_laws:
            if st.session_state.hero.hp < 50:
                dmg *= 1.2
        st.session_state.hero.hp -= dmg
        sim["log"].append(f"{e.name} бьёт героя на {dmg:.1f} → HP героя={max(0,st.session_state.hero.hp):.1f}")
        if st.session_state.hero.hp <= 0:
            sim["log"].append("Герой пал!")
            break

    # write back
    st.session_state.counters = sim["counters"]
    st.session_state.log = sim["log"]
    # cleanup dead enemies
    st.session_state.enemies = [e for e in st.session_state.enemies if e.is_alive()]

# ---------- UI layout ----------
st.title("Lawforge — текстовый прототип правил боя")

col1, col2, col3 = st.columns([1,1,1])

with col1:
    st.header("Активные законы")
    chosen = st.multiselect("Выбери до 2 законов (слоты):", options=[f"{k} — {v.name}" for k,v in ALL_LAWS.items()],
                            default=[f"{x} — {ALL_LAWS[x].name}" for x in st.session_state.active_laws])
    # map back to ids
    selected_ids = []
    for s in chosen:
        lid = s.split(" — ")[0]
        selected_ids.append(lid)
    if len(selected_ids) > 2:
        st.warning("Можно выбрать максимум 2 закона")
        selected_ids = selected_ids[:2]
    st.session_state.active_laws = selected_ids

    st.button("Step (один тик)", on_click=sim_tick)
    if st.button("Run wave (до конца)"):
        # run until hero dead or enemies dead
        tick_count = 0
        while st.session_state.hero.is_alive() and any(e.is_alive() for e in st.session_state.enemies):
            sim_tick()
            tick_count += 1
            if tick_count > 200:
                st.session_state.log.append("Техническое ограничение: прерван длинный раунд")
                break
        st.session_state.metrics['runs'] += 1
        st.session_state.metrics['avg_ticks'].append(tick_count)
        # track build use
        key = ",".join(sorted(st.session_state.active_laws))
        st.session_state.metrics['dominant_builds'][key] = st.session_state.metrics['dominant_builds'].get(key,0)+1

    if st.button("Next wave / Restart enemies"):
        st.session_state.wave += 1
        # spawn more enemies (scale)
        n = 4 + st.session_state.wave
        st.session_state.enemies = []
        for i in range(n):
            t = random.choice(["grunt","brute","skirm"])
            if t=="grunt":
                st.session_state.enemies.append(Unit(f"Пехотинец#{i+1}", hp=20+st.session_state.wave*2, atk=4+st.session_state.wave*0.2, speed=1.0, tags=["grunt"]))
            elif t=="brute":
                st.session_state.enemies.append(Unit(f"Огр#{i+1}", hp=60+st.session_state.wave*5, atk=12+st.session_state.wave*0.5, speed=0.7, tags=["brute"]))
            else:
                st.session_state.enemies.append(Unit(f"Бегун#{i+1}", hp=12+st.session_state.wave*1.2, atk=3+st.session_state.wave*0.15, speed=1.6, tags=["skirm"]))

    if st.button("Restart prototype"):
        reset_wave()

with col2:
    st.header("Состояние боя")
    st.subheader("Герой")
    h = st.session_state.hero
    st.write(f"**{h.name}** — HP: {h.hp:.1f}, ATK: {h.atk}, Speed: {h.speed}")
    st.subheader("Враги (живые)")
    for e in st.session_state.enemies:
        st.write(f"- {e.name}: HP {e.hp:.1f}, ATK {e.atk}, Speed {e.speed}")

with col3:
    st.header("Логи / Метрики")
    st.subheader("Лог")
    st.text_area("Журнал событий", value="\n".join(st.session_state.log[-200:]), height=300)
    st.subheader("Метрики")
    st.write(st.session_state.metrics)

st.markdown("---")
st.caption("Доступные законы (рабочий пул):")
for k,v in ALL_LAWS.items():
    st.write(f"**{v.name}** — {v.desc}")
