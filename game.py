# game.py
# Run:
#   pip install streamlit pandas
#   streamlit run game.py
#
# Optional:
#   Create factions.csv рядом с game.py:
#     name,power,stability,radicalization,resources
#     Merchants,60,70,20,75
#     Temple,55,65,40,55
#     Mages,45,50,30,50
#     Lodge,30,60,20,40
#     Council,35,50,25,45

from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Literal

import pandas as pd
import streamlit as st


# -----------------------------
# Data model
# -----------------------------

Role = Literal["narrator", "player", "world", "system"]

ROLE_TO_CHAT = {
    "narrator": "assistant",  # ведущий/мастер
    "world": "assistant",     # город/мир
    "system": "assistant",    # системные уведомления
    "player": "user",         # игрок
}

ROLE_PREFIX = {
    "narrator": "🕯️ **Хроникёр Нериссы**",
    "world": "🏙️ **Город**",
    "system": "⚙️ **Система**",
    "player": "🗡️ **Ты**",
}


@dataclass
class Message:
    role: Role
    content: str


@dataclass
class Faction:
    name: str
    power: int
    stability: int
    radicalization: int
    resources: int
    rel_player: int = 0

    def clamp(self):
        self.power = int(max(0, min(100, self.power)))
        self.stability = int(max(0, min(100, self.stability)))
        self.radicalization = int(max(0, min(100, self.radicalization)))
        self.resources = int(max(0, min(100, self.resources)))
        self.rel_player = int(max(-100, min(100, self.rel_player)))


@dataclass
class World:
    seed: int = 42
    day: int = 1
    max_days: int = 7

    economic_stress: int = 40
    public_fear: int = 30
    magical_tension: int = 50

    factions: Dict[str, Faction] = field(default_factory=dict)
    log: List[Message] = field(default_factory=list)

    crisis_truth: str = "unknown"  # lodge/mages/merchants/accident

    def rng(self) -> random.Random:
        return random.Random(self.seed + self.day * 999)

    def clamp(self):
        self.economic_stress = int(max(0, min(100, self.economic_stress)))
        self.public_fear = int(max(0, min(100, self.public_fear)))
        self.magical_tension = int(max(0, min(100, self.magical_tension)))
        for f in self.factions.values():
            f.clamp()

    def push(self, role: Role, text: str):
        self.log.append(Message(role=role, content=text))


# -----------------------------
# Load/save parameters
# -----------------------------

DEFAULT_FACTIONS = pd.DataFrame(
    [
        {"name": "Merchants", "power": 60, "stability": 70, "radicalization": 20, "resources": 75},
        {"name": "Temple",    "power": 55, "stability": 65, "radicalization": 40, "resources": 55},
        {"name": "Mages",     "power": 45, "stability": 50, "radicalization": 30, "resources": 50},
        {"name": "Lodge",     "power": 30, "stability": 60, "radicalization": 20, "resources": 40},
        {"name": "Council",   "power": 35, "stability": 50, "radicalization": 25, "resources": 45},
    ]
)

CSV_PATH = "factions.csv"


def load_factions_df() -> pd.DataFrame:
    if os.path.exists(CSV_PATH):
        df = pd.read_csv(CSV_PATH)
        cols = ["name", "power", "stability", "radicalization", "resources"]
        for c in cols:
            if c not in df.columns:
                raise ValueError(f"Missing column '{c}' in {CSV_PATH}")
        return df[cols].copy()
    return DEFAULT_FACTIONS.copy()


def save_factions_df(df: pd.DataFrame):
    df.to_csv(CSV_PATH, index=False)


def df_to_factions(df: pd.DataFrame) -> Dict[str, Faction]:
    factions: Dict[str, Faction] = {}
    for _, row in df.iterrows():
        f = Faction(
            name=str(row["name"]),
            power=int(row["power"]),
            stability=int(row["stability"]),
            radicalization=int(row["radicalization"]),
            resources=int(row["resources"]),
        )
        f.clamp()
        factions[f.name] = f
    return factions


# -----------------------------
# Narrative helpers
# -----------------------------

FACTION_RU = {
    "Merchants": "Торговая гильдия",
    "Temple": "Храм Пламени",
    "Mages": "Магический Круг",
    "Lodge": "Теневая Ложа",
    "Council": "Народный Совет",
}


def fr(name: str) -> str:
    return FACTION_RU.get(name, name)


