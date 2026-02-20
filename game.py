# majesty_game.py
# Streamlit Majesty-like procedural kingdom crisis prototype (7 days).
#
# Run:
#   pip install streamlit pandas
#   streamlit run majesty_game.py
#
# What you get:
# - 1 day = 1 "весть" от колоритного NPC + 2–3 решения
# - 1 выбор игрока -> 1 ответ Хроникёра (ироничный фэнтези / лёгкий dark fantasy)
# - процедурность: события выбираются по триггерам/весам из состояния
# - цель: НЕ допустить упадка государства (к концу 7 дня обязательно будет финальный стейт)
# - простая аналитика: JSONL лог в ./analytics/<session_id>.jsonl

from __future__ import annotations

import os
import json
import uuid
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Literal

import streamlit as st


# -----------------------------
# UI roles
# -----------------------------
Role = Literal["narrator", "player", "npc"]

ROLE_TO_CHAT = {
    "narrator": "assistant",
    "npc": "assistant",
    "player": "user",
}
ROLE_PREFIX = {
    "narrator": "🕯️ **Хроникёр**",
    "npc": "👤 **Весть**",
    "player": "👑 **Король/Королева**",
}


# -----------------------------
# State model
# -----------------------------
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

    treasury: int = 55      # Казна
    order: int = 55         # Порядок
    health: int = 55        # Здоровье народа
    nobles: int = 55        # Лояльность знати
    faith: int = 55         # Вера/единство
    border: int = 55        # Граница/угрозы

    decay: int = 0          # Упадок (главный fail-meter)
    doom: int = 0           # Накопитель "неизбежности финала" (гарантия стейта к 7 дню)

    tags: List[Tag] = field(default_factory=list)     # временные модификаторы
    log: List[Message] = field(default_factory=list)

    current_event_id: Optional[str] = None
    current_event: Optional[dict] = None

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    # buffering to avoid spam in chat
    buffer_mode: bool = False
    _buffer: List[str] = field(default_factory=list)

    def rng(self) -> random.Random:
        # deterministic per day
        return random.Random(self.seed + self.day * 1337)

    def clamp(self):
        for k in ("treasury", "order", "health", "nobles", "faith", "border"):
            v = getattr(self, k)
            setattr(self, k, int(max(0, min(100, v))))
        self.decay = int(max(0, min(10, self.decay)))
        self.doom = int(max(0, min(20, self.doom)))

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
        out = self._buffer[:]
        self._buffer = []
        return out

    def add_tag(self, name: str, days: int):
        # refresh if exists
        for t in self.tags:
            if t.name == name:
                t.days_left = max(t.days_left, days)
                return
        self.tags.append(Tag(name=name, days_left=days))

    def has_tag(self, name: str) -> bool:
        return any(t.name == name and t.days_left > 0 for t in self.tags)

    def tick_tags(self):
        for t in self.tags:
            t.days_left -= 1
        self.tags = [t for t in self.tags if t.days_left > 0]


# -----------------------------
# Zones / scoring
# -----------------------------
GREEN = 60
YELLOW = 40

def zone(v: int) -> str:
    if v >= GREEN:
        return "🟢"
    if v >= YELLOW:
        return "🟡"
    return "🔴"

def stable_state(k: Kingdom) -> bool:
    # stable if all non-red and decay low
    reds = sum(1 for v in (k.treasury, k.order, k.health, k.nobles, k.faith, k.border) if v < YELLOW)
    return (reds == 0) and (k.decay <= 2)

def stability_score(k: Kingdom) -> int:
    # 0..100-ish
    vals = [k.treasury, k.order, k.health, k.nobles, k.faith, k.border]
    base = sum(vals) // len(vals)
    # penalize red zones
    penalty = sum(10 for v in vals if v < YELLOW) + sum(4 for v in vals if YELLOW <= v < GREEN)
    score = base - penalty - k.decay * 5
    return int(max(0, min(100, score)))

def worst_stat(k: Kingdom) -> Tuple[str, int]:
    items = [
        ("Казна", k.treasury),
        ("Порядок", k.order),
        ("Здоровье", k.health),
        ("Знать", k.nobles),
        ("Вера", k.faith),
        ("Граница", k.border),
    ]
    items.sort(key=lambda x: x[1])
    return items[0]


