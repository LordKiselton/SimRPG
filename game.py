# game.py
# MVP: "Стабилизировать город" — главный win condition.
#
# Run:
#   pip install streamlit pandas
#   streamlit run game.py
#
# Optional factions.csv рядом с game.py:
# name,power,stability,radicalization,resources
# Merchants,60,70,20,75
# Temple,55,65,40,55
# Mages,45,50,30,50
# Lodge,30,60,20,40
# Council,35,50,25,45

from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Literal, Tuple

import pandas as pd
import streamlit as st


# -----------------------------
# Data model
# -----------------------------

Role = Literal["narrator", "player", "world", "system"]

ROLE_TO_CHAT = {
    "narrator": "assistant",
    "world": "assistant",
    "system": "assistant",
    "player": "user",
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

    # City pressures
    economic_stress: int = 40
    public_fear: int = 30
    magical_tension: int = 50  # social/political conflict around magic (NOT "safety")

    # Narrative track (lightweight, still helps cohesion)
    ship_progress: int = 0  # 0..4
    ship_target: int = 4
    ship_suspect: str = "unknown"  # lodge/mages/merchants/accident (hidden truth, used for flavor/rare effects)
    ship_revealed: bool = False

    factions: Dict[str, Faction] = field(default_factory=dict)
    log: List[Message] = field(default_factory=list)

    # Buffer: to produce 1 narrator reply per turn
    buffer_mode: bool = False
    _buffer: List[str] = field(default_factory=list)

    def rng(self) -> random.Random:
        # deterministic per day
        return random.Random(self.seed + self.day * 999)

    def clamp(self):
        self.economic_stress = int(max(0, min(100, self.economic_stress)))
        self.public_fear = int(max(0, min(100, self.public_fear)))
        self.magical_tension = int(max(0, min(100, self.magical_tension)))
        self.ship_progress = int(max(0, min(self.ship_target, self.ship_progress)))
        for f in self.factions.values():
            f.clamp()

    def push(self, role: Role, text: str):
        if self.buffer_mode:
            self._buffer.append(text)
        else:
            self.log.append(Message(role=role, content=text))

    def buffer_start(self):
        self.buffer_mode = True
        self._buffer = []

    def buffer_end(self) -> List[str]:
        self.buffer_mode = False
        buf = self._buffer[:]
        self._buffer = []
        return buf


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
    7: "День седьмой — «Проверка на прочность»",
}


def day_title(d: int) -> str:
    return DAY_NAME.get(d, f"День {d}")


# -----------------------------
# Win condition (primary)
# -----------------------------

STABLE_THRESH_ECON = 55
STABLE_THRESH_FEAR = 55
STABLE_THRESH_MAGIC = 60  # conflict around magic, keep moderate

def stability_score(w: World) -> int:
    # higher is better; 0..100-ish
    # penalize overshoots
    score = 100
    score -= max(0, w.economic_stress - STABLE_THRESH_ECON) * 2
    score -= max(0, w.public_fear - STABLE_THRESH_FEAR) * 2
    score -= max(0, w.magical_tension - STABLE_THRESH_MAGIC) * 2
    return int(max(0, min(100, score)))

def stable_today(w: World) -> bool:
    return (
        w.economic_stress <= STABLE_THRESH_ECON
        and w.public_fear <= STABLE_THRESH_FEAR
        and w.magical_tension <= STABLE_THRESH_MAGIC
    )


# -----------------------------
# Intents & dynamics
# -----------------------------

def compute_effective_power(f: Faction) -> int:
    return int((f.resources * 0.5 + f.power * 0.5) * (0.5 + f.stability / 200.0))

def leader_faction(w: World) -> Tuple[str, int]:
    best = ("", -1)
    for f in w.factions.values():
        p = compute_effective_power(f)
        if p > best[1]:
            best = (f.name, p)
    return best

def faction_intent(w: World, f: Faction) -> str:
    # Intents tuned to "city pressure" logic
    if w.economic_stress > 70 and f.name == "Merchants":
        return "law"
    if w.public_fear > 70 and f.name in ("Temple", "Lodge"):
        return "sabotage"
    if f.stability < 35 and f.name == "Mages":
        return "aid"
    if w.magical_tension > 70 and f.name == "Temple":
        return "propaganda"
    return "propaganda"