DAY_NAME = {
    1: "День первый — «Слухи на мокрых причалах»",
    2: "День второй — «Голод рынка»",
    3: "День третий — «Шёпот у маяка»",
    4: "День четвёртый — «Окно возможностей»",
    5: "День пятый — «Искры над доками»",
    6: "День шестой — «Грань»",
    7: "День седьмой — «Приговор города»",
}


def day_title(d: int) -> str:
    return DAY_NAME.get(d, f"День {d}")


PLAYER_ACTIONS_RU = {
    "investigate": {
        "title": "Расследовать исчезновение корабля",
        "desc": "Собрать слухи, осмотреть доки, надавить на свидетелей. Ты ищешь правду — или хотя бы правдоподобную версию.",
    },
    "support_temple": {
        "title": "Поддержать Храм Пламени публично",
        "desc": "Ты говоришь о порядке и очищении. Толпа слушает. Маги мрачнеют.",
    },
    "support_mages": {
        "title": "Встать на защиту Магического Круга",
        "desc": "Ты защищаешь магов от обвинений и истерии. Храм воспринимает это как вызов.",
    },
    "support_merchants": {
        "title": "Помочь Торговой гильдии восстановить поставки",
        "desc": "Ты ищешь обходные пути, убеждаешь, покупаешь, договариваешься. Город любит тех, кто тушит пожар голода.",
    },
    "spread_rumour": {
        "title": "Запустить слухи против выбранной силы",
        "desc": "Немного шёпота — и репутация трещит. Но страх в городе тоже растёт.",
    },
    "bribe": {
        "title": "Подкупить посредников",
        "desc": "Деньги любят тишину. Ты покупаешь доступ, лояльность и закрытые двери.",
    },
    "noop": {
        "title": "Промолчать и наблюдать",
        "desc": "Иногда бездействие — тоже действие. Но город не любит пустоты: её заполняют другие.",
    },
}


# -----------------------------
# World init / step
# -----------------------------

def init_world_from_df(df: pd.DataFrame, seed: int, max_days: int) -> World:
    w = World(seed=seed, max_days=max_days)
    w.factions = df_to_factions(df)

    r = random.Random(seed)
    w.crisis_truth = r.choices(
        ["lodge", "mages", "merchants", "accident"],
        weights=[30, 30, 20, 20],
        k=1
    )[0]

    w.log = []
    w.day = 1

    w.economic_stress = 40
    w.public_fear = 30
    w.magical_tension = 50

    w.push(
        "narrator",
        f"**{day_title(1)}**\n\n"
        "В гавани Нериссы пропадает корабль с *астральным углём* — топливом для портовых механизмов и городской машинерии. "
        "Цены взлетают, лавки закрываются раньше, а у костров обсуждают одно и то же: **кто виноват и кому выгодно**."
    )

    w.economic_stress += 20
    w.public_fear += 15
    if "Mages" in w.factions:
        w.factions["Mages"].stability -= 10
        w.push("world", f"Слухи прежде всего бьют по {fr('Mages')}: «опять их печати, их ритуалы, их высокомерие».")
    w.clamp()
    return w


def compute_effective_power(f: Faction) -> int:
    return int((f.resources * 0.5 + f.power * 0.5) * (0.5 + f.stability / 200.0))


def faction_intent(w: World, f: Faction) -> str:
    if w.economic_stress > 70 and f.name == "Merchants":
        return "law"
    if w.magical_tension > 70 and f.name == "Temple":
        return "propaganda"
    if f.stability < 35 and f.name == "Mages":
        return "aid"
    if w.public_fear > 70 and f.name in ("Lodge", "Temple"):
        return "sabotage"
    return "propaganda"


