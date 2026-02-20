
# majesty_game_ui_v3.py
# Streamlit Majesty-like procedural kingdom crisis prototype (7 days).
# UI changes v3:
# - Skull-segment bar for decay (10 skulls, filled)
# - Stats moved to the right of the chat
# - Active tags moved to the very bottom
# - NPC messages show the NPC name (no generic "Весть")
# - Game result is printed into the chat with emoji
# - "Двор:" removed; header shows "День N/X"
# - Title changed to "Королевство за Семь Дней" and subtitle updated
#
# Based on previous v2 file.

from __future__ import annotations
import os, json, uuid, random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Literal
import streamlit as st

Role = Literal["narrator", "player", "npc"]

ROLE_TO_CHAT = {"narrator":"assistant","npc":"assistant","player":"user"}
# Keep narrator/player prefixes; make npc prefix empty because we include NPC name in message content
ROLE_PREFIX = {"narrator": "🕯️ **Хроникёр**", "npc": "", "player":"👑 **Трон**"}

@dataclass
class Message:
    role: Role
    content: str

@dataclass
class Tag:
    name: str
    days_left: int

@dataclass
class Kingdom:
    seed: int = 42
    day: int = 1
    max_days: int = 7
    treasury: int = 55
    order: int = 55
    health: int = 55
    nobles: int = 55
    faith: int = 55
    border: int = 55
    decay: int = 0
    tags: List[Tag] = field(default_factory=list)
    log: List[Message] = field(default_factory=list)
    current_event_id: Optional[str] = None
    current_event: Optional[dict] = None
    announced_event_id: Optional[str] = None
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    def rng(self): return random.Random(self.seed + self.day * 1337)
    def clamp(self):
        for k in ("treasury","order","health","nobles","faith","border"):
            v = getattr(self, k); setattr(self, k, int(max(0, min(100, v))))
        self.decay = int(max(0, min(10, self.decay)))
    def push(self, role: Role, text: str): self.log.append(Message(role=role, content=text))
    def add_tag(self, name: str, days: int):
        for t in self.tags:
            if t.name == name:
                t.days_left = max(t.days_left, days); return
        self.tags.append(Tag(name=name, days_left=days))
    def has_tag(self, name: str) -> bool:
        return any(t.name == name and t.days_left>0 for t in self.tags)
    def tick_tags(self):
        for t in self.tags: t.days_left -= 1
        self.tags = [t for t in self.tags if t.days_left > 0]

GREEN = 60; YELLOW = 40
STAT_LABELS = {"treasury":"Казна","order":"Порядок","health":"Здоровье","nobles":"Знать","faith":"Вера","border":"Граница","decay":"Упадок"}

def zone(v:int)->str:
    if v>=GREEN: return "🟢"
    if v>=YELLOW: return "🟡"
    return "🔴"

def red_count(k: Kingdom)->int:
    return sum(1 for v in (k.treasury,k.order,k.health,k.nobles,k.faith,k.border) if v<YELLOW)
def green_count(k: Kingdom)->int:
    return sum(1 for v in (k.treasury,k.order,k.health,k.nobles,k.faith,k.border) if v>=GREEN)
def stable_state(k: Kingdom)->bool: return (red_count(k)==0) and (k.decay<=2)
def stability_score(k: Kingdom)->int:
    vals=[k.treasury,k.order,k.health,k.nobles,k.faith,k.border]
    base=sum(vals)//len(vals)
    penalty=sum(10 for v in vals if v<YELLOW)+sum(4 for v in vals if YELLOW<=v<GREEN)
    score=base-penalty-k.decay*5
    return int(max(0,min(100,score)))
def worst_stat(k: Kingdom)->Tuple[str,int]:
    items=[("Казна",k.treasury),("Порядок",k.order),("Здоровье",k.health),("Знать",k.nobles),("Вера",k.faith),("Граница",k.border)]
    items.sort(key=lambda x:x[1]); return items[0]

NPCS: Dict[str, dict] = {
    "chancellor": {"name": "Канцлер Медь-у-Ногтя", "emoji": "📣"},
    "marshal":    {"name": "Маршал Гримм из Северных Кольев", "emoji": "📣"},
    "bishop":     {"name": "Архиепископиня Серафима Пепельная", "emoji": "📣"},
    "physician":  {"name": "Лекарь Профитроль", "emoji": "📣"},
    "spymaster":  {"name": "Шептун Барон Без-Лица", "emoji": "📣"},
    "reeve":      {"name": "Староста Милая-Но-С-Молотком", "emoji": "📣"},
}
def npc_header(npc_id:str)->str:
    n=NPCS[npc_id]; return f"{n['emoji']} **{n['name']}**"