# -----------------------------
# NPC voices
# -----------------------------
NPCS: Dict[str, dict] = {
    "chancellor": {
        "name": "Канцлер Медь-у-Ногтя",
        "tone": "деловой, язвительный",
        "emoji": "📜",
    },
    "marshal": {
        "name": "Маршал Гримм из Северных Кольев",
        "tone": "прямой, мрачный",
        "emoji": "🛡️",
    },
    "bishop": {
        "name": "Архиепископиня Серафима Пепельная",
        "tone": "торжественный, угрожающе-ласковый",
        "emoji": "🔥",
    },
    "physician": {
        "name": "Лекарь Профитроль (клятва дана, но мелким шрифтом)",
        "tone": "профессиональный, циничный",
        "emoji": "🩺",
    },
    "spymaster": {
        "name": "Шептун Барон Без-Лица",
        "tone": "спокойный, неприятно точный",
        "emoji": "🕷️",
    },
    "reeve": {
        "name": "Староста Милая-Но-С-Молотком",
        "tone": "простая, бодрая, с угрозой",
        "emoji": "🧺",
    },
}

def npc_header(npc_id: str) -> str:
    n = NPCS[npc_id]
    return f"{n['emoji']} **{n['name']}** (_{n['tone']}_)"


# -----------------------------
# Event system
# -----------------------------
def trig_ok(k: Kingdom, trig: dict) -> bool:
    # Supported triggers: stat_lt, stat_gt, has_tag, not_tag, day_ge, day_le
    for key, val in trig.items():
        if key.endswith("_lt"):
            stat = key[:-3]
            if getattr(k, stat) >= int(val):
                return False
        elif key.endswith("_gt"):
            stat = key[:-3]
            if getattr(k, stat) <= int(val):
                return False
        elif key == "has_tag":
            if not k.has_tag(val):
                return False
        elif key == "not_tag":
            if k.has_tag(val):
                return False
        elif key == "day_ge":
            if k.day < int(val):
                return False
        elif key == "day_le":
            if k.day > int(val):
                return False
        else:
            # unknown trigger key -> fail safe (don't show)
            return False
    return True


def apply_effects(k: Kingdom, effects: dict) -> Dict[str, int]:
    """
    Apply numeric deltas and tags:
      effects: {
         "treasury": -5, "order": +3, ...
         "decay": +1, "doom": +2,
         "tags_add": {"martial_law": 2, ...}
      }
    Returns dict of deltas actually applied for display/analytics.
    """
    deltas: Dict[str, int] = {}
    for stat, delta in effects.items():
        if stat == "tags_add":
            continue
        if not hasattr(k, stat):
            continue
        d = int(delta)
        if d != 0:
            setattr(k, stat, getattr(k, stat) + d)
            deltas[stat] = d
    if "tags_add" in effects and isinstance(effects["tags_add"], dict):
        for tag_name, days in effects["tags_add"].items():
            k.add_tag(str(tag_name), int(days))
    k.clamp()
    return deltas


def weight_for_event(k: Kingdom, ev: dict) -> int:
    w = int(ev.get("weight", 1))

    # cheap dynamic weighting: make crises more likely when related stat is bad
    bias = ev.get("bias", {})
    for stat, mult in bias.items():
        v = getattr(k, stat)
        # lower stat -> higher weight
        if v < YELLOW:
            w += int(mult) * 3
        elif v < GREEN:
            w += int(mult)
    # tags influence
    for tag, add in ev.get("tag_weight", {}).items():
        if k.has_tag(tag):
            w += int(add)
    # doom nudges towards "resolution" events late
    if k.day >= 6 and ev.get("late_boost", False):
        w += 6 + k.doom // 2

    return max(0, w)