def intent_title_ru(intent: str) -> str:
    return {
        "law": "двигает решения",
        "propaganda": "раскачивает мнение",
        "aid": "успокаивает своих",
        "sabotage": "подливает масла",
    }.get(intent, "выжидает")

def intent_reason_ru(w: World, f: Faction, intent: str) -> str:
    if intent == "law" and f.name == "Merchants":
        return f"рынок перегрет ({w.economic_stress})"
    if intent == "sabotage":
        return f"страх на улицах высокий ({w.public_fear})"
    if intent == "aid" and f.name == "Mages":
        return f"их порядок шатается ({f.stability})"
    if intent == "propaganda" and f.name == "Temple" and w.magical_tension > 70:
        return f"конфликт вокруг магии растёт ({w.magical_tension})"
    if intent == "propaganda":
        return "борьба за влияние"
    return "контекст слабый"


# -----------------------------
# Player action modes (simplified UI)
# -----------------------------

MODE_LIST = ["Стабилизация", "Влияние", "Тайные меры", "Ожидание", "Расследование (корабль)"]

MODE_DESC = {
    "Стабилизация": "Быстрые меры по городу: цены, патрули, переговоры. Сильнее всего влияет на 3 показателя давления.",
    "Влияние": "Открытая работа с выбранной фракцией: поддержка или давление (в пределах городской легитимности).",
    "Тайные меры": "Подкуп или слухи против выбранной фракции. Дает контроль, но повышает риск деградации атмосферы.",
    "Ожидание": "Ничего не делать. Город и фракции сыграют без тебя.",
    "Расследование (корабль)": "Двигает сюжет и дает редкие рычаги: снижает страх и может открыть спец-меру.",
}

SECRET_OPS = ["Подкупить", "Пустить слухи"]
INFLUENCE_OPS = ["Поддержать", "Надавить"]

def faction_choices(w: World) -> List[str]:
    # show as RU names but keep mapping
    return list(w.factions.keys())


# -----------------------------
# Effects: player actions
# -----------------------------

