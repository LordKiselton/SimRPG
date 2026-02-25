# app.py
# Улучшенный прототип "Законы боя" - Streamlit (визуализация, кадры, синергии, instability)
# Запуск: streamlit run app.py

import streamlit as st
import random, time
from dataclasses import dataclass, field
from typing import List, Dict
import pandas as pd

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

    def is_alive(self):
        return self.hp > 0

@dataclass
class Law:
    id: str
    name: str
    desc: str
    apply_fn: callable
    instability_cost: float = 0.2  # how much instability per tick it adds
    can_boost: bool = True

# ---------------- Session state init ----------------
if "wave" not in st.session_state:
    st.session_state.wave = 1
if "hero" not in st.session_state:
    st.session_state.hero = Unit("Чернокнижник", hp=100.0, max_hp=100.0, atk=10.0, speed=1.0, tags=["hero"])
if "enemies" not in st.session_state:
    def spawn_wave(n, wave):
        out=[]
        for i in range(n):
            t = random.choice(["grunt","brute","skirm"])
            if t=="grunt":
                out.append(Unit(f"Пехотинец#{i+1}", hp=20+wave*2, max_hp=20+wave*2, atk=4+wave*0.2, speed=1.0, tags=["grunt"]))
            elif t=="brute":
                out.append(Unit(f"Огр#{i+1}", hp=60+wave*5, max_hp=60+wave*5, atk=12+wave*0.5, speed=0.7, tags=["brute"]))
            else:
                out.append(Unit(f"Бегун#{i+1}", hp=12+wave*1.2, max_hp=12+wave*1.2, atk=3+wave*0.15, speed=1.6, tags=["skirm"]))
        return out
    st.session_state.enemies = spawn_wave(5, st.session_state.wave)
if "log" not in st.session_state:
    st.session_state.log = []
if "metrics" not in st.session_state:
    st.session_state.metrics = {"runs":0,"avg_ticks":[],"dominant_builds":{}, "boosts":0}
if "active_laws" not in st.session_state:
    st.session_state.active_laws = []
if "instability" not in st.session_state:
    st.session_state.instability = 0.0
if "tick_history" not in st.session_state:
    st.session_state.tick_history = {"tick":[], "hero_hp":[], "avg_enemy_hp":[]}
if "counters" not in st.session_state:
    st.session_state.counters = {"hit_count":0}
if "boost_cooldown" not in st.session_state:
    st.session_state.boost_cooldown = 0
if "boost_state" not in st.session_state:
    st.session_state.boost_state = {"active":False, "remaining":0, "law":None}

# ---------------- Law implementations ----------------
def law_double_every_third_hit(sim):
    # Единственный эффект: если hit_count %3 ==0 -> damage x2 for this tick
    sim['counters']['hit_count'] += 0  # counting done in actor
    if sim['counters']['hit_count'] % 3 == 0 and sim['counters']['hit_count']>0:
        sim['current_tick_mods']['damage_mul'] *= 2
        sim['events'].append(("double3","Третий удар удвоен"))

def law_vulnerable_if_slow(sim):
    # slow enemies take x2 damage (per-target)
    for e in sim['enemies']:
        if e.speed < 1.0:
            sim['mod_targets'].setdefault(e.name, {})['damage_mul'] = sim['mod_targets'].get(e.name, {}).get('damage_mul',1)*2
    sim['events'].append(("vuln_slow","Уязвимость замедленных"))

def law_crit_on_low_hp(sim):
    # targets below 50% hp take +50% damage; hero takes +20% enemy damage if hero below 30%
    for e in sim['enemies']:
        if e.hp / e.max_hp < 0.5:
            sim['mod_targets'].setdefault(e.name, {})['damage_mul'] = sim['mod_targets'].get(e.name, {}).get('damage_mul',1)*1.5
    if sim['hero'].hp / sim['hero'].max_hp < 0.3:
        sim['current_tick_mods']['enemy_damage_mul'] *= 1.2
    sim['events'].append(("crit_low","Крит по низкому HP"))

def law_death_bloom(sim):
    sim['current_tick_mods']['death_bloom'] = True
    sim['events'].append(("death_bloom","Взрыв при смерти"))

ALL_LAWS = {
    "double3": Law("double3", "Третий удар удваивается", "Каждый третий удар любого юнита наносит двойной урон.", law_double_every_third_hit, instability_cost=0.25),
    "vuln_slow": Law("vuln_slow", "Уязвимость замедленных", "Замедленные получают +100% урона.", law_vulnerable_if_slow, instability_cost=0.2),
    "crit_low": Law("crit_low", "Крит по беде", "Цели ниже 50% HP получают повышенный урон; если герой ниже 30% — враги сильнее.", law_crit_on_low_hp, instability_cost=0.18),
    "death_bloom": Law("death_bloom", "Взрыв при смерти", "При смерти — зона урона.", law_death_bloom, instability_cost=0.3),
}