EVENTS: List[dict] = [
    {
        "id": "rat_tax",
        "npc": "chancellor",
        "title": "Налог на крыс… простите, на ‘грызунов податных’",
        "intro": "Канцлер разворачивает свиток, который пахнет чернилами и лёгким отчаянием.\n\n"
                 "«Ваше Величество, казна скрипит. Предлагаю… расширить налоговую базу. "
                 "Крысы, как известно, тоже граждане — если их правильно назвать».\n\n"
                 "За окнами действительно кто-то скребётся. Возможно, это уже электорат.",
        "trigger": {"treasury_lt": 60},
        "weight": 6,
        "bias": {"treasury": 2},
        "choices": [
            {
                "text": "Ввести ‘грызунный’ сбор. Народ переживёт.",
                "effects": {"treasury": +10, "order": -4, "nobles": -2, "doom": +1, "tags_add": {"tax_hike": 3}},
                "outro": "Казна толстеет, а народ учится ненавидеть творчески. Крысы смотрят на тебя с уважением."
            },
            {
                "text": "Срезать расходы двора. Да, и свечи тоже.",
                "effects": {"treasury": +6, "nobles": -4, "faith": -1, "doom": +1, "tags_add": {"austerity": 3}},
                "outro": "Дворяне обижаются так громко, что эхо уходит в склепы. Зато бухгалтерия впервые улыбается."
            },
            {
                "text": "Ничего не менять. Переждём.",
                "effects": {"treasury": -4, "doom": +2},
                "outro": "Свиток сворачивается сам. Казна — тоже."
            },
        ],
    },
    {
        "id": "plague",
        "npc": "physician",
        "title": "Пятна на коже и на репутации",
        "intro": "Лекарь протирает очки рукавом, который видел слишком многое.\n\n"
                 "«Есть новости. Плохие. Хорошие тоже есть: у нас появилась возможность проверить, "
                 "насколько быстро крестьяне умеют умирать организованно».\n\n"
                 "В низинах вспыхнула лихорадка. Люди шепчутся, что это кара. Болезнь — что это статистика.",
        "trigger": {"health_lt": 60},
        "weight": 7,
        "bias": {"health": 3},
        "choices": [
            {
                "text": "Закрыть рынки и дороги на неделю.",
                "effects": {"health": +14, "treasury": -6, "order": -2, "doom": +1, "tags_add": {"quarantine": 3}},
                "outro": "Чума упирается в ворота. Торговцы — в твою дверь."
            },
            {
                "text": "Нанять лекарей и алхимиков. Пусть спорят в палатках, не в храме.",
                "effects": {"treasury": -10, "health": +18, "faith": -2, "doom": +1, "tags_add": {"medical_response": 3}},
                "outro": "Народ живёт дольше. Священники — обиженно молчат."
            },
            {
                "text": "Объявить пост и молебны. Если не поможет — хотя бы красиво.",
                "effects": {"faith": +8, "health": +4, "order": -2, "doom": +2, "tags_add": {"pious_edict": 3}},
                "outro": "Пламя свечей ярче. Температура — тоже."
            },
        ],
    },
    {
        "id": "border_monster",
        "npc": "marshal",
        "title": "Монстр на тракте (и он не про налоги)",
        "intro": "Маршал снимает шлем. На лице — усталость, на словах — экономия.\n\n"
                 "«Северный тракт перекрыт. Там завёлся зверь. "
                 "Местные называют его ‘Костоглот’. Я называю его ‘проблема, которая растит цены’».\n\n"
                 "Если тракт падёт — падёт и снабжение.",
        "trigger": {"border_lt": 65},
        "weight": 7,
        "bias": {"border": 3, "order": 1},
        "choices": [
            {
                "text": "Отправить королевскую дружину. Быстро и дорого.",
                "effects": {"treasury": -8, "border": +16, "order": +2, "doom": +1, "tags_add": {"royal_patrols": 3}},
                "outro": "Костоглот исчезает. Дружина — тоже, но позже вернётся с трофеями и травмами."
            },
            {
                "text": "Объявить награду героям. Пусть риск станет профессией.",
                "effects": {"treasury": -4, "border": +10, "order": +1, "doom": +1, "tags_add": {"bounty": 3}},
                "outro": "В трактире появляются ‘герои’. Часть из них даже умеет держать меч за рукоять."
            },
            {
                "text": "Закрыть тракт. Переживём на запасах.",
                "effects": {"border": -6, "treasury": -2, "health": -2, "doom": +2},
                "outro": "Запасы тают. Монстр сытый. Все довольны, кроме людей."
            },
        ],
    },
    {
        "id": "noble_plot",
        "npc": "spymaster",
        "title": "Знать играется в шахматы, где пешки — люди",
        "intro": "Шептун улыбается так, будто у него в кармане лежит твой завтрашний день.\n\n"
                 "«Ваше Величество, у трёх домов внезапно совпали интересы. "
                 "Обычно такое бывает либо перед свадьбой, либо перед убийством».\n\n"
                 "Речь о коалиции ‘против хаоса’. Читай: ‘против тебя, если получится’.",
        "trigger": {"nobles_lt": 65},
        "weight": 6,
        "bias": {"nobles": 3},
        "choices": [
            {
                "text": "Купить лояльность: титулы, льготы, улыбки.",
                "effects": {"treasury": -8, "nobles": +16, "doom": +1, "tags_add": {"noble_concessions": 3}},
                "outro": "Они кланяются. Слишком низко — чтобы удобнее было ударить позже."
            },
            {
                "text": "Показательный суд. Пусть страх заменит уважение.",
                "effects": {"order": +8, "nobles": -6, "faith": -2, "doom": +2, "tags_add": {"purge": 3}},
                "outro": "Правосудие звучит красиво. Особенно когда оно говорит твоим голосом."
            },
            {
                "text": "Пустить слухи внутри знати. Пусть грызут друг друга.",
                "effects": {"nobles": +6, "order": -2, "doom": +1, "tags_add": {"court_rumours": 3}},
                "outro": "Интриги — как яды: малые дозы лечат, большие — делают тебя похожим на тех, кого ты презираешь."
            },
        ],
    },
    {
        "id": "heresy",
        "npc": "bishop",
        "title": "Ересь, которая умеет улыбаться",
        "intro": "Архиепископиня ставит на стол чашу с пеплом. Пахнет благовониями и приговором.\n\n"
                 "«В кварталах расползается новая вера. "
                 "Они говорят, что Пламя должно согревать, а не сжигать. "
                 "Опасные люди — они звучат разумно».\n\n"
                 "Религия — это всегда политика, только в красивой одежде.",
        "trigger": {"faith_lt": 65},
        "weight": 6,
        "bias": {"faith": 3, "order": 1},
        "choices": [
            {
                "text": "Разрешить проповеди. Но под надзором.",
                "effects": {"faith": +6, "order": -2, "nobles": +1, "doom": +1, "tags_add": {"toleration": 3}},
                "outro": "Город учится спорить словами, а не кострами. Иногда это даже работает."
            },
            {
                "text": "Запретить и карать. Быстро и страшно.",
                "effects": {"order": +6, "faith": -4, "public_fear": 0, "doom": +2, "tags_add": {"inquisition": 3}},
                "outro": "Костры теплее. Город — холоднее."
            },
            {
                "text": "Устроить общий праздник веры. Пусть единство станет привычкой.",
                "effects": {"treasury": -6, "faith": +12, "order": +2, "doom": +1, "tags_add": {"festival": 2}},
                "outro": "Толпа поёт. И на один вечер перестаёт искать врага."
            },
        ],
    },
    {
        "id": "bandits",
        "npc": "reeve",
        "title": "Разбойники и очень убедительная бедность",
        "intro": "Староста приходит без поклонов — но с корзиной жалоб.\n\n"
                 "«Ваше Величество, на дорогах такие ‘сборщики’, что даже мы бы так не смогли. "
                 "Люди платят дважды: разбойникам — деньгами, нам — нервами».\n\n"
                 "Если порядок падает, у государства появляется хобби: разваливаться.",
        "trigger": {"order_lt": 65},
        "weight": 7,
        "bias": {"order": 3},
        "choices": [
            {
                "text": "Усилить стражу и патрули.",
                "effects": {"treasury": -6, "order": +14, "nobles": -1, "doom": +1, "tags_add": {"patrols": 3}},
                "outro": "Дороги становятся безопаснее. Некоторым это даже мешает работать."
            },
            {
                "text": "Амнистия: принять часть разбойников в ополчение.",
                "effects": {"order": +8, "border": +2, "nobles": -2, "doom": +1, "tags_add": {"militia": 3}},
                "outro": "Вчерашние преступники маршируют строем. Вопрос только — куда повернут оружие завтра."
            },
            {
                "text": "Снизить налоги на деревни. Пусть бедность не вербует врагов.",
                "effects": {"treasury": -8, "order": +6, "health": +2, "doom": +1, "tags_add": {"tax_relief": 3}},
                "outro": "Люди меньше злятся. Казна — больше."
            },
        ],
    },
]