def apply_player_mode(w: World, mode: str, target: Optional[str], subop: Optional[str]) -> str:
    rng = w.rng()

    if mode == "Ожидание":
        w.public_fear += 1
        return "Ты отступаешь на шаг и смотришь, как город сам выбирает траекторию. Пустоту мгновенно заполняют чужие решения."

    if mode == "Стабилизация":
        # Directly targets pressures, mild political tradeoffs
        # Choose a "package" based on current biggest problem (auto, no UI)
        pressures = [("экономика", w.economic_stress), ("страх", w.public_fear), ("магия", w.magical_tension)]
        pressures.sort(key=lambda x: x[1], reverse=True)
        top = pressures[0][0]

        if top == "экономика":
            w.economic_stress -= 10
            w.public_fear -= 2
            if "Merchants" in w.factions:
                w.factions["Merchants"].resources -= 3  # concessions
                w.factions["Merchants"].power -= 1
            return ("Ты вводишь временные меры: коридор цен, приоритетные поставки, контроль на пристанях. "
                    "Рынок выдыхает, а люди впервые за дни говорят не только о голоде.")
        if top == "страх":
            w.public_fear -= 10
            w.economic_stress -= 2
            if "Council" in w.factions:
                w.factions["Council"].power += 2
            return ("Ты усиливаешь патрули и проводишь публичные переговоры с лидерами кварталов. "
                    "Толпа перестаёт быть зверем — хотя бы на ночь.")
        # magic conflict
        w.magical_tension -= 10
        w.public_fear -= 2
        if "Temple" in w.factions:
            w.factions["Temple"].radicalization -= 2
        if "Mages" in w.factions:
            w.factions["Mages"].stability += 2
        return ("Ты собираешь Храм и Круг за одним столом, заставляя их говорить языком правил, а не обвинений. "
                "Конфликт вокруг магии отступает, но осадок в речах остаётся.")

    if mode == "Влияние":
        if not target or target not in w.factions:
            return "Ты пытаешься давить на воздух — но у города нет адресата."
        f = w.factions[target]
        if subop == "Поддержать":
            # Support helps their stability/power, but also shifts pressures depending on faction
            f.power += 5
            f.stability += 3
            f.rel_player += 4

            if target == "Temple":
                # Better: Temple support reduces fear (order), increases magic conflict (rhetoric)
                w.public_fear -= 3
                w.magical_tension += 4
                f.radicalization += 2
                return ("Ты выходишь рядом с пламенными знаменами: обещаешь порядок и ясные запреты. "
                        "Люди чувствуют опору — но спор о магии становится громче.")
            if target == "Mages":
                w.magical_tension -= 3
                w.public_fear -= 1
                return ("Ты защищаешь Круг от истерии и требуешь процедур вместо казней. "
                        "В воздухе меньше злобы — но город внимательно смотрит на каждый новый ритуал.")
            if target == "Merchants":
                w.economic_stress -= 3
                w.public_fear -= 1
                return ("Ты легализуешь быстрые сделки и даёшь гильдии коридор для действий. "
                        "Прилавки оживают — но кто-то шепчет, что город продают по частям.")
            if target == "Council":
                w.public_fear -= 2
                w.economic_stress -= 1
                return ("Ты усиливаешь легитимность Совета: открытые заседания, отчёты, ответственность. "
                        "Люди меньше боятся неизвестного.")
            if target == "Lodge":
                w.public_fear += 3
                w.economic_stress += 1
                return ("Ты играешь с тенью — и тень отвечает. Связи открываются, но на улицах становится тревожнее.")
            return "Ты выбираешь сторону — и город делает пометку напротив твоего имени."

        # Pressure / crackdown
        if subop == "Надавить":
            # Pressure reduces power, increases instability; can reduce some pressures if applied to right faction
            f.power -= 5
            f.stability -= 3
            f.rel_player -= 4
            w.public_fear += 1  # конфликтность

            if target == "Lodge":
                w.public_fear -= 4  # cutting fear network
                return ("Ты прижимаешь тех, кто любит шептать в темноте: облавы, аресты посредников, контроль таверн. "
                        "Улицы выдыхают — но Ложа запоминает такие ходы.")
            if target == "Merchants":
                w.economic_stress += 2  # рынок обижается
                return ("Ты давишь на гильдию: проверки, тарифы, показательные штрафы. "
                        "Люди радуются справедливости — но рынок реагирует сухо и больно.")
            if target == "Temple":
                w.magical_tension -= 2  # меньше риторики
                return ("Ты ограничиваешь пламенные проповеди и требуешь умеренности. "
                        "Спор о магии становится тише — зато на площади появляется холодный гнев.")
            if target == "Mages":
                w.magical_tension += 2
                return ("Ты заставляешь Круг жить по новым правилам и отчётности. "
                        "Город чувствует контроль — но маги воспринимают это как унижение.")
            if target == "Council":
                w.public_fear += 2
                return ("Ты демонстративно принижаешь Совет, снимая с него полномочия. "
                        "Люди мгновенно чувствуют вакуум власти.")
            return "Ты нажимаешь сильнее — и слышишь, как трещит чья-то опора."

    if mode == "Тайные меры":
        if not target or target not in w.factions or not subop:
            return "Тайные меры требуют адресата и способа."
        f = w.factions[target]

        if subop == "Подкупить":
            f.rel_player += 10
            f.resources -= 4
            w.public_fear += 1  # коррупционный фон
            return ("Ты платишь аккуратно: без свидетелей и лишних слов. "
                    "Двери открываются быстрее — но город начинает пахнуть деньгами, а не законом.")

        if subop == "Пустить слухи":
            f.power -= 6
            f.stability -= 2
            w.public_fear += 3
            return ("Ты запускаешь шёпот ровно туда, где он превращается в уверенность. "
                    "Чужое влияние трескается — но страх на улицах растёт.")

    if mode == "Расследование (корабль)":
        # Guaranteed progress so it's never "wasted"
        w.ship_progress += 1
        w.public_fear -= 3  # people feel someone is working
        # Rare targeted consequence based on hidden truth — small, not required for win condition
        if w.ship_progress >= w.ship_target:
            w.ship_revealed = True
        if w.ship_suspect == "lodge" and "Lodge" in w.factions:
            w.factions["Lodge"].stability -= 2
        elif w.ship_suspect == "mages" and "Mages" in w.factions:
            w.magical_tension += 2
        elif w.ship_suspect == "merchants" and "Merchants" in w.factions:
            w.factions["Merchants"].resources -= 2
        else:
            w.economic_stress -= 1

        # A small "special lever" unlocked mid-track: once per run, investigation can give a stabilizing bonus
        if w.ship_progress == 2:
            w.economic_stress -= 2
            return ("Ты находишь связку документов по маршрутам и складским ключам. "
                    "Это не раскрывает виновника, но снимает часть напряжения на рынке. По городу проходит тихий выдох.")
        if w.ship_progress == 4:
            return ("Точки сходятся. Карта ветров, подписи, ночные свидетели — теперь у тебя есть цельная версия. "
                    "Главное — удержать город от срыва, пока правда не превратится в новую искру.")
        return ("Ты собираешь показания и сверяешь следы: меньше пафоса, больше фактов. "
                "Когда кто-то работает, паника уходит в тень.")

    return "Ты делаешь шаг — и город отвечает."