def trig_ok(k: Kingdom, trig: dict)->bool:
    for key,val in trig.items():
        if key.endswith("_lt"):
            stat=key[:-3]; 
            if getattr(k,stat)>=int(val): return False
        elif key.endswith("_gt"):
            stat=key[:-3];
            if getattr(k,stat)<=int(val): return False
        elif key=="has_tag":
            if not k.has_tag(val): return False
        elif key=="not_tag":
            if k.has_tag(val): return False
        elif key=="day_ge":
            if k.day< int(val): return False
        elif key=="day_le":
            if k.day> int(val): return False
        else: return False
    return True

def apply_effects(k: Kingdom, effects: dict)->dict:
    deltas={}
    for stat,delta in effects.items():
        if stat=="tags_add": continue
        if not hasattr(k,stat): continue
        d=int(delta)
        if d!=0:
            setattr(k,stat,getattr(k,stat)+d)
            deltas[stat]=d
    if "tags_add" in effects and isinstance(effects["tags_add"], dict):
        for tag_name,days in effects["tags_add"].items():
            k.add_tag(str(tag_name), int(days))
    k.clamp()
    return deltas

def weight_for_event(k: Kingdom, ev: dict)->int:
    w=int(ev.get("weight",1)); bias=ev.get("bias",{})
    for stat,mult in bias.items():
        v=getattr(k,stat)
        if v<YELLOW: w+=int(mult)*3
        elif v<GREEN: w+=int(mult)
    for tag,add in ev.get("tag_weight",{}).items():
        if k.has_tag(tag): w+=int(add)
    if k.day>=6 and ev.get("late_boost",False): w+=6
    return max(0,w)

def eligible_events(k: Kingdom, events: List[dict])->List[dict]:
    evs=[ev for ev in events if trig_ok(k, ev.get("trigger",{}))]
    return evs if evs else events[:]

# (EVENTS same as previous versions; omitted here for brevity — include the event definitions)
# For brevity in this snippet, we'll import EVENTS from the v2 file if available, else fallback to empty.
try:
    from majesty_game_ui_v2 import EVENTS  # type: ignore
except Exception:
    EVENTS = []

def event_resolution_decay_delta(k: Kingdom, before: dict, after: dict, ev: dict)->Tuple[int,List[str]]:
    reasons=[]; delta=0
    domain=ev.get("domain"); severity=int(ev.get("severity",1))
    if domain and domain in after and domain in before:
        b=int(before[domain]); a=int(after[domain])
        if a < YELLOW:
            delta += severity; reasons.append(f"кризис дня не купирован ({STAT_LABELS.get(domain,domain)} в 🔴) +{severity}")
        if b < YELLOW and a >= YELLOW:
            delta -= 1; reasons.append(f"кризис дня приглушён ({STAT_LABELS.get(domain,domain)} вышла из 🔴) -1")
        if b >= YELLOW and a < YELLOW:
            delta += 1; reasons.append(f"ты открыл новую рану ({STAT_LABELS.get(domain,domain)} упала в 🔴) +1")
    return delta, reasons

def global_state_decay_delta(k: Kingdom)->Tuple[int,List[str]]:
    reds=red_count(k); greens=green_count(k); reasons=[]; delta=0
    if reds >= 2: delta += 1; reasons.append("в государстве 2+ 🔴 зон +1")
    if greens == 6: delta -= 1; reasons.append("все показатели в 🟢 зоне -1")
    return delta, reasons

def system_end_of_day(k: Kingdom, rng: random.Random)->List[str]:
    beats=[]
    k.treasury -= 2; k.border -= 1
    if k.has_tag("tax_hike"): k.order -=1
    if k.has_tag("quarantine"): k.treasury -=1; k.order -=1
    if k.has_tag("licensed_smuggling"): k.order -=1
    if k.has_tag("purge"): k.nobles -=1; k.faith -=1
    if k.order < YELLOW: k.treasury -=1; k.health -=1
    if k.health < YELLOW: k.order -=1
    if k.treasury < YELLOW: k.order -=1
    if k.border < YELLOW: k.order -=1
    if k.order < 30 and rng.random() < 0.30:
        beats.append("К ночи слышны крики: в одном из кварталов ‘самоорганизовались’.")
        k.order -=6; k.treasury -=3
    if k.health < 30 and rng.random() < 0.30:
        beats.append("К рассвету город пахнет уксусом и травами.")
        k.health -=6; k.order -=3
    if k.border < 30 and rng.random() < 0.30:
        beats.append("Север присылает ‘письмо’ стрелами.")
        k.border -=6; k.treasury -=2
    k.clamp(); return beats