def apply_player_action(w: World, action: str) -> str:
    rng = w.rng()

    if action == "noop":
        w.public_fear += 1
        return ("Ты выбираешь молчание. В переулках это читают по-разному: "
                "кто-то видит осторожность, кто-то — слабость. Город продолжает двигаться без тебя.")

    if action == "investigate":
        w.public_fear -= 4
        if w.crisis_truth == "lodge" and "Lodge" in w.factions:
            w.factions["Lodge"].stability -= 6
            return ("Ты обходишь причалы, говоришь с докерами и портовыми писарями. "
                    "Кто-то видел **маски** у маяка, кто-то — тень без фонаря. "
                    f"След ведёт к {fr('Lodge')} (−6 к стабильности).")
        if w.crisis_truth == "mages" and "Mages" in w.factions:
            w.factions["Mages"].stability -= 4
            w.magical_tension += 6
            return ("Ты находишь на обрывках паруса следы **сигилов** — слишком чистых для случайности. "
                    f"Подозрение падает на {fr('Mages')}, и город сжимает кулаки (напряжение магии +6).")
        if w.crisis_truth == "merchants" and "Merchants" in w.factions:
            w.factions["Merchants"].power -= 4
            w.factions["Merchants"].resources -= 6
            return ("Тебе попадается книга страховок: цифры сходятся слишком красиво. "
                    f"Слишком удобно для {fr('Merchants')}. Их версия трещит (−4 влияние, −6 ресурсы).")
        w.economic_stress -= 3
        return ("Портовый староста показывает карты и журнал ветров: шторм, неверные лоции, человеческая ошибка. "
                "Город чуть выдыхает (экономический стресс −3).")

    if action == "support_temple" and "Temple" in w.factions and "Mages" in w.factions:
        w.factions["Temple"].power += 6
        w.magical_tension += 5
        w.factions["Mages"].stability -= 3
        return ("Ты выступаешь на площади: «порядок важнее гордыни». "
                f"{fr('Temple')} поднимает знамёна (+6 влияние), но магический воздух густеет (напряжение +5).")

    if action == "support_mages" and "Mages" in w.factions and "Temple" in w.factions:
        w.factions["Mages"].stability += 6
        w.magical_tension -= 4
        w.factions["Temple"].radicalization += 4
        return ("Ты гасишь истерию и защищаешь магов от линчевания. "
                f"{fr('Mages')} держится увереннее (+6 стабильность), но {fr('Temple')} озлобляется (+4 радикализация).")

    if action == "support_merchants" and "Merchants" in w.factions and "Council" in w.factions:
        w.factions["Merchants"].resources += 6
        w.economic_stress -= 5
        w.factions["Council"].power -= 2
        return ("Ты находишь обходные цепочки поставок и уговариваешь нужных людей. "
                f"Стресс рынка падает (−5), {fr('Merchants')} богатеет (+6 ресурсы), Совет выглядит слабее (−2 влияние).")

    if action == "spread_rumour":
        target = rng.choice(list(w.factions.values()))
        target.power -= 4
        w.public_fear += 3
        return (f"Ты шепчешь нужным ушам: «{fr(target.name)} скрывает правду». "
                f"Их влияние падает (−4), но страх в городе растёт (+3).")

    if action == "bribe":
        target = rng.choice(list(w.factions.values()))
        target.rel_player += 8
        target.resources -= 3
        return (f"Ты платишь тихо и без свидетелей. "
                f"Люди {fr(target.name)} начинают узнавать тебя по шагам (+8 отношения).")

    return "Ты делаешь шаг — и город отвечает."


def apply_faction_action(w: World, actor: Faction, intent: str) -> str:
    rng = w.rng()
    others = [x for x in w.factions.values() if x.name != actor.name]
    target = rng.choice(others) if others else None

    if intent == "propaganda":
        delta = rng.randint(2, 6)
        actor.power += delta
        actor.radicalization += 1
        if actor.name == "Temple":
            w.magical_tension += 3
            return (f"{fr(actor.name)} раздувает костры и речи: «магия — искушение». "
                    f"Их влияние растёт (+{delta}), а напряжение магии усиливается (+3).")
        if actor.name == "Lodge":
            w.public_fear += 3
            return (f"{fr(actor.name)} запускает страх в подворотни: «ночью лучше не выходить». "
                    f"Их влияние растёт (+{delta}), страх +3.")
        return (f"{fr(actor.name)} ведёт кампанию в городе: плакаты, слухи, обещания. "
                f"Их влияние растёт (+{delta}).")

    if intent == "sabotage" and target:
        dmg = rng.randint(3, 8)
        target.stability -= dmg
        target.resources -= rng.randint(1, 5)
        w.public_fear += 4
        if rng.random() < 0.2:
            actor.power -= 5
            return (f"{fr(actor.name)} пытается ударить по {fr(target.name)} исподтишка (−{dmg} стабильность), "
                    "но следы всплывают (−5 влияние у инициатора).")
        return (f"{fr(actor.name)} подрывает позиции {fr(target.name)}: срыв поставок, подкуп свидетеля, ночной пожар. "
                f"{fr(target.name)} теряет устойчивость (−{dmg}). Страх +4.")

    if intent == "aid":
        actor.stability += 8
        actor.resources -= 3
        return (f"{fr(actor.name)} тушит внутренние пожары: дисциплина, охрана, контроль ритуалов. "
                f"+8 стабильности, но это стоит денег (−3 ресурсы).")

    if intent == "law":
        if actor.name == "Merchants":
            w.economic_stress -= 8
            actor.power += 3
            return (f"{fr(actor.name)} проталкивает чрезвычайные тарифы и новые маршруты. "
                    f"Стресс рынка −8, их влияние +3.")
        if actor.name == "Temple":
            w.magical_tension -= 5
            actor.power += 3
            return (f"{fr(actor.name)} добивается ограничений на магические практики. "
                    f"Напряжение магии −5, их влияние +3.")
        w.public_fear -= 3
        return f"{fr(actor.name)} проводит успокоительный указ: страх −3."

    return f"{fr(actor.name)} выжидает, считая ходы."