# -----------------------------
# Effects: factions & escalations
# -----------------------------

def apply_faction_action(w: World, actor: Faction, intent: str) -> str:
    rng = w.rng()
    others = [x for x in w.factions.values() if x.name != actor.name]
    target = rng.choice(others) if others else None

    if intent == "propaganda":
        delta = rng.randint(2, 6)
        actor.power += delta
        actor.radicalization += 1

        if actor.name == "Temple":
            # Temple propaganda increases social conflict about magic
            w.magical_tension += 2
            w.public_fear += 1
            return f"{fr(actor.name)} раздувает спор о магии и порядке."
        if actor.name == "Lodge":
            w.public_fear += 2
            return f"{fr(actor.name)} подкармливает тревогу тихими слухами."
        if actor.name == "Merchants":
            w.economic_stress -= 1
            return f"{fr(actor.name)} обещает поставки и стабильные цены."
        if actor.name == "Council":
            w.public_fear -= 1
            return f"{fr(actor.name)} показывает людям процесс и ответственность."
        if actor.name == "Mages":
            w.magical_tension -= 1
            return f"{fr(actor.name)} выступает за протоколы и безопасность ритуалов."
        return f"{fr(actor.name)} работает на своё влияние."

    if intent == "sabotage" and target:
        dmg = rng.randint(3, 7)
        target.stability -= dmg
        w.public_fear += 3
        w.economic_stress += 1
        actor.power += 1  # fear feeds manipulators
        return f"Кто-то бьёт по слабым местам {fr(target.name)} — и город вздрагивает."

    if intent == "aid":
        actor.stability += 7
        actor.resources -= 2
        w.magical_tension -= 1 if actor.name == "Mages" else 0
        return f"{fr(actor.name)} тушит внутренние пожары."

    if intent == "law":
        # market emergency response
        if actor.name == "Merchants":
            w.economic_stress -= 6
            actor.power += 2
            actor.resources -= 1
            return f"{fr(actor.name)} вводит новые маршруты и режим снабжения."
        w.public_fear -= 1
        return f"{fr(actor.name)} проводит успокоительные меры."

    return f"{fr(actor.name)} выжидает."


def system_escalations(w: World) -> List[str]:
    """
    IMPORTANT CHANGE:
    Magical accident is about *unsafe magic under stress*, not merely 'conflict around magic'.
    So it depends on:
      - magical_tension high (society heated)
      - Mages stability low (unsafe conditions)
      - and Temple power LOW (less 'control') OR fear high (mob pressure)
    """
    out: List[str] = []
    rng = w.rng()

    mages = w.factions.get("Mages")
    temple = w.factions.get("Temple")

    # Magical accident risk (more coherent)
    if mages:
        control_factor = 0
        if temple:
            control_factor = max(0, 60 - temple.power)  # stronger Temple -> more control -> lower risk
        risk = 0
        if w.magical_tension > 72:
            risk += (w.magical_tension - 72)
        if mages.stability < 45:
            risk += (45 - mages.stability) * 2
        if w.public_fear > 70:
            risk += (w.public_fear - 70)
        risk += control_factor // 3

        # convert risk to chance
        chance = min(0.55, max(0.0, risk / 180.0))
        if chance > 0 and rng.random() < chance:
            out.append("Над доками срывается ритуал: искры режут туман, металл воет, люди разбегаются. "
                       "Это не ‘магия плоха’, это **магия под давлением**.")
            w.public_fear += 8
            w.economic_stress += 6
            mages.stability -= 8
            mages.power -= 4

    # Riot risk (unchanged idea, clearer impact)
    if w.public_fear > 82 and rng.random() < 0.30:
        out.append("Толпа рвёт витрины и цепляется за стражу. Ночь проходит в криках — утром город платит по счетам.")
        w.economic_stress += 9
        w.public_fear += 3
        if "Council" in w.factions:
            w.factions["Council"].power -= 4
        if "Temple" in w.factions:
            w.factions["Temple"].power += 2

    # Story beats about the ship so it doesn't vanish
    if w.day in (2, 4, 6):
        if w.ship_progress >= 1:
            out.append("По делу корабля: кто-то ‘случайно’ путается в показаниях. Значит, нервы настоящие.")
        else:
            out.append("По делу корабля: на пристанях снова спорят о виновнике — без фактов страх всегда громче.")

    return out