# Note: One event/day is enough for clarity.


# -----------------------------
# Daily generation
# -----------------------------
def eligible_events(k: Kingdom) -> List[dict]:
    evs = []
    for ev in EVENTS:
        if trig_ok(k, ev.get("trigger", {})):
            evs.append(ev)
    # fallback if nothing eligible: pick a random "pressure" event by removing triggers
    if not evs:
        evs = EVENTS[:]
    return evs

def pick_event(k: Kingdom) -> dict:
    rng = k.rng()
    evs = eligible_events(k)
    weights = [weight_for_event(k, ev) for ev in evs]
    # avoid all zero
    if sum(weights) <= 0:
        weights = [1 for _ in evs]
    chosen = rng.choices(evs, weights=weights, k=1)[0]
    return chosen


# -----------------------------
# System drift & escalations (guarantee a "state" by day 7)
# -----------------------------
def red_count(k: Kingdom) -> int:
    return sum(1 for v in (k.treasury, k.order, k.health, k.nobles, k.faith, k.border) if v < YELLOW)

def green_count(k: Kingdom) -> int:
    return sum(1 for v in (k.treasury, k.order, k.health, k.nobles, k.faith, k.border) if v >= GREEN)

def system_end_of_day(k: Kingdom, rng: random.Random) -> List[str]:
    """
    Small, readable systemic consequences.
    Also ensures we drift towards a decisive 7-day outcome.
    """
    beats: List[str] = []

    # base upkeep / gravity
    k.treasury -= 2  # the kingdom eats coins
    k.order -= 1 if k.has_tag("tax_hike") else 0
    k.health -= 1 if k.has_tag("quarantine") else 0  # quarantine has costs
    k.border -= 1  # threats never sleep

    # cross-couplings (light)
    if k.order < YELLOW:
        k.treasury -= 1
        k.health -= 1
    if k.health < YELLOW:
        k.order -= 1
    if k.treasury < YELLOW:
        k.order -= 1

    # decay logic (primary)
    reds = red_count(k)
    greens = green_count(k)
    if reds >= 2:
        k.decay += 1
        beats.append("Ночь проходит тяжело: когда в королевстве горит сразу в двух местах, дым неизбежно находит трон.")
    elif greens == 6:
        k.decay = max(0, k.decay - 1)
        beats.append("Ночь редкая: тишина без шёпота. Даже крысы шуршат аккуратнее.")

    # doom ramp: pushes toward decisive ending by day 7 (without feeling random)
    # doom grows when you oscillate or postpone problems
    if k.day >= 3:
        k.doom += 1
    if reds >= 3:
        k.doom += 1
    if k.has_tag("austerity") and k.has_tag("purge"):
        k.doom += 1  # harsh ruler reputation accelerates instability

    # escalation incidents (rare but meaningful)
    if k.order < 30 and rng.random() < 0.35:
        beats.append("К ночи слышны крики: в одном из кварталов ‘самоорганизовались’. Порядок — это не вещь, это договор.")
        k.order -= 6
        k.treasury -= 3
        k.decay += 1
    if k.health < 30 and rng.random() < 0.35:
        beats.append("К рассвету город пахнет уксусом и травами. Беда входит без стука — и выходит не всегда.")
        k.health -= 6
        k.order -= 3
        k.decay += 1
    if k.border < 30 and rng.random() < 0.35:
        beats.append("Север присылает ‘письмо’ стрелами. Пограничники отвечают молчанием: они заняты выживанием.")
        k.border -= 6
        k.treasury -= 2
        k.decay += 1

    k.clamp()
    return beats