# Synergy map (pair -> description & extra effects)
SYNERGIES = {
    frozenset(("double3","vuln_slow")): ("x4 по замедленным на каждом 3-м ударе", "damage_mul_bonus", 2.0),
    frozenset(("crit_low","death_bloom")): ("Смерть низкого HP вызывает массовый взрыв", "death_bloom_bonus", True),
}

# ---------------- Helpers ----------------
def reset_wave(n_enemies=5):
    st.session_state.hero = Unit("Чернокнижник", hp=100.0, max_hp=100.0, atk=10.0, speed=1.0, tags=["hero"])
    st.session_state.enemies = []
    for i in range(n_enemies):
        t = random.choice(["grunt","brute","skirm"])
        if t=="grunt":
            st.session_state.enemies.append(Unit(f"Пехотинец#{i+1}", hp=20+st.session_state.wave*2, max_hp=20+st.session_state.wave*2, atk=4+st.session_state.wave*0.2, speed=1.0, tags=["grunt"]))
        elif t=="brute":
            st.session_state.enemies.append(Unit(f"Огр#{i+1}", hp=60+st.session_state.wave*5, max_hp=60+st.session_state.wave*5, atk=12+st.session_state.wave*0.5, speed=0.7, tags=["brute"]))
        else:
            st.session_state.enemies.append(Unit(f"Бегун#{i+1}", hp=12+st.session_state.wave*1.2, max_hp=12+st.session_state.wave*1.2, atk=3+st.session_state.wave*0.15, speed=1.6, tags=["skirm"]))
    st.session_state.log = []
    st.session_state.instability = 0.0
    st.session_state.tick_history = {"tick":[], "hero_hp":[], "avg_enemy_hp":[]}
    st.session_state.counters = {"hit_count":0}
    st.session_state.boost_cooldown = 0
    st.session_state.boost_state = {"active":False, "remaining":0, "law":None}

def log(msg):
    st.session_state.log.append(msg)
    if len(st.session_state.log) > 400:
        st.session_state.log = st.session_state.log[-400:]

def compute_avg_enemy_hp():
    alive = [e for e in st.session_state.enemies if e.is_alive()]
    if not alive:
        return 0.0
    return sum(e.hp for e in alive)/len(alive)

# ---------------- Simulation tick ----------------
def sim_tick():
    # prepare sim context
    sim = {
        "hero": st.session_state.hero,
        "enemies": [e for e in st.session_state.enemies if e.is_alive()],
        "events": [],
        "counters": st.session_state.counters,
        "current_tick_mods": {"damage_mul":1.0, "enemy_damage_mul":1.0, "death_bloom":False},
        "mod_targets": {},
    }

    # instability accumulation
    for lid in st.session_state.active_laws:
        st.session_state.instability += ALL_LAWS[lid].instability_cost
    # if boost active, amplify instability a bit
    if st.session_state.boost_state['active']:
        st.session_state.instability += 0.05

    # apply laws (they mutate sim and append events)
    # also apply boost: if boosting a law, call its apply twice / extra effect
    for lid in st.session_state.active_laws:
        ALL_LAWS[lid].apply_fn(sim)
        if st.session_state.boost_state['active'] and st.session_state.boost_state['law']==lid:
            # boosted: call again or apply bonus
            ALL_LAWS[lid].apply_fn(sim)
            sim['events'].append(("boosted", f"Усиление закона {ALL_LAWS[lid].name} (boost)"))

    # synergy detection
    if len(st.session_state.active_laws)>=2:
        pair = frozenset(st.session_state.active_laws)
        if pair in SYNERGIES:
            desc, key, val = SYNERGIES[pair]
            sim['events'].append(("synergy", f"СИНЕРГИЯ: {desc}"))
            # apply simple effect
            if key=="damage_mul_bonus":
                sim['current_tick_mods']['damage_mul'] *= val

    # Hero attacks (target lowest HP)
    if sim["enemies"]:
        target = min(sim["enemies"], key=lambda x: x.hp)
        base = sim["hero"].atk
        dmg = base * sim["current_tick_mods"].get("damage_mul",1.0)
        td = sim["mod_targets"].get(target.name, {})
        dmg = dmg * td.get("damage_mul",1)
        # apply hit_count
        st.session_state.counters['hit_count'] = st.session_state.counters.get('hit_count',0)+1
        sim['events'].append(("hero_attack", f"Герой наносит {dmg:.1f} → {target.name}"))
        target.hp -= dmg
        if target.hp <= 0:
            sim['events'].append(("death", f"{target.name} пал"))
            if sim['current_tick_mods'].get("death_bloom"):
                others = [e for e in sim["enemies"] if e.name!=target.name and e.is_alive()]
                if others:
                    o = random.choice(others)
                    o.hp -= 8
                    sim['events'].append(("death_bloom", f"Взрыв ранил {o.name} на 8"))

    # Enemies attack
    for e in [x for x in sim["enemies"] if x.is_alive()]:
        base = e.atk
        dmg = base * sim["current_tick_mods"].get("enemy_damage_mul",1.0)
        # some enemies might have tags that interact
        st.session_state.hero.hp -= dmg
        sim['events'].append(("enemy_attack", f"{e.name} бьёт героя на {dmg:.1f}"))
        if st.session_state.hero.hp <= 0:
            sim['events'].append(("hero_death","Герой пал"))
            break

    # write back
    st.session_state.counters = sim['counters']
    # log events succinctly (keep last few)
    for ev in sim['events']:
        tag, txt = ev
        log(f"[{tag}] {txt}")
    # cleanup
    st.session_state.enemies = [e for e in st.session_state.enemies if e.is_alive()]

    # record tick history
    t = len(st.session_state.tick_history['tick'])+1
    st.session_state.tick_history['tick'].append(t)
    st.session_state.tick_history['hero_hp'].append(max(0,st.session_state.hero.hp))
    st.session_state.tick_history['avg_enemy_hp'].append(compute_avg_enemy_hp())

    # reduce boost timer & cooldown
    if st.session_state.boost_state['active']:
        st.session_state.boost_state['remaining'] -= 1
        if st.session_state.boost_state['remaining'] <= 0:
            st.session_state.boost_state = {"active":False, "remaining":0, "law":None}
            st.session_state.boost_cooldown = 8  # ticks
    if st.session_state.boost_cooldown>0:
        st.session_state.boost_cooldown -= 1