# -----------------------------
# Endings: stabilization is primary
# -----------------------------

def ending_text(w: World) -> str:
    # Primary win
    if stable_today(w) and w.day > w.max_days:
        return ("**ПОБЕДА: город удержан.**\n\n"
                "Неделя прошла без окончательного срыва. Рынок не рухнул, толпа не стала зверем, спор о магии не взорвал доки. "
                "Нерисса запомнит эту неделю как ‘пепельную’ — но не как ‘похоронную’.\n\n"
                f"**Итоговая устойчивость:** {stability_score(w)}/100.")

    # If not stable: describe dominant failure
    if w.public_fear > 80:
        return ("**ПОРАЖЕНИЕ: город сорвался в страх.**\n\n"
                "Паника победила институты. Когда люди боятся, они ищут не решение, а врага — и находят его.")
    if w.economic_stress > 75:
        return ("**ПОРАЖЕНИЕ: рынок сломался.**\n\n"
                "Цены и дефицит победили обещания. Голод — самый быстрый политический аргумент.")
    if w.magical_tension > 80:
        return ("**ПОРАЖЕНИЕ: конфликт вокруг магии стал точкой разлома.**\n\n"
                "Даже без катастрофы город начал жить в режиме ‘мы и они’. А это всегда дороже любой аварии.")
    return ("**НЕУДАЧА: неделя прошла на грани.**\n\n"
            "Решающих провалов не случилось, но и стабилизации нет. В Нериссе всё ещё слишком много пороха.")


# -----------------------------
# Compact turn narration (1 choice -> 1 narrator reply)
# -----------------------------

def snapshot_world(w: World) -> dict:
    return {
        "day": w.day,
        "economic_stress": w.economic_stress,
        "public_fear": w.public_fear,
        "magical_tension": w.magical_tension,
        "ship_progress": w.ship_progress,
        "factions": {
            name: {
                "power": f.power,
                "stability": f.stability,
                "radicalization": f.radicalization,
                "resources": f.resources,
                "rel_player": f.rel_player,
            }
            for name, f in w.factions.items()
        }
    }

def fmt_delta(x: int) -> str:
    return f"+{x}" if x > 0 else str(x)

def top_faction_changes(before: dict, after: dict, top_n: int = 2):
    changes = []
    for name, b in before["factions"].items():
        a = after["factions"].get(name)
        if not a:
            continue
        score = (
            abs(a["power"] - b["power"]) +
            abs(a["stability"] - b["stability"]) +
            abs(a["resources"] - b["resources"]) +
            abs(a["radicalization"] - b["radicalization"]) +
            abs(a["rel_player"] - b["rel_player"])
        )
        if score > 0:
            changes.append((score, name, b, a))
    changes.sort(reverse=True, key=lambda t: t[0])
    return changes[:top_n]