def ensure_analytics_dir():
    os.makedirs("analytics", exist_ok=True)
def analytics_path(k: Kingdom)->str:
    ensure_analytics_dir(); return os.path.join("analytics", f"{k.session_id}.jsonl")
def log_event(k: Kingdom, payload: dict):
    p=analytics_path(k); payload=dict(payload); payload["session_id"]=k.session_id
    with open(p,"a",encoding="utf-8") as f: f.write(json.dumps(payload, ensure_ascii=False)+"\n")

def init_game(seed:int)->Kingdom:
    k=Kingdom(seed=seed); k.day=1; k.max_days=7
    k.treasury=k.order=k.health=k.nobles=k.faith=k.border=55
    k.decay=0; k.tags=[]; k.log=[]
    k.current_event=None; k.current_event_id=None; k.announced_event_id=None
    k.push("narrator","**День первый — ‘Трон, перо и неизбежность’**\n\nКаждое утро вести стучатся в двери дворца.\n\n**Семь дней** — и королевство станет устойчивым… или станет историей.")
    return k

def pick_event(k: Kingdom)->dict:
    rng=k.rng(); evs=eligible_events(k, EVENTS); weights=[weight_for_event(k, ev) for ev in evs]
    if sum(weights)<=0: weights=[1 for _ in evs]
    return rng.choices(evs, weights=weights, k=1)[0]

def announce_event_if_needed(k: Kingdom):
    if not k.current_event or not k.current_event_id: return
    if k.announced_event_id == k.current_event_id: return
    ev = k.current_event
    # simplified presentation: push header that is just NPC name + intro
    k.push("npc", f"{npc_header(ev['npc'])}\n\n{ev['intro']}")
    k.announced_event_id = k.current_event_id

def new_day_event(k: Kingdom):
    ev = pick_event(k); k.current_event = ev; k.current_event_id = ev["id"]; announce_event_if_needed(k)

def snapshot(k: Kingdom)->dict:
    return {"day":k.day,"treasury":k.treasury,"order":k.order,"health":k.health,"nobles":k.nobles,"faith":k.faith,"border":k.border,"decay":k.decay,"tags":{t.name:t.days_left for t in k.tags},"event_id":k.current_event_id}

def diff(a:dict,b:dict)->dict:
    out={}
    for key in ("treasury","order","health","nobles","faith","border","decay"):
        out[key]=int(b[key])-int(a[key])
    return {kk:vv for kk,vv in out.items() if vv!=0}

def deltas_line_colored(deltas:dict)->str:
    keys=["treasury","order","health","nobles","faith","border","decay"]; parts=[]
    for k in keys:
        if k in deltas and deltas[k]!=0:
            d=deltas[k]; color="#22c55e" if d>0 else "#ef4444"; sign="+" if d>0 else ""
            parts.append(f"<span style='color:{color}; font-weight:700'>{STAT_LABELS[k]} {sign}{d}</span>")
    return " · ".join(parts) if parts else "Сдвиги мелкие — но мелочи иногда и ломают короны."

def render_skull_bar(decay:int)->str:
    filled = decay
    out=[]
    for i in range(10):
        if i < filled:
            out.append("<span style='font-size:20px; color:#ef4444;'>💀</span>")
        else:
            out.append("<span style='font-size:20px; color:#666666; opacity:0.3;'>💀</span>")
    return " ".join(out)

def ending(k: Kingdom)->str:
    if stable_state(k):
        return "🎉 **ПОБЕДА: Королевство удержано.**\n\nТы заставил державу не развалиться.\n\n**Упадок:** {}/10".format(k.decay)
    if k.decay >= 6 or red_count(k) >= 3:
        worst_name, worst_v = worst_stat(k)
        return "💀 **ПОРАЖЕНИЕ: Упадок победил.**\n\nСамая больная точка: **{}** ({}).\n\n**Упадок:** {}/10".format(worst_name, worst_v, k.decay)
    worst_name, worst_v = worst_stat(k)
    return "⚖️ **ФИНАЛ: На грани, но живы.**\n\nСамая слабая точка: **{}** ({}).\n\n**Упадок:** {}/10".format(worst_name,worst_v,k.decay)