# ---------------- UI ----------------
st.title("Lawforge — визуальный прототип (улучшенная версия)")

left, mid, right = st.columns([1.4,1.8,1])

with left:
    st.header("Законы (выбери до 2)")
    # show available laws with checkboxes (but limit to 2)
    choices = []
    for k,v in ALL_LAWS.items():
        checked = k in st.session_state.active_laws
        cb = st.checkbox(f"{v.name} — {v.desc}", value=checked, key=f"cb_{k}")
        if cb:
            choices.append(k)
    # enforce limit
    if len(choices)>2:
        st.warning("Можно выбрать максимум 2 закона. Первые два сохранены.")
        choices = choices[:2]
    st.session_state.active_laws = choices

    st.markdown("**Интерактивные действия:**")
    colA, colB, colC = st.columns(3)
    if colA.button("Step (1 тик)"):
        sim_tick()
    if colB.button("Run (авто till end)", key="run_auto"):
        # run loop with visual frames
        frame_placeholder = st.empty()
        max_steps = 300
        step = 0
        while st.session_state.hero.is_alive() and any(e.is_alive() for e in st.session_state.enemies):
            sim_tick()
            step += 1
            # render frame into placeholder
            render_frame(frame_placeholder)
            time.sleep(0.25)
            if step>max_steps:
                log("Достигнут предел шагов (прервано)")
                break
        # metrics
        st.session_state.metrics['runs'] += 1
        st.session_state.metrics['avg_ticks'].append(step)
        key = ",".join(sorted(st.session_state.active_laws))
        st.session_state.metrics['dominant_builds'][key] = st.session_state.metrics['dominant_builds'].get(key,0)+1
    if colC.button("Restart wave"):
        st.session_state.wave += 1
        st.session_state.enemies = spawn_wave(4 + st.session_state.wave, st.session_state.wave)
        reset_wave(n_enemies=0)  # reset hero/hist but we replace enemies next
        # rebuild enemies properly
        st.session_state.enemies = spawn_wave(4 + st.session_state.wave, st.session_state.wave)

    st.markdown("---")
    st.subheader("Boost / вмешательство")
    st.write("Усиль выбранный закон кратковременно. Имеется cooldown.")
    available_law_to_boost = st.selectbox("Law to boost", options=[""] + st.session_state.active_laws, index=0)
    if st.button("Boost (3 тика)"):
        if not available_law_to_boost:
            st.warning("Выберите активный закон для усиления")
        elif st.session_state.boost_cooldown>0:
            st.warning(f"Boost в откате: {st.session_state.boost_cooldown} тиков")
        else:
            st.session_state.boost_state = {"active":True, "remaining":3, "law":available_law_to_boost}
            st.session_state.metrics['boosts'] += 1
            log(f"Boost: усилен {available_law_to_boost}")