def narrate_summary(before: dict, after: dict) -> Tuple[str, str, str]:
    ge = after["economic_stress"] - before["economic_stress"]
    gf = after["public_fear"] - before["public_fear"]
    gm = after["magical_tension"] - before["magical_tension"]
    delta_line = f"**Итог:** Экономика {fmt_delta(ge)}, Страх {fmt_delta(gf)}, Спор о магии {fmt_delta(gm)}."
    stable = f"**Устойчивость:** {stability_score_from_snapshot(after)}/100. (Цель: удержать все давления ниже порогов к концу недели.)"
    faction_line = ""
    top = top_faction_changes(before, after, 2)
    if top:
        bits = []
        for _, name, b, a in top:
            d = a["power"] - b["power"]
            if d != 0:
                bits.append(f"{fr(name)} влияние {fmt_delta(d)}")
        faction_line = ("**Сдвиги сил:** " + ", ".join(bits) + ".") if bits else ""
    return delta_line, faction_line, stable

def stability_score_from_snapshot(snap: dict) -> int:
    # reuse score formula without world instance
    score = 100
    score -= max(0, snap["economic_stress"] - STABLE_THRESH_ECON) * 2
    score -= max(0, snap["public_fear"] - STABLE_THRESH_FEAR) * 2
    score -= max(0, snap["magical_tension"] - STABLE_THRESH_MAGIC) * 2
    return int(max(0, min(100, score)))