def system_escalations(w: World) -> List[str]:
    out: List[str] = []
    rng = w.rng()

    mages = w.factions.get("Mages")
    if mages and w.magical_tension > 75 and mages.stability < 35 and rng.random() < 0.35:
        out.append("Над доками вспыхивает рваная вспышка: ритуал срывается, железо плавится, люди кричат. "
                   "Город запоминает такие ночи надолго.")
        w.public_fear += 12
        w.economic_stress += 8
        mages.power -= 10
        mages.stability -= 10

    if w.public_fear > 80 and rng.random() < 0.30:
        out.append("Толпа становится зверем: витрины летят, стража отвечает дубинками, кто-то поджигает лавку. "
                   "После такого город просыпается другим.")
        w.economic_stress += 10
        w.public_fear += 5
        if "Council" in w.factions:
            w.factions["Council"].power -= 5
        if "Temple" in w.factions:
            w.factions["Temple"].power += 3

    if w.day in (3, 5) and rng.random() < 0.6:
        clue = {
            "lodge": "У маяка кто-то видел людей в масках: без фонаря, но уверенно, будто дорога им знакома.",
            "mages": "На обрывке паруса остаётся чистый след сигила — слишком точный, чтобы быть случайным.",
            "merchants": "В книге страховок мелькают одинаковые подписи — как будто кто-то заранее ждал пропажи.",
            "accident": "Журнал ветров говорит о внезапном шквале. Слишком резком для сезона."
        }[w.crisis_truth]
        out.append(f"Улика: {clue}")

    return out


def check_ending(w: World) -> Optional[str]:
    temple = w.factions.get("Temple")
    merchants = w.factions.get("Merchants")
    mages = w.factions.get("Mages")
    lodge = w.factions.get("Lodge")
    council = w.factions.get("Council")

    if mages and w.magical_tension > 85 and mages.stability < 25:
        return ("**Арканная катастрофа.**\n\nДоковая линия горит фиолетовым пламенем, механизмы молчат, "
                "а улицы шепчут только одно слово: «магия». Храм требует чрезвычайной власти — и получает её.")

    if temple and temple.radicalization > 75 and w.public_fear > 65 and temple.power > 70:
        return ("**Теократия.**\n\nХрам Пламени объявляет город священной территорией, вводит запреты и караулы. "
                "Магия — вне закона. Спокойствие приходит, но оно пахнет дымом.")

    if merchants and merchants.power > 78 and w.economic_stress < 45:
        return ("**Торговый протекторат.**\n\nРынок стабилизируется, хлеб возвращается на прилавки, "
                "но город начинает измерять людей монетой. Власть переходит к тем, кто держит склады.")

    if lodge and lodge.power > 60 and w.public_fear > 70:
        return ("**Теневая регентура.**\n\nСтрах становится валютой. Правда — роскошью. "
                "В городе тихо, потому что каждый боится сказать лишнее.")

    if council and council.power > 60 and w.public_fear < 55 and w.economic_stress < 55:
        return ("**Гражданская реформа.**\n\nСовет собирает фракции за одним столом. "
                "Компромисс хрупок, но город впервые за долгое время дышит свободнее.")

    return None


def step_world(w: World, player_action: str) -> Optional[str]:
    w.push("narrator", f"**{day_title(w.day)}**")
    w.push("player", apply_player_action(w, player_action))

    for f in list(w.factions.values()):
        intent = faction_intent(w, f)
        w.push("world", apply_faction_action(w, f, intent))

    for e in system_escalations(w):
        w.push("world", e)

    w.public_fear += 1 if w.economic_stress > 65 else -2
    w.economic_stress += 1 if w.public_fear > 75 else 0
    if "Temple" in w.factions and "Mages" in w.factions:
        w.magical_tension += 1 if w.factions["Temple"].power > w.factions["Mages"].power + 20 else -1

    w.clamp()
    ending = check_ending(w)
    w.day += 1
    return ending