with mid:
    # render arena & short controls via function (so run loop can call it)
    def render_frame(place):
        # top: instability bar + active laws badges
        with place.container():
            st.markdown(f"**Волна #{st.session_state.wave}**")
            inst = min(1.0, st.session_state.instability)
            st.progress(inst, text=f"Instability: {st.session_state.instability:.2f} / 1.0")
            # instability warnings
            if st.session_state.instability >= 1.0:
                st.error("Предел нестабильности! ХАОС может произойти.")
            # show active laws badges
            badges = []
            for lid in st.session_state.active_laws:
                name = ALL_LAWS[lid].name
                if st.session_state.boost_state['active'] and st.session_state.boost_state['law']==lid:
                    name = f"⚡ {name} (boost)"
                badges.append(f"`{name}`")
            st.markdown("Активные законы: " + (" ".join(badges) if badges else "_—_"))

            # synergy display
            if len(st.session_state.active_laws)>=2:
                pair = frozenset(st.session_state.active_laws)
                if pair in SYNERGIES:
                    desc = SYNERGIES[pair][0]
                    st.markdown(f"**🔗 СИНЕРГИЯ:** {desc}")

            # arena grid: render hero + enemies as simple cards
            cols = st.columns(6)
            # hero on left
            hero_col = cols[0]
            with hero_col:
                h = st.session_state.hero
                st.markdown("**Герой**")
                st.write(f"{h.name}")
                st.progress(max(0,h.hp)/h.max_hp, text=f"HP: {max(0,h.hp):.1f}/{h.max_hp:.1f}")
            # enemies
            en_cols = cols[1:]
            alive = [e for e in st.session_state.enemies if e.is_alive()]
            for i, c in enumerate(en_cols):
                if i < len(alive):
                    e = alive[i]
                    with c:
                        st.markdown(f"**{e.name}**")
                        st.write(f"Atk:{e.atk:.1f} Spd:{e.speed:.2f}")
                        st.progress(max(0,e.hp)/e.max_hp, text=f"HP: {max(0,e.hp):.1f}/{e.max_hp:.1f}")
                else:
                    with c:
                        st.write("---")

            # last events (compact)
            st.markdown("**Последние события**")
            for ln in st.session_state.log[-6:]:
                st.write(ln)

    # initial render
    frame_placeholder = st.empty()
    render_frame(frame_placeholder)

with right:
    st.header("Диаграммы / метрики")
    # tick chart
    if st.session_state.tick_history['tick']:
        df = pd.DataFrame({
            "tick": st.session_state.tick_history['tick'],
            "hero_hp": st.session_state.tick_history['hero_hp'],
            "avg_enemy_hp": st.session_state.tick_history['avg_enemy_hp']
        }).set_index('tick')
        st.line_chart(df)
    else:
        st.write("Графики появятся после первых тикoв")

    st.markdown("**Метрики**")
    st.write(st.session_state.metrics)
    st.markdown("---")
    st.subheader("Лог (полный)")
    st.text_area("Журнал", value="\n".join(st.session_state.log[-200:]), height=220)

# ---------------- Chaos check (instability overflow) ----------------
if st.session_state.instability >= 1.0:
    # trigger chaos: random big effect
    if any(e.is_alive() for e in st.session_state.enemies):
        # randomly buff or nerf
        effect = random.choice(["mass_heal_enemies","hero_shock","random_law_corrupt"])
        if effect=="mass_heal_enemies":
            for e in st.session_state.enemies:
                e.hp = min(e.max_hp, e.hp + 20)
            log("ХАОС: враги внезапно исцеляются (+20 HP)")
        elif effect=="hero_shock":
            st.session_state.hero.hp -= 25
            log("ХАОС: разряд по герою (-25 HP)")
        else:
            # corrupt a random active law (toggle its instability or remove)
            if st.session_state.active_laws:
                lid = random.choice(st.session_state.active_laws)
                st.session_state.active_laws.remove(lid)
                log(f"ХАОС: закон {lid} искажён и исчез")
    # reset instability partially
    st.session_state.instability *= 0.4

# ---------------- Small helpers for UI-run integration ----------------
# (we defined render_frame above; other buttons call sim_tick and then render_frame)
if st.button("Step + render (UI)"):
    sim_tick()
    frame_placeholder = st.empty()
    render_frame(frame_placeholder)

# ---------------- Footer / helper info ----------------
st.markdown("---")
st.caption("Подсказка: выбирай 1–2 закона, запускай Step или Run; попробуй Boost в ключевых моментах; наблюдай instability — он делает механику риск/награда.")