def step_world_compact(w: World, player_text: str, mode: str, target: Optional[str], subop: Optional[str]) -> Tuple[Optional[str], List[str]]:
    before = snapshot_world(w)

    w.buffer_start()

    # 1) Player action consequence (buffered)
    w.push("world", apply_player_mode(w, mode, target, subop))

    # 2) Factions act (buffered)
    for f in list(w.factions.values()):
        intent = faction_intent(w, f)
        w.push("world", apply_faction_action(w, f, intent))

    # 3) System escalations (buffered)
    for e in system_escalations(w):
        w.push("world", e)

    # 4) Gentle drift (tuned to stabilization)
    # If economy is high, fear tends to rise. If fear is high, economy also worsens.
    if w.economic_stress > 65:
        w.public_fear += 1
    else:
        w.public_fear -= 1
    if w.public_fear > 75:
        w.economic_stress += 1

    # conflict around magic: if Temple dominates Mages too hard, conflict rises
    if "Temple" in w.factions and "Mages" in w.factions:
        if w.factions["Temple"].power > w.factions["Mages"].power + 25:
            w.magical_tension += 1
        else:
            w.magical_tension -= 1

    w.clamp()

    # Day advances
    w.day += 1

    after = snapshot_world(w)
    buffered = w.buffer_end()

    # Compose 1 narrator reply
    # Choose 1-2 strongest beats (prioritize ship line, disasters)
    hi_kw = ["По делу корабля:", "ритуал", "Толпа", "сорвался", "вспых", "маяк", "облав", "поставк", "переговор"]
    scored = []
    for i, t in enumerate(buffered):
        score = 0
        for kw in hi_kw:
            if kw.lower() in t.lower():
                score += 3
        # prefer shorter beats
        score += max(0, 2 - (len(t) // 260))
        scored.append((score, i, t))
    scored.sort(reverse=True, key=lambda x: x[0])

    beats = []
    for score, i, t in scored[:4]:
        if score <= 0:
            continue
        beats.append(t)
    if not beats:
        beats = buffered[:2] if buffered else ["Город отвечает без слов — переменой воздуха и настроения."]

    delta_line, faction_line, stable_line = narrate_summary(before, after)

    # Simple "risk" line
    risks = []
    if after["economic_stress"] > STABLE_THRESH_ECON:
        risks.append("рынок")
    if after["public_fear"] > STABLE_THRESH_FEAR:
        risks.append("страх")
    if after["magical_tension"] > STABLE_THRESH_MAGIC:
        risks.append("конфликт магии")
    risk_line = f"_Риски выше порога_: **{', '.join(risks)}**." if risks else "_Все давления ниже порогов: город выглядит управляемым._"

    narrator = (
        f"**{day_title(before['day'])}**\n\n"
        + "\n\n".join(beats[:2]).strip()
        + "\n\n"
        + delta_line
        + ("\n\n" + faction_line if faction_line else "")
        + "\n\n"
        + stable_line
        + "\n\n"
        + risk_line
    ).strip()

    w.push("narrator", narrator)

    # Determine ending if episode is over
    ending = None
    if w.day > w.max_days:
        ending = ending_text(w)

    # Debug lines for expander
    debug_lines = buffered

    return ending, debug_lines


# -----------------------------
# Init
# -----------------------------

def init_world_from_df(df: pd.DataFrame, seed: int, max_days: int) -> World:
    w = World(seed=seed, max_days=max_days)
    w.factions = df_to_factions(df)

    r = random.Random(seed)
    w.ship_suspect = r.choices(
        ["lodge", "mages", "merchants", "accident"],
        weights=[30, 30, 20, 20],
        k=1
    )[0]

    w.log = []
    w.day = 1

    w.economic_stress = 40
    w.public_fear = 30
    w.magical_tension = 50

    # Opening
    w.push(
        "narrator",
        f"**{day_title(1)}**\n\n"
        "В гавани Нериссы пропадает корабль с *астральным углём*. "
        "Это не просто груз: это тепло мастерских, ход портовых механизмов и спокойствие рынка.\n\n"
        "**Цель недели:** удержать город в управляемом состоянии — без голода, без толпы и без взрыва конфликта вокруг магии."
    )

    # Initial shock
    w.economic_stress += 18
    w.public_fear += 12
    if "Mages" in w.factions:
        w.factions["Mages"].stability -= 6
    w.clamp()
    return w


# -----------------------------
# UI
# -----------------------------

st.set_page_config(page_title="Нерисса: стабилизация города", layout="wide")

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
.chat-feed {
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px;
  padding: 6px;
  background: rgba(255,255,255,0.01);
}
.preview-card {
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 14px;
  padding: 10px 12px;
  margin-top: 8px;
  background: rgba(255,255,255,0.02);
}
</style>
""", unsafe_allow_html=True)

st.title("Нерисса — Неделя стабилизации (MVP)")
st.caption("Упрощённый UI: выбираешь **режим** → (иногда) **цель** → получаешь **один** ответ Хроникёра. Глубина — внутри систем.")

with st.sidebar:
    st.header("Сессия")
    seed = st.number_input("Seed (для повторяемости)", min_value=1, max_value=999999, value=42, step=1)
    max_days = st.slider("Длительность эпизода (дней)", min_value=3, max_value=14, value=7, step=1)

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
    st.subheader("Таблица фракций")
    st.caption("Правки применятся после **Новая игра**.")

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
    if st.button("Новая игра", type="primary"):
        df = st.session_state.get("factions_df", load_factions_df())
        st.session_state["world"] = init_world_from_df(df, seed=seed, max_days=max_days)
        st.session_state["ending"] = None
        st.session_state["debug_last_turn"] = []
        st.toast("Мир перезапущен", icon="🌍")


if "world" not in st.session_state:
    df0 = st.session_state.get("factions_df", load_factions_df())
    st.session_state["world"] = init_world_from_df(df0, seed=seed, max_days=max_days)

if "ending" not in st.session_state:
    st.session_state["ending"] = None

if "debug_last_turn" not in st.session_state:
    st.session_state["debug_last_turn"] = []

w: World = st.session_state["world"]

chat_col, hud_col = st.columns([0.70, 0.30], gap="large")

with hud_col:
    st.markdown('<div class="hud-card">', unsafe_allow_html=True)
    st.markdown('<div class="hud-title">Давления города</div>', unsafe_allow_html=True)
    st.metric("Экономика (≤55)", w.economic_stress)
    st.metric("Страх (≤55)", w.public_fear)
    st.metric("Спор о магии (≤60)", w.magical_tension)
    st.markdown(f"<div class='hud-small'><b>Устойчивость:</b> {stability_score(w)}/100</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='hud-small'><b>Корабль:</b> улики {w.ship_progress}/{w.ship_target}</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    lf, lp = leader_faction(w)
    st.markdown('<div class="hud-card">', unsafe_allow_html=True)
    st.markdown('<div class="hud-title">Баланс сил</div>', unsafe_allow_html=True)
    st.markdown(f"- **Сейчас сильнее всех:** {fr(lf)}")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="hud-card">', unsafe_allow_html=True)
    st.markdown('<div class="hud-title">Прогноз намерений</div>', unsafe_allow_html=True)
    for f in w.factions.values():
        intent = faction_intent(w, f)
        st.markdown(f"- **{fr(f.name)}**: _{intent_title_ru(intent)}_ — {intent_reason_ru(w, f, intent)}")
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
            "к_тебе": f.rel_player,
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("Подробности последнего хода (отладка)"):
        if not st.session_state["debug_last_turn"]:
            st.caption("Пока пусто.")
        else:
            for line in st.session_state["debug_last_turn"]:
                st.markdown(line)
                st.divider()

with chat_col:
    st.subheader(f"Сцена: день {w.day}/{w.max_days}")

    if st.session_state["ending"]:
        st.error("ИТОГ")
        st.markdown(st.session_state["ending"])
        st.info("Нажми **Новая игра** в сайдбаре, чтобы сыграть ещё раз.")

    # Chat feed controls
    cA, cB, cC = st.columns([1, 1, 1])
    with cA:
        chat_height = st.slider("Высота ленты", 350, 900, 650, 50, key="chat_height")
    with cB:
        render_last = st.slider("Сообщений в ленте", 20, 200, 80, 10, key="render_last")
    with cC:
        if st.button("⬇️ Вниз", use_container_width=True):
            st.rerun()

    feed = st.container(height=chat_height)
    with feed:
        st.markdown('<div class="chat-feed">', unsafe_allow_html=True)
        msgs = w.log[-render_last:] if w.log else []
        if not msgs:
            st.info("Пока пусто. Выбери действие ниже.")
        else:
            for m in msgs:
                with st.chat_message(ROLE_TO_CHAT[m.role]):
                    st.markdown(f"{ROLE_PREFIX[m.role]}\n\n{m.content}")
        st.markdown("</div>", unsafe_allow_html=True)

    # ACTION PANEL (simplified)
    st.markdown("### Ход")
    disabled = bool(st.session_state["ending"]) or (w.day > w.max_days)

    mode = st.radio("Режим", MODE_LIST, index=0, horizontal=True, disabled=disabled)
    st.caption(MODE_DESC.get(mode, ""))

    target = None
    subop = None

    needs_target = mode in ("Влияние", "Тайные меры")
    if needs_target:
        # Show target selector only when relevant
        target = st.radio("Цель", faction_choices(w), format_func=lambda k: fr(k), horizontal=True, disabled=disabled)

    if mode == "Влияние":
        subop = st.radio("Действие", INFLUENCE_OPS, horizontal=True, disabled=disabled)
    elif mode == "Тайные меры":
        subop = st.radio("Действие", SECRET_OPS, horizontal=True, disabled=disabled)

    # Preview (compact)
    st.markdown('<div class="preview-card">', unsafe_allow_html=True)
    if mode == "Стабилизация":
        st.markdown("**Превью:** сильнее всего снижает самое ‘горящее’ давление (экономика/страх/спор о магии).")
    elif mode == "Влияние":
        st.markdown("**Превью:** усиливаешь/ослабляешь выбранную фракцию и получаешь побочные эффекты на давления города.")
    elif mode == "Тайные меры":
        st.markdown("**Превью:** даёт быстрый контроль над влиянием/лояльностью, но чаще повышает страх (коррупционный/панический фон).")
    elif mode == "Расследование (корабль)":
        st.markdown("**Превью:** улики +1 (гарантированно), страх −3. Сюжетные биты всплывают чаще.")
    else:
        st.markdown("**Превью:** город сыграет сам, риски могут тихо подрасти.")
    st.markdown("</div>", unsafe_allow_html=True)

    b1, b2 = st.columns([1, 1])

    def apply_turn():
        # Player line (keep, CRPG feel)
        player_line = f"{mode}" + (f" → {fr(target)}" if target else "") + (f" ({subop})" if subop else "")
        w.push("player", player_line)

        ending, debug_lines = step_world_compact(w, player_line, mode, target, subop)
        st.session_state["debug_last_turn"] = debug_lines

        if ending:
            st.session_state["ending"] = ending

    with b1:
        if st.button("Сделать ход", type="primary", use_container_width=True, disabled=disabled):
            apply_turn()
            st.rerun()

    with b2:
        if st.button("Быстрый ход: Стабилизация", use_container_width=True, disabled=disabled):
            mode_fast = "Стабилизация"
            w.push("player", mode_fast)
            ending, debug_lines = step_world_compact(w, mode_fast, mode_fast, None, None)
            st.session_state["debug_last_turn"] = debug_lines
            if ending:
                st.session_state["ending"] = ending
            st.rerun()