# -----------------------------
# Streamlit UI (Variant B + separate log window)
# -----------------------------

st.set_page_config(page_title="Нерисса: CRPG-диалог + HUD", layout="wide")

st.markdown("""
<style>
.block-container { padding-top: 1.0rem; max-width: 1200px; }
.hud-card {
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px;
  padding: 12px 12px;
  margin-bottom: 10px;
  background: rgba(255,255,255,0.02);
}
.hud-title { font-weight: 700; font-size: 0.95rem; margin-bottom: 6px; opacity: 0.95; }
.hud-small { font-size: 0.85rem; opacity: 0.85; }
.choice-wrap {
  position: sticky;
  bottom: 0;
  z-index: 10;
  padding-top: 10px;
  background: linear-gradient(to top, rgba(14,17,23,0.98), rgba(14,17,23,0.0));
}
</style>
""", unsafe_allow_html=True)

st.title("Нерисса: Пепельная неделя — вертикальный срез")
st.caption("Слева — диалог (как в CRPG), справа — HUD города. Журнал вынесен отдельно, чтобы главный экран оставался чистым.")

with st.sidebar:
    st.header("Сессия")
    seed = st.number_input("Seed (для повторяемости)", min_value=1, max_value=999999, value=42, step=1)
    max_days = st.slider("Длительность эпизода (дней)", min_value=3, max_value=30, value=7, step=1)

    st.divider()
    st.header("Баланс (CSV)")
    st.caption(f"Файл: {CSV_PATH}")
    if os.path.exists(CSV_PATH):
        st.success("factions.csv найден")
    else:
        st.info("factions.csv не найден — используется дефолт")

    if st.button("Перезагрузить фракции из CSV"):
        st.session_state["factions_df"] = load_factions_df()
        st.toast("Загружено", icon="✅")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Сохранить фракции в CSV"):
            save_factions_df(st.session_state.get("factions_df", load_factions_df()))
            st.toast("Сохранено", icon="💾")
    with c2:
        if st.button("Сбросить на дефолт"):
            st.session_state["factions_df"] = DEFAULT_FACTIONS.copy()
            st.toast("Сброшено", icon="🔄")

    st.divider()
    st.subheader("Таблица фракций (редактируемая)")
    st.caption("Правки применятся после **Новая игра / Сброс мира**.")

    if "factions_df" not in st.session_state:
        st.session_state["factions_df"] = load_factions_df()

    edited = st.data_editor(
        st.session_state["factions_df"],
        num_rows="dynamic",
        use_container_width=True,
        key="factions_editor",
    )

    expected = ["name", "power", "stability", "radicalization", "resources"]
    for c in expected:
        if c not in edited.columns:
            st.error(f"Отсутствует колонка: {c}")
            st.stop()

    edited = edited[expected].copy()
    for c in ["power", "stability", "radicalization", "resources"]:
        edited[c] = pd.to_numeric(edited[c], errors="coerce").fillna(0).astype(int).clip(0, 100)
    edited["name"] = edited["name"].astype(str)
    st.session_state["factions_df"] = edited

    st.divider()
    if st.button("Новая игра / Сброс мира", type="primary"):
        df = st.session_state.get("factions_df", load_factions_df())
        st.session_state["world"] = init_world_from_df(df, seed=seed, max_days=max_days)
        st.session_state["ending"] = None
        st.toast("Мир перезапущен", icon="🌍")


if "world" not in st.session_state:
    df0 = st.session_state.get("factions_df", load_factions_df())
    st.session_state["world"] = init_world_from_df(df0, seed=seed, max_days=max_days)

if "ending" not in st.session_state:
    st.session_state["ending"] = None

w: World = st.session_state["world"]


# --- LAYOUT: Variant B ---
chat_col, hud_col = st.columns([0.70, 0.30], gap="large")