# -----------------------------
# Narration helpers
# -----------------------------
STAT_LABELS = {
    "treasury": "Казна",
    "order": "Порядок",
    "health": "Здоровье",
    "nobles": "Знать",
    "faith": "Вера",
    "border": "Граница",
    "decay": "Упадок",
    "doom": "Рок",
}

def deltas_line(deltas: Dict[str, int]) -> str:
    # show only key stats
    keys = ["treasury", "order", "health", "nobles", "faith", "border", "decay"]
    parts = []
    for k in keys:
        if k in deltas and deltas[k] != 0:
            d = deltas[k]
            parts.append(f"{STAT_LABELS[k]} {'+' if d>0 else ''}{d}")
    return " · ".join(parts) if parts else "Без заметных числовых сдвигов (редкая роскошь)."

def hud_line(k: Kingdom) -> str:
    return (
        f"Казна {zone(k.treasury)}{k.treasury} | "
        f"Порядок {zone(k.order)}{k.order} | "
        f"Здоровье {zone(k.health)}{k.health}\n"
        f"Знать {zone(k.nobles)}{k.nobles} | "
        f"Вера {zone(k.faith)}{k.faith} | "
        f"Граница {zone(k.border)}{k.border}\n"
        f"**Упадок:** {k.decay}/10 · **Устойчивость:** {stability_score(k)}/100"
    )