def play_choice(k: Kingdom, choice_idx:int)->Optional[str]:
    rng=k.rng(); ev=k.current_event
    if not ev: new_day_event(k); ev=k.current_event
    before=snapshot(k); before_decay=k.decay
    ch=ev["choices"][choice_idx]
    apply_effects(k, ch["effects"])
    k.push("npc", ch.get("outro","Указ произнесён."))
    drift_beats = system_end_of_day(k, rng)
    for b in drift_beats: k.push("npc", b)
    after_mid = snapshot(k); ev_delta, ev_reasons = event_resolution_decay_delta(k, before, after_mid, ev)
    gl_delta, gl_reasons = global_state_decay_delta(k)
    k.decay += ev_delta + gl_delta; k.clamp()
    decay_change = k.decay - before_decay
    reasons = ev_reasons + gl_reasons
    if decay_change != 0:
        sign = "+" if decay_change > 0 else ""
        if reasons:
            decay_explain = f"**Почему упадок {sign}{decay_change}:** " + "; ".join(reasons) + "."
        else:
            decay_explain = f"**Почему упадок {sign}{decay_change}:** так сложились обстоятельства."
    else:
        decay_explain = "**Упадок не изменился:** сегодня ты не усилил трещины — и не залечил их до конца."
    k.tick_tags(); k.day += 1; k.clamp()
    after = snapshot(k); deltas = diff(before,after)
    narrator_text = f"**День {before['day']} завершён**\n\n**Сдвиги:** {deltas_line_colored(deltas)}\n\n{decay_explain}"
    k.push("narrator", narrator_text)
    log_event(k, {"type":"turn","turn":before["day"],"event_id":ev["id"],"choice_idx":choice_idx,"choice_text":ch["text"],"domain":ev.get("domain"),"severity":ev.get("severity"),"before":{kk:before[kk] for kk in ('treasury','order','health','nobles','faith','border','decay')}, "after":{kk:after[kk] for kk in ('treasury','order','health','nobles','faith','border','decay')},"deltas":deltas,"decay_reason":reasons,"stability_score":stability_score(k),"red_count":red_count(k)})
    end=None
    if k.day > k.max_days:
        end = ending(k)
        # push end into chat as narrator message
        k.push("narrator", end)
        log_event(k, {"type":"end","turn":k.max_days,"ending":"win" if stable_state(k) else ("collapse" if (k.decay>=6 or red_count(k)>=3) else "edge"), "final":snapshot(k),"stability_score":stability_score(k)})
    return end

# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="Королевство за Семь Дней", layout="wide")
st.markdown("""
<style>
.block-container { padding-top: 1.0rem; max-width: 1400px; }
.chat-feed { border:1px solid rgba(255,255,255,0.08); border-radius:14px; padding:8px; background:rgba(255,255,255,0.01);}
.card { border:1px solid rgba(255,255,255,0.10); border-radius:14px; padding:12px; background:rgba(255,255,255,0.02);}
.small { font-size:0.9rem; opacity:0.85; }
.decay-wrap { border:1px solid rgba(255,255,255,0.10); border-radius:12px; padding:8px; background:rgba(255,255,255,0.02); text-align:center; }
.stats-block { border:1px solid rgba(255,255,255,0.06); border-radius:12px; padding:8px; background:rgba(255,255,255,0.01); }
</style>
""", unsafe_allow_html=True)

st.title("Королевство за Семь Дней")
st.caption("Семь дней тебе дано — и ни мгновеньем более,  что удержать корону на лезвии судьбы.")

with st.sidebar:
    st.header("Сессия")
    seed = st.number_input("Seed", min_value=1, max_value=999999, value=42, step=1)
    if st.button("Новая партия (7 дней)", type="primary"):
        st.session_state["k"] = init_game(seed); st.session_state["ending"]=None
        new_day_event(st.session_state["k"]); st.rerun()
    st.divider()
    st.subheader("Аналитика")
    st.caption("Логи: ./analytics/<session>.jsonl")
    if "k" in st.session_state: st.code(analytics_path(st.session_state["k"]), language="text")

if "k" not in st.session_state:
    st.session_state["k"] = init_game(42); st.session_state["ending"]=None; new_day_event(st.session_state["k"])

k: Kingdom = st.session_state["k"]
if k.current_event and k.current_event_id: announce_event_if_needed(k)
elif not k.current_event: new_day_event(k)