with hud_col:
    st.markdown('<div class="hud-card">', unsafe_allow_html=True)
    st.markdown('<div class="hud-title">Панель города</div>', unsafe_allow_html=True)
    st.metric("Экономический стресс", w.economic_stress)
    st.metric("Общественный страх", w.public_fear)
    st.metric("Напряжение магии", w.magical_tension)

    risks = []
    if w.public_fear >= 80:
        risks.append("⚠️ Возможен бунт")
    if w.economic_stress >= 75:
        risks.append("⚠️ Рынок на грани срыва")
    if w.magical_tension >= 80:
        risks.append("⚠️ Риск магической аварии")
    if not risks:
        risks.append("✅ Пороговых рисков нет")

    st.markdown("<div class='hud-small'>" + "<br>".join(risks) + "</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="hud-card">', unsafe_allow_html=True)
    st.markdown('<div class="hud-title">Фракции</div>', unsafe_allow_html=True)
    rows = []
    for f in w.factions.values():
        rows.append({
            "фракция": fr(f.name),
            "влияние": f.power,
            "стаб": f.stability,
            "рад": f.radicalization,
            "рес": f.resources,
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("Подробности (отладка)"):
        rows2 = []
        for f in w.factions.values():
            rows2.append({
                "фракция": fr(f.name),
                "эфф_сила": compute_effective_power(f),
                "отношение_к_тебе": f.rel_player,
            })
        st.dataframe(pd.DataFrame(rows2), use_container_width=True, hide_index=True)

with chat_col:
    st.subheader(f"Сцена: день {w.day}/{w.max_days}")

    if st.session_state["ending"]:
        st.error("ФИНАЛ")
        st.markdown(st.session_state["ending"])
        st.info("Нажми **Новая игра / Сброс мира** в сайдбаре, чтобы сыграть ещё раз.")

    # -----------------------------
    # Main dialogue view + Separate log window
    # -----------------------------
    st.markdown("### Диалог")

    # Keep main screen clean: show last N messages only
    main_keep = st.slider(
        "Сколько сообщений держать на главном экране",
        min_value=10,
        max_value=120,
        value=40,
        step=10,
        help="Это «витрина» текущей сцены. Полная история — в журнале ниже.",
        key="main_keep_slider",
    )

    if not w.log:
        st.info("Пока пусто. Выбери действие снизу.")
    else:
        for m in w.log[-main_keep:]:
            with st.chat_message(ROLE_TO_CHAT[m.role]):
                st.markdown(f"{ROLE_PREFIX[m.role]}\n\n{m.content}")

    # Separate "window" for full log (popover if available, else expander)
    def render_log_window():
        st.caption("Полный журнал: удобно листать, не перегружая сцену.")
        log_keep = st.slider(
            "Сколько последних сообщений показать в журнале",
            min_value=50,
            max_value=max(50, len(w.log)),
            value=min(300, len(w.log)) if len(w.log) > 0 else 50,
            step=50,
            key="log_keep_slider",
        )
        log_container = st.container(height=420)
        with log_container:
            if not w.log:
                st.write("Журнал пуст.")
            else:
                for m in w.log[-log_keep:]:
                    st.markdown(f"{ROLE_PREFIX[m.role]}\n\n{m.content}")
                    st.divider()

    try:
        with st.popover("📜 Журнал событий"):
            render_log_window()
    except Exception:
        with st.expander("📜 Журнал событий"):
            render_log_window()

    # -----------------------------
    # Choice panel (kept intact)
    # -----------------------------
    st.markdown('<div class="choice-wrap">', unsafe_allow_html=True)
    st.markdown("### Выбор реплики / действия")

    disabled = bool(st.session_state["ending"]) or (w.day > w.max_days)

    options = ["investigate", "support_temple", "support_mages", "support_merchants", "spread_rumour", "bribe", "noop"]
    choice = st.radio(
        "",
        options=options,
        format_func=lambda k: PLAYER_ACTIONS_RU[k]["title"],
        disabled=disabled,
        label_visibility="collapsed",
        key="choice_radio",
    )
    st.caption(PLAYER_ACTIONS_RU[choice]["desc"])

    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("Сказать/Сделать это", type="primary", use_container_width=True, disabled=disabled):
            ending = step_world(w, choice)
            if ending:
                st.session_state["ending"] = ending

            if w.day > w.max_days and not st.session_state["ending"]:
                st.session_state["ending"] = check_ending(w) or (
                    "**Патовая неделя.**\n\nНикто не получил решающего преимущества. "
                    "Город выжил — и это уже событие. Но узлы затянуты, а не развязаны."
                )
            st.rerun()

    with c2:
        if st.button("Пропустить ход", use_container_width=True, disabled=disabled):
            ending = step_world(w, "noop")
            if ending:
                st.session_state["ending"] = ending

            if w.day > w.max_days and not st.session_state["ending"]:
                st.session_state["ending"] = check_ending(w) or (
                    "**Патовая неделя.**\n\nНикто не получил решающего преимущества. "
                    "Город выжил — и это уже событие. Но узлы затянуты, а не развязаны."
                )
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)