def ending(k: Kingdom) -> str:
    # decisive by day 7: either stable, collapse, or specific failure state.
    if stable_state(k):
        return (
            "**ПОБЕДА: Королевство удержано.**\n\n"
            "Ты не победил мир — ты сделал невозможное: **заставил его не развалиться**. "
            "На этой неделе у государства не отвалились колёса… и это уже легенда.\n\n"
            f"**Устойчивость:** {stability_score(k)}/100 · **Упадок:** {k.decay}/10"
        )

    # collapse condition
    if k.decay >= 6 or red_count(k) >= 3:
        worst_name, worst_v = worst_stat(k)
        return (
            "**ПОРАЖЕНИЕ: Упадок победил.**\n\n"
            "Королевство не рушится красиво. Оно рушится *по счетам*: "
            "хлеб исчезает, дороги пустеют, люди перестают верить даже в слухи.\n\n"
            f"Самая больная точка: **{worst_name}** ({worst_v}).\n\n"
            f"**Упадок:** {k.decay}/10 · **Устойчивость:** {stability_score(k)}/100"
        )

    # "hard but survived" ending
    worst_name, worst_v = worst_stat(k)
    return (
        "**ФИНАЛ: На грани, но живы.**\n\n"
        "Ты удержал трон, но королевство держится на костылях, молитвах и привычке людей терпеть. "
        "Следующая неделя решит больше, чем эта.\n\n"
        f"Самая слабая точка: **{worst_name}** ({worst_v}).\n\n"
        f"**Упадок:** {k.decay}/10 · **Устойчивость:** {stability_score(k)}/100"
    )


# -----------------------------
# Analytics (simple JSONL)
# -----------------------------
def ensure_analytics_dir():
    os.makedirs("analytics", exist_ok=True)

def analytics_path(k: Kingdom) -> str:
    ensure_analytics_dir()
    return os.path.join("analytics", f"{k.session_id}.jsonl")

def log_event(k: Kingdom, payload: dict):
    p = analytics_path(k)
    payload = dict(payload)
    payload["session_id"] = k.session_id
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


# -----------------------------
# Game flow
# -----------------------------
def init_game(seed: int) -> Kingdom:
    k = Kingdom(seed=seed)
    k.day = 1
    k.max_days = 7

    # Start in "manageable but tense" zone
    k.treasury = 55
    k.order = 55
    k.health = 55
    k.nobles = 55
    k.faith = 55
    k.border = 55
    k.decay = 0
    k.doom = 0
    k.tags = []
    k.log = []

    k.push(
        "narrator",
        "**День первый — ‘Трон и табуретка’**\n\n"
        "Ты — монарх. Королевство — организм, который требует золота, крови и времени. "
        "Каждое утро к тебе приходят вести.\n\n"
        "**Цель недели:** не допустить упадка государства. "
        "Семь дней — и либо страна станет устойчивой, либо выберет более… естественное состояние."
    )
    return k


def new_day_event(k: Kingdom):
    ev = pick_event(k)
    k.current_event = ev
    k.current_event_id = ev["id"]


def snapshot(k: Kingdom) -> dict:
    return {
        "day": k.day,
        "treasury": k.treasury,
        "order": k.order,
        "health": k.health,
        "nobles": k.nobles,
        "faith": k.faith,
        "border": k.border,
        "decay": k.decay,
        "doom": k.doom,
        "tags": {t.name: t.days_left for t in k.tags},
        "event_id": k.current_event_id,
    }


def diff(a: dict, b: dict) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for key in ("treasury", "order", "health", "nobles", "faith", "border", "decay", "doom"):
        out[key] = int(b[key]) - int(a[key])
    return {k: v for k, v in out.items() if v != 0}