# Top metrics row (without stability/day line)
top = st.columns(7)
top[0].metric("Казна", f"{zone(k.treasury)} {k.treasury}")
top[1].metric("Порядок", f"{zone(k.order)} {k.order}")
top[2].metric("Здоровье", f"{zone(k.health)} {k.health}")
top[3].metric("Знать", f"{zone(k.nobles)} {k.nobles}")
top[4].metric("Вера", f"{zone(k.faith)} {k.faith}")
top[5].metric("Граница", f"{zone(k.border)} {k.border}")
top[6].metric("Упадок", f"{k.decay}/10")

# prominent skull bar
st.markdown(f"<div class='decay-wrap'><div style='font-weight:800'>Упадок: {k.decay}/10</div><div style='margin-top:6px'>{render_skull_bar(k.decay)}</div></div>", unsafe_allow_html=True)

# Main layout: chat (left) + stats (right)
left, right = st.columns([0.7, 0.3], gap="large")

with left:
    st.subheader(f"День {k.day}/{k.max_days}")
    # chat feed
    chat_height = st.session_state.get("chat_height", 500); render_last = st.session_state.get("render_last", 120)
    feed = st.container(height=chat_height)
    with feed:
        st.markdown('<div class="chat-feed">', unsafe_allow_html=True)
        msgs = k.log[-render_last:] if k.log else []
        if not msgs:
            st.info("Пока пусто.")
        else:
            for m in msgs:
                with st.chat_message(ROLE_TO_CHAT[m.role]):
                    st.markdown(f"{ROLE_PREFIX[m.role]}\n\n{m.content}", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # choices
    st.markdown("### Решение трона")
    disabled = bool(st.session_state.get("ending")) or (k.day > k.max_days) or (k.current_event is None)
    ev = k.current_event
    if ev:
        choice_texts = [c["text"] for c in ev["choices"]]
        choice_idx = st.radio("", options=list(range(len(choice_texts))), format_func=lambda i: choice_texts[i], disabled=disabled, label_visibility="collapsed", key="choice_radio")
        b1,b2 = st.columns([1,1])
        with b1:
            if st.button("Издать указ", type="primary", use_container_width=True, disabled=disabled):
                k.push("player", f"Я решаю: **{choice_texts[choice_idx]}**")
                end = play_choice(k, choice_idx)
                st.session_state["ending"] = end
                if not st.session_state["ending"] and k.day <= k.max_days:
                    new_day_event(k)
                st.rerun()
        with b2:
            if st.button("Пропустить (плохая идея)", use_container_width=True, disabled=disabled):
                k.push("player", "Я решаю: **ничего не делать**.")
                k.current_event = {"id":"skip","npc":"chancellor","domain":"order","severity":2,"title":"Тишина","intro":"Во дворце тихо.","choices":[{"text":"…","effects":{"treasury":-2,"order":-2},"outro":"Ты ничего не сделал."}]}
                k.current_event_id = "skip"; k.announced_event_id=None
                announce_event_if_needed(k)
                end = play_choice(k, 0); st.session_state["ending"]=end
                if not st.session_state["ending"] and k.day <= k.max_days: new_day_event(k)
                st.rerun()

    # bottom: tags moved here
    with st.expander("Активные следы решений (в самом низу)"):
        if not k.tags: st.caption("Пока ничего не прилипло.")
        else:
            for t in k.tags: st.markdown(f"- `{t.name}` ещё **{t.days_left}** дн.")

with right:
    st.markdown("<div class='stats-block'>", unsafe_allow_html=True)
    st.subheader("Показатели")
    st.markdown(f"- Казна: {zone(k.treasury)} {k.treasury}")
    st.markdown(f"- Порядок: {zone(k.order)} {k.order}")
    st.markdown(f"- Здоровье: {zone(k.health)} {k.health}")
    st.markdown(f"- Знать: {zone(k.nobles)} {k.nobles}")
    st.markdown(f"- Вера: {zone(k.faith)} {k.faith}")
    st.markdown(f"- Граница: {zone(k.border)} {k.border}")
    st.markdown("</div>", unsafe_allow_html=True)

# Hidden controls
with st.expander("Настройки ленты (не трогать без нужды)"):
    st.session_state["chat_height"] = st.slider("Высота ленты", 250, 900, int(chat_height), 50)
    st.session_state["render_last"] = st.slider("Сколько сообщений показывать", 20, 200, int(render_last), 10)
    st.caption("🟢 ≥60, 🟡 40–59, 🔴 <40. Упадок растёт, если кризис дня не купирован и/или есть 2+ 🔴 зоны.")