def play_choice(k: Kingdom, choice_idx: int) -> Tuple[Optional[str], List[str]]:
    """
    Player chooses option for today's event.
    Produce ONE narrator message.
    """
    rng = k.rng()
    ev = k.current_event
    if not ev:
        new_day_event(k)
        ev = k.current_event

    before = snapshot(k)

    k.buffer_start()

    # NPC delivers the news (buffer)
    k.push("npc", f"{npc_header(ev['npc'])}\n\n**{ev['title']}**\n\n{ev['intro']}")

    # Apply choice
    ch = ev["choices"][choice_idx]
    # primary effects
    deltas_applied = apply_effects(k, ch["effects"])
    # small “flavor” consequences based on tags/conditions
    if k.has_tag("tax_hike") and k.order < GREEN:
        k.order -= 1
        k.doom += 1

    # Put choice outro beat
    k.push("world", ch.get("outro", "Решение принято. Королевство делает пометку напротив твоего имени."))

    # System end-of-day drift and escalations
    beats = system_end_of_day(k, rng)
    for b in beats:
        k.push("world", b)

    # Tick tags AFTER day passes
    k.tick_tags()

    # Advance day
    k.day += 1
    k.clamp()

    after = snapshot(k)
    deltas = diff(before, after)

    # Create ONE narrator response
    buffered = k.buffer_end()

    # Choose 1–2 most important beats from buffer for readability
    # Prioritize systemic escalation lines and the choice outro.
    important = []
    for t in buffered:
        if "Ночь проходит тяжело" in t or "К ночи" in t or "К рассвету" in t or "Север" in t:
            important.append(t)
    if ch.get("outro"):
        important.insert(0, ch["outro"])

    important = important[:2] if important else buffered[:2]

    narrator_text = (
        f"**День {before['day']} → день {after['day']}**\n\n"
        + "\n\n".join(important).strip()
        + "\n\n"
        + f"**Сдвиги:** {deltas_line(deltas)}\n\n"
        + hud_line(k)
    )

    # Push compact narrator response into main log
    k.push("narrator", narrator_text)

    # Analytics
    log_event(k, {
        "type": "turn",
        "turn": before["day"],
        "event_id": ev["id"],
        "choice_idx": choice_idx,
        "choice_text": ch["text"],
        "before": {k2: before[k2] for k2 in ("treasury","order","health","nobles","faith","border","decay","doom")},
        "after": {k2: after[k2] for k2 in ("treasury","order","health","nobles","faith","border","decay","doom")},
        "deltas": deltas,
        "stability_score": stability_score(k),
        "red_count": red_count(k),
    })

    # Ending?
    end = None
    if k.day > k.max_days:
        end = ending(k)
        log_event(k, {
            "type": "end",
            "turn": k.max_days,
            "ending": "win" if stable_state(k) else ("collapse" if (k.decay>=6 or red_count(k)>=3) else "edge"),
            "final": snapshot(k),
            "stability_score": stability_score(k),
        })

    return end, buffered


# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="Majesty-proto: Король и Вести", layout="wide")

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
.card {
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 14px;
  padding: 12px 12px;
  background: rgba(255,255,255,0.02);
}
</style>
""", unsafe_allow_html=True)

st.title("👑 Majesty-подобный прототип: Король и ежедневные вести")
st.caption("Ироничное фэнтези с нотками dark fantasy. 7 дней. 1 весть в день. Цель — не допустить упадка.")

with st.sidebar:
    st.header("Сессия")
    seed = st.number_input("Seed", min_value=1, max_value=999999, value=42, step=1)

    if st.button("Новая партия (7 дней)", type="primary"):
        st.session_state["k"] = init_game(seed)
        st.session_state["ending"] = None
        st.session_state["debug_last"] = []
        # first day event
        new_day_event(st.session_state["k"])
        st.toast("Партия началась", icon="🌍")

    st.divider()
    st.subheader("Аналитика")
    st.caption("Логи пишутся в `./analytics/<session>.jsonl`")
    if "k" in st.session_state:
        st.code(analytics_path(st.session_state["k"]), language="text")

    st.divider()
    st.subheader("Пояснение зон")
    st.caption("🟢 ≥60, 🟡 40–59, 🔴 <40. Упадок растёт при 2+ красных параметрах.")


if "k" not in st.session_state:
    st.session_state["k"] = init_game(42)
    st.session_state["ending"] = None
    st.session_state["debug_last"] = []
    new_day_event(st.session_state["k"])

k: Kingdom = st.session_state["k"]

left, right = st.columns([0.68, 0.32], gap="large")

with right:
    st.markdown('<div class="hud-card">', unsafe_allow_html=True)
    st.markdown('<div class="hud-title">Королевство</div>', unsafe_allow_html=True)

    st.metric("Казна", f"{zone(k.treasury)} {k.treasury}")
    st.metric("Порядок", f"{zone(k.order)} {k.order}")
    st.metric("Здоровье", f"{zone(k.health)} {k.health}")
    st.metric("Знать", f"{zone(k.nobles)} {k.nobles}")
    st.metric("Вера", f"{zone(k.faith)} {k.faith}")
    st.metric("Граница", f"{zone(k.border)} {k.border}")

    st.markdown(f"**Упадок:** {k.decay}/10")
    st.markdown(f"**Устойчивость:** {stability_score(k)}/100")
    st.markdown(f"**День:** {k.day}/{k.max_days}")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="hud-card">', unsafe_allow_html=True)
    st.markdown('<div class="hud-title">Активные следы решений</div>', unsafe_allow_html=True)
    if not k.tags:
        st.markdown("<span class='hud-small'>Пока ничего не прилипло. Редкая удача.</span>", unsafe_allow_html=True)
    else:
        for t in k.tags:
            st.markdown(f"- `{t.name}` ещё **{t.days_left}** дн.")
    st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("Отладка: сырой буфер прошлого хода"):
        if not st.session_state.get("debug_last"):
            st.caption("Пусто.")
        else:
            for line in st.session_state["debug_last"]:
                st.markdown(line)
                st.divider()


with left:
    st.subheader(f"Двор: день {k.day}/{k.max_days}")

    if st.session_state["ending"]:
        st.error("ИТОГ")
        st.markdown(st.session_state["ending"])
        st.info("Нажми **Новая партия** в сайдбаре, чтобы начать заново.")

    # Chat feed
    c1, c2 = st.columns([1, 1])
    with c1:
        chat_height = st.slider("Высота ленты", 350, 900, 650, 50, key="chat_height")
    with c2:
        render_last = st.slider("Сообщений", 20, 200, 80, 10, key="render_last")

    feed = st.container(height=chat_height)
    with feed:
        st.markdown('<div class="chat-feed">', unsafe_allow_html=True)
        msgs = k.log[-render_last:] if k.log else []
        if not msgs:
            st.info("Пока пусто.")
        else:
            for m in msgs:
                with st.chat_message(ROLE_TO_CHAT[m.role]):
                    st.markdown(f"{ROLE_PREFIX[m.role]}\n\n{m.content}")
        st.markdown("</div>", unsafe_allow_html=True)

    # Event card + choices
    st.markdown("### Весть дня")
    disabled = bool(st.session_state["ending"]) or (k.day > k.max_days)

    if not k.current_event or k.current_event_id is None:
        new_day_event(k)

    ev = k.current_event
    if ev:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown(f"{npc_header(ev['npc'])}")
        st.markdown(f"**{ev['title']}**")
        st.markdown(ev["intro"])
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("### Решение трона")
        choice_texts = [c["text"] for c in ev["choices"]]
        choice_idx = st.radio(
            "",
            options=list(range(len(choice_texts))),
            format_func=lambda i: choice_texts[i],
            disabled=disabled,
            label_visibility="collapsed",
            key="choice_radio",
        )

        b1, b2 = st.columns([1, 1])
        with b1:
            if st.button("Издать указ", type="primary", use_container_width=True, disabled=disabled):
                # player message
                k.push("player", f"Я решаю: **{choice_texts[choice_idx]}**")
                end, debug_lines = play_choice(k, choice_idx)
                st.session_state["debug_last"] = debug_lines
                st.session_state["ending"] = end

                # Next day: pick next event if game continues
                if not st.session_state["ending"] and k.day <= k.max_days:
                    new_day_event(k)
                st.rerun()

        with b2:
            if st.button("Пропустить (плохая идея)", use_container_width=True, disabled=disabled):
                # Treat skip as a weak "do nothing": costs + doom
                k.push("player", "Я решаю: **ничего не делать** (и надеюсь, что мир сам исправится).")
                # Fabricate a minimal "event" on skip
                k.current_event = {
                    "id": "skip",
                    "npc": "chancellor",
                    "title": "Тишина (которая тоже событие)",
                    "intro": "Во дворце тихо. Это плохая тишина — когда слышно, как государство скрипит.",
                    "choices": [
                        {"text": "…", "effects": {"treasury": -2, "order": -2, "doom": +2}, "outro": "Ты ничего не сделал. Мир сделал выводы."}
                    ],
                }
                k.current_event_id = "skip"
                end, debug_lines = play_choice(k, 0)
                st.session_state["debug_last"] = debug_lines
                st.session_state["ending"] = end
                if not st.session_state["ending"] and k.day <= k.max_days:
                    new_day_event(k)
                st.rerun()
    else:
        st.info("Нет вестей — странно. Обычно они сами находят трон.")
