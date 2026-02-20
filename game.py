# majesty_game_ui_v2_fixed.py
# Streamlit Majesty-like procedural kingdom crisis prototype (7 days).
#
# This is your provided majesty_game_ui_v2.py with UI changes applied AND fixed
# (indentation + broken multiline f-strings in the UI section).
#
# Key UI behavior kept as requested:
# - Title: "Королевство за Семь Дней" + updated subtitle
# - Stats panel on the right of chat
# - Active tags moved to the very bottom
# - NPC messages use 📣 avatar; narrator 🕯️; player 👑
# - News are shown directly in the chat (announced once per day)
# - Game result is written into chat (via play_choice pushing ending)
# - "Двор:" removed -> "День N/X"

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
    "npc": "",
    "player": "👑 **Трон**",
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

    decay: int = 0          # Упадок (главный fail-meter) 0..10

    tags: List[Tag] = field(default_factory=list)
    log: List[Message] = field(default_factory=list)

    current_event_id: Optional[str] = None
    current_event: Optional[dict] = None

    # track which event has been announced into chat (to avoid duplicates)
    announced_event_id: Optional[str] = None

    # last turn deltas for UI hints
    last_turn_deltas: Dict[str, int] = field(default_factory=dict)

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    def rng(self) -> random.Random:
        return random.Random(self.seed + self.day * 1337)

    def clamp(self):
        for k in ("treasury", "order", "health", "nobles", "faith", "border"):
            v = getattr(self, k)
            setattr(self, k, int(max(0, min(100, v))))
        self.decay = int(max(0, min(10, self.decay)))

    def push(self, role: Role, text: str):
        self.log.append(Message(role=role, content=text))

    def add_tag(self, name: str, days: int):
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

STAT_LABELS = {
    "treasury": "Казна",
    "order": "Порядок",
    "health": "Здоровье",
    "nobles": "Знать",
    "faith": "Вера",
    "border": "Граница",
    "decay": "Упадок",
}

def zone(v: int) -> str:
    if v >= GREEN:
        return "🟢"
    if v >= YELLOW:
        return "🟡"
    return "🔴"

def red_count(k: Kingdom) -> int:
    return sum(1 for v in (k.treasury, k.order, k.health, k.nobles, k.faith, k.border) if v < YELLOW)

def green_count(k: Kingdom) -> int:
    return sum(1 for v in (k.treasury, k.order, k.health, k.nobles, k.faith, k.border) if v >= GREEN)

def stable_state(k: Kingdom) -> bool:
    # “Удержали государство”: нет красных зон и упадок низкий
    return (red_count(k) == 0) and (k.decay <= 2)

def stability_score(k: Kingdom) -> int:
    vals = [k.treasury, k.order, k.health, k.nobles, k.faith, k.border]
    base = sum(vals) // len(vals)
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


def render_decay_bar(decay: int) -> str:
    skulls = []
    for i in range(10):
        if i < decay:
            skulls.append("<span style='color:#ff4d4d;font-size:20px'>💀</span>")
        else:
            skulls.append("<span style='color:#555;font-size:20px'>💀</span>")
    return " ".join(skulls)

def decay_badge(decay: int) -> str:
    if decay <= 2:
        return "🟢 Низкий"
    if decay <= 5:
        return "🟡 Риск"
    return "🔴 Критический"


# -----------------------------
# NPC voices
# -----------------------------
NPCS: Dict[str, dict] = {
    "chancellor": {"name": "Канцлер Медь-у-Ногтя", "emoji": "📜"},
    "marshal":    {"name": "Маршал Гримм из Северных Кольев", "emoji": "🛡️"},
    "bishop":     {"name": "Архиепископиня Серафима Пепельная", "emoji": "🔥"},
    "physician":  {"name": "Лекарь Профитроль", "emoji": "🩺"},
    "spymaster":  {"name": "Шептун Барон Без-Лица", "emoji": "🕷️"},
    "reeve":      {"name": "Староста Милая-Но-С-Молотком", "emoji": "🧺"},
}

def npc_header(npc_id: str) -> str:
    n = NPCS[npc_id]
    return f"{n['emoji']} **{n['name']}**"


# -----------------------------
# Event system
# -----------------------------
def trig_ok(k: Kingdom, trig: dict) -> bool:
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
            return False
    return True

def apply_effects(k: Kingdom, effects: dict) -> Dict[str, int]:
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
    bias = ev.get("bias", {})
    for stat, mult in bias.items():
        v = getattr(k, stat)
        if v < YELLOW:
            w += int(mult) * 3
        elif v < GREEN:
            w += int(mult)
    for tag, add in ev.get("tag_weight", {}).items():
        if k.has_tag(tag):
            w += int(add)
    if k.day >= 6 and ev.get("late_boost", False):
        w += 6
    return max(0, w)

def eligible_events(k: Kingdom, events: List[dict]) -> List[dict]:
    evs = [ev for ev in events if trig_ok(k, ev.get("trigger", {}))]
    return evs if evs else events[:]  # fallback


# -----------------------------
# Content: daily news
# -----------------------------
EVENTS: List[dict] = [
    # --- Chancellor: money / policy ---
    {
        "id": "rat_tax",
        "npc": "chancellor",
        "domain": "treasury",
        "severity": 2,
        "title": "Налог на крыс… простите, на ‘грызунов податных’",
        "intro": """Канцлер раскатывает свитки, будто это похоронные простыни для бюджета.

«Казна кашляет, Ваше Величество. Лекарь просит золото, стража просит золото, а двор… двор просит хотя бы повод просить золото.
Есть решение изысканное: расширить налоговую базу. Крысы, если им дать титул, становятся платёжеспособнее.

Слышите скребёт за стеной? Это либо народ, либо новый средний класс.»""",
        "trigger": {"treasury_lt": 60},
        "weight": 6,
        "bias": {"treasury": 2},
        "choices": [
            {"text": "Ввести сбор. Народ переживёт.",
             "effects": {"treasury": +10, "order": -4, "nobles": -2, "tags_add": {"tax_hike": 3}},
             "outro": """Казна улыбается, как ростовщик на похоронах. Народ тоже улыбается — но уже тем, чем улыбаются виселицы."""},
            {"text": "Срезать расходы двора. Да, и свечи тоже.",
             "effects": {"treasury": +6, "nobles": -4, "faith": -1, "tags_add": {"austerity": 3}},
             "outro": """Двор режет расходы и обиду — второе громче. Казна становится бодрее, а знать учится произносить «предательство» шёпотом."""},
            {"text": "Ничего не менять. Переждём.",
             "effects": {"treasury": -4},
             "outro": """Вы оставляете всё как есть. Казна сворачивается в себя, как улитка под сапогом — медленно и без надежды."""},
        ],
    },
    {
        "id": "mint_scandal",
        "npc": "chancellor",
        "domain": "treasury",
        "severity": 2,
        "title": "Монетный двор и удивительно мягкое золото",
        "intro": """Канцлер кладёт на ладонь монету и сгибает её ногтем, как драматург — мораль.

«Ваше, на Монетном дворе завелась алхимия. Монеты стали мягкими — будто совесть.
Народ называет это чудом. Я называю это тем словом, которое запрещают произносить в приличном королевстве: инфляция.

Если не вмешаться, завтра мы будем богаты настолько, что сможем купить разве что уныние — оптом.»""",
        "trigger": {"treasury_lt": 70},
        "weight": 5,
        "bias": {"treasury": 2, "nobles": 1},
        "choices": [
            {"text": "Провести чистку монетного двора.",
             "effects": {"treasury": -4, "order": +6, "nobles": -2, "tags_add": {"audit": 3}},
             "outro": """Монеты снова звенят честно. Некоторые головы — тоже, но уже без телесного сопровождения."""},
            {"text": "Закрыть глаза и пустить ‘мягкое золото’ в оборот.",
             "effects": {"treasury": +8, "order": -6, "nobles": -2},
             "outro": """Золото течёт рекой — и воняет болотом. Порядок тонет первым, как принято у приличных катастроф."""},
            {"text": "Сделать ‘разовую реформу’: обмен и новый герб.",
             "effects": {"treasury": +2, "order": +2, "faith": -2},
             "outro": """Вы меняете герб и правила, как актёр — маску. Публика хлопает, пока не замечает, что пьеса та же."""},
        ],
    },
    {
        "id": "granary_fire",
        "npc": "chancellor",
        "domain": "treasury",
        "severity": 3,
        "title": "Пожар в амбарах (и запах чужой выгоды)",
        "intro": """Канцлер приходит с копотью на манжетах и слишком чистыми глазами.

«Сгорели амбары. Случайно — разумеется. Случайность пахнет смолой и чьей-то новой яхтой.
Голод не стучит в двери: он входит, как закон, и выходит — как налог.

Нам нужно решить, чем мы будем кормить людей: хлебом, очередью или надеждой.»""",
        "trigger": {"treasury_lt": 75},
        "weight": 6,
        "bias": {"treasury": 2, "order": 1, "health": 1},
        "choices": [
            {"text": "Выкупить зерно у гильдий по любой цене.",
             "effects": {"treasury": -12, "health": +8, "order": +2, "tags_add": {"emergency_buy": 2}},
             "outro": """Вы покупаете зерно по цене, на которой можно было бы построить вторую столицу — для тех, кто ещё жив. Голод отступает, казна — обижается."""},
            {"text": "Нормировать хлеб. Жёстко. С печатями.",
             "effects": {"order": +6, "health": +4, "nobles": -2, "tags_add": {"rationing": 3}},
             "outro": """Печати ложатся на хлеб, как проклятие. Люди едят меньше, живут дольше и спорят так, будто спор заменяет ужин."""},
            {"text": "Оставить всё рынку. Рынок мудр… на своей стороне.",
             "effects": {"health": -8, "order": -4, "treasury": +4},
             "outro": """Рынок «урегулировал» вопрос: сильные сыты, слабые мудреют. В хроники заносится: «так было задумано»."""},
        ],
    },

    # --- Physician: health ---
    {
        "id": "plague",
        "npc": "physician",
        "domain": "health",
        "severity": 3,
        "title": "Пятна на коже и на репутации",
        "intro": """Лекарь не садится. Он стоит, как приговор, и держит список симптомов, будто список обвинений.

«Лихорадка в низинах. Жар, язвы, кашель — обычная поэзия смерти.
Хорошая новость: болезнь честна. Ей всё равно, кто платит налоги.
Плохая новость: она работает быстрее, чем канцелярия.»""",
        "trigger": {"health_lt": 60},
        "weight": 7,
        "bias": {"health": 3},
        "choices": [
            {"text": "Закрыть рынки и дороги на неделю.",
             "effects": {"health": +14, "treasury": -6, "order": -2, "tags_add": {"quarantine": 3}},
             "outro": """Ворота закрыты. Чума бьётся в них, как актёр в четвёртую стену. Торговцы бьются в вашу — заметно громче."""},
            {"text": "Нанять лекарей и алхимиков.",
             "effects": {"treasury": -10, "health": +18, "faith": -2, "tags_add": {"medical_response": 3}},
             "outro": """Вы нанимаете лекарей и алхимиков. Народ живёт дольше, а священные объяснения звучат тише и обиженнее."""},
            {"text": "Объявить пост и молебны.",
             "effects": {"faith": +8, "health": +4, "order": -2, "tags_add": {"pious_edict": 3}},
             "outro": """Вы объявляете пост и молебны. Свечи горят ярко, а температура — ещё ярче. Бог, возможно, слышит. Вирус — точно."""},
        ],
    },
    {
        "id": "well_poison",
        "npc": "physician",
        "domain": "health",
        "severity": 2,
        "title": "Колodец, который ‘сам испортился’",
        "intro": """Лекарь приносит кружку воды и демонстративно не пьёт.

«В восточном квартале люди падают без лишней драматургии. Колодец ‘сам испортился’ — как репутация при дворе.
Если это саботаж, завтра ‘само’ испортится ещё пять колодцев.

Выбирайте: лечить, обвинять или экономить на живых.»""",
        "trigger": {"health_lt": 75},
        "weight": 5,
        "bias": {"health": 2, "order": 1},
        "choices": [
            {"text": "Перекрыть колодец, раздать кипячёную воду, найти источник.",
             "effects": {"treasury": -6, "health": +10, "order": +2, "tags_add": {"water_patrol": 3}},
             "outro": """Вы кипятите воду и страх. Вода становится скучной, но безопасной. Скука — редкая милость в нашем ремесле."""},
            {"text": "Обвинить ‘врагов веры’ и устроить показательное расследование.",
             "effects": {"faith": +6, "order": +2, "health": +2, "nobles": -2, "tags_add": {"scapegoat": 2}},
             "outro": """Вы находите виновных быстрее, чем источник. Толпа довольна: ей всё равно, что правда не успела на спектакль."""},
            {"text": "Сэкономить: ‘само пройдёт’.",
             "effects": {"health": -8, "order": -2},
             "outro": """Вы решаете, что ‘само пройдёт’. Оно не проходит. Оно осваивается и начинает работать по расписанию."""},
        ],
    },

    # --- Marshal: border ---
    {
        "id": "border_monster",
        "npc": "marshal",
        "domain": "border",
        "severity": 3,
        "title": "Монстр на тракте (и он не про налоги)",
        "intro": """Маршал снимает шлем. Под ним — лицо, которое видело слишком много побед, чтобы им верить.

«Северный тракт перекрыт. Завёлся зверь. Местные зовут его Костоглот.
Я зову его ‘рост цен’.

Если тракт падёт, снабжение падёт следом. А когда падает снабжение, первым всегда падает король — пусть и символически.»""",
        "trigger": {"border_lt": 65},
        "weight": 7,
        "bias": {"border": 3, "order": 1},
        "choices": [
            {"text": "Отправить королевскую дружину.",
             "effects": {"treasury": -8, "border": +16, "order": +2, "tags_add": {"royal_patrols": 3}},
             "outro": """Дружина уходит — и возвращается не целиком. Зверь исчезает. Покой тоже исчезает, но это уже традиция."""},
            {"text": "Объявить награду героям.",
             "effects": {"treasury": -4, "border": +10, "order": +1, "tags_add": {"bounty": 3}},
             "outro": """Вы обещаете награду. В трактирах рождаются герои, как грибы: многие съедобны, некоторые смертельно."""},
            {"text": "Закрыть тракт. Переживём на запасах.",
             "effects": {"border": -6, "treasury": -2, "health": -2},
             "outro": """Вы закрываете тракт. Запасы тают. Монстр сытый. Люди — учатся смотреть на трон голодными глазами."""},
        ],
    },
    {
        "id": "raiders",
        "npc": "marshal",
        "domain": "border",
        "severity": 2,
        "title": "Налётчики с северной улыбкой",
        "intro": """Маршал кладёт на стол наконечник стрелы. Он не украшает — он объясняет.

«Не война. Пока. Просто люди, которые считают чужое своим.
Если мы промолчим, они решат, что это дипломатия.

Граница — место, где терпение умирает первым. Обычно без почестей.»""",
        "trigger": {"border_lt": 75},
        "weight": 5,
        "bias": {"border": 2, "treasury": 1},
        "choices": [
            {"text": "Сжечь их лагерь и оставить знак.",
             "effects": {"border": +10, "order": +2, "faith": -2, "treasury": -4, "tags_add": {"reprisal": 2}},
             "outro": """Огонь отвечает вместо переговоров. Север понимает. Огонь, как известно, любит продолжения и повторные показы."""},
            {"text": "Выкупить мир подарками вождю.",
             "effects": {"treasury": -8, "border": +6, "nobles": +2, "tags_add": {"bribe_tribe": 3}},
             "outro": """Вы покупаете мир подарками. Мир становится вашим — ровно до следующего счёта. Вождь улыбается слишком профессионально."""},
            {"text": "Сделать вид, что налётов нет.",
             "effects": {"border": -8, "order": -2},
             "outro": """Вы делаете вид, что налётов нет. Налёты, к счастью, не разделяют вашего оптимизма."""},
        ],
    },

    # --- Spymaster: nobles / intrigue ---
    {
        "id": "noble_plot",
        "npc": "spymaster",
        "domain": "nobles",
        "severity": 3,
        "title": "Знать играет в шахматы, где пешки — люди",
        "intro": """Шептун говорит тихо — так, что слова приходится ловить, как яд на игле.

«Три дома внезапно совпали интересами. Обычно это случается либо перед свадьбой, либо перед убийством.
Они называют это ‘коалицией против хаоса’. Смешно: хаос обычно сидит в коалиции.

Выбирайте: кормить их амбиции, ломать их страхом или стравить их, как собак в саду.»""",
        "trigger": {"nobles_lt": 65},
        "weight": 6,
        "bias": {"nobles": 3},
        "choices": [
            {"text": "Купить лояльность: титулы, льготы, улыбки.",
             "effects": {"treasury": -8, "nobles": +16, "tags_add": {"noble_concessions": 3}},
             "outro": """Вы покупаете лояльность. Они кланяются низко — удобная поза для будущего удара в спину."""},
            {"text": "Показательный суд. Пусть страх заменит уважение.",
             "effects": {"order": +8, "nobles": -6, "faith": -2, "tags_add": {"purge": 3}},
             "outro": """Суд идёт быстро. Страх работает быстрее. Уважение, как и обычно, даже не успевает прийти."""},
            {"text": "Стравить дома слухами.",
             "effects": {"nobles": +6, "order": -2, "tags_add": {"court_rumours": 3}},
             "outro": """Вы пускаете слухи. Двор начинает гнить шепотом. Иногда это полезно: гниль пожирает гниль."""},
        ],
    },
    {
        "id": "heir_scandal",
        "npc": "spymaster",
        "domain": "nobles",
        "severity": 2,
        "title": "Скандал вокруг наследника (не твоего, но шумно)",
        "intro": """Шептун улыбается так, будто уже видел ваш некролог — и оценил стиль.

«Наследник дома Лисихов замечен в храме, затем в борделе, затем снова в храме.
Порядок событий спорный, но публика уже выбрала самое смешное.

Если не вмешаться, скандал вырастет и станет политической программой. Народ обожает, когда порок произносится с трибуны.»""",
        "trigger": {"nobles_lt": 75},
        "weight": 4,
        "bias": {"nobles": 2, "faith": 1},
        "choices": [
            {"text": "Замять золотом и брачным договором.",
             "effects": {"treasury": -6, "nobles": +10, "faith": -2, "tags_add": {"hush_money": 2}},
             "outro": """Золото и брак — древняя химия придворной чистоты. Скандал умирает. Плесень остаётся."""},
            {"text": "Сделать из него урок: публичное покаяние.",
             "effects": {"faith": +6, "nobles": +6, "order": +2},
             "outro": """Покаяние выходит на площадь. Толпа получает театр, а вы — сигнал: ‘трон режиссирует даже стыд’."""},
            {"text": "Пустить на самотёк — не моё дело.",
             "effects": {"nobles": -6, "order": -2},
             "outro": """Вы не вмешиваетесь. Скандал, как воспитанный человек, вмешивается вместо вас."""},
        ],
    },

    # --- Bishop: faith / unity ---
    {
        "id": "heresy",
        "npc": "bishop",
        "domain": "faith",
        "severity": 2,
        "title": "Ересь, которая умеет улыбаться",
        "intro": """Архиепископиня говорит так, будто каждое слово — свеча, и её можно воткнуть в чью-то совесть.

«В кварталах расползается новая вера. Они говорят, что Пламя должно согревать, а не сжигать.
Опасные люди. Они звучат разумно.

Разум — первый шаг к сомнению. Сомнение — первый шаг к ереси. А ересь, как вы знаете, плохо переносит налоговую отчётность.»""",
        "trigger": {"faith_lt": 65},
        "weight": 6,
        "bias": {"faith": 3, "order": 1},
        "choices": [
            {"text": "Разрешить проповеди, но под надзором.",
             "effects": {"faith": +6, "order": -2, "nobles": +1, "tags_add": {"toleration": 3}},
             "outro": """Вы позволяете проповеди под надзором. Город учится спорить словами, а не кострами. Иногда это даже хуже — слова запоминаются."""},
            {"text": "Запретить и карать.",
             "effects": {"order": +6, "faith": -4, "tags_add": {"inquisition": 3}},
             "outro": """Вы запрещаете и караете. Костры теплеют. Город холодеет. Бог молчит с достойным королей самоконтролем."""},
            {"text": "Праздник веры: единство как привычка.",
             "effects": {"treasury": -6, "faith": +12, "order": +2, "tags_add": {"festival": 2}},
             "outro": """Вы устраиваете праздник веры. Толпа поёт и на вечер забывает, кого сегодня ненавидеть. Завтра — вспомнит."""},
        ],
    },
    {
        "id": "black_relic",
        "npc": "bishop",
        "domain": "faith",
        "severity": 3,
        "title": "Чёрная реликвия в лавке старьёвщика",
        "intro": """Архиепископиня держит свёрток так, будто он способен исповедоваться и обвинить её первым.

«В городе продают реликвию. Называют её ‘Кость Святого’.
Удивительно: святой, судя по запаху, умер вчера — и был крайне зол.

Если это подделка — вера треснет. Если не подделка — треснет всё остальное.»""",
        "trigger": {"faith_lt": 75},
        "weight": 5,
        "bias": {"faith": 2, "order": 1},
        "choices": [
            {"text": "Изъять реликвию и спрятать в храме.",
             "effects": {"faith": +8, "order": +2, "treasury": -2, "tags_add": {"sealed_relic": 3}},
             "outro": """Вы изымаете реликвию и прячете её в храме. Реликвия исчезает. Слухи обретают бессмертие."""},
            {"text": "Объявить её подделкой и наказать торговца.",
             "effects": {"order": +6, "faith": +2, "nobles": -2, "tags_add": {"public_trial": 2}},
             "outro": """Вы объявляете её подделкой и находите виновного. Город любит простые ответы. Истина берёт выходной."""},
            {"text": "Продать обратно ‘народу’. Пусть вера станет экономикой.",
             "effects": {"treasury": +6, "faith": -6, "order": -2},
             "outro": """Вы продаёте её обратно народу. Казна довольна. Алтари — запоминают. Память у них долгая."""},
        ],
    },

    # --- Reeve: order / common folk ---
    {
        "id": "bandits",
        "npc": "reeve",
        "domain": "order",
        "severity": 2,
        "title": "Разбойники и очень убедительная бедность",
        "intro": """Староста приходит с корзиной жалоб — тяжёлой, как совесть чиновника.

«На дорогах такие сборщики, что даже мы бы так не смогли.
Люди платят дважды: разбойникам — деньгами, нам — нервами.

Когда порядок падает, государство заводит хобби: разваливаться с чувством собственного достоинства.»""",
        "trigger": {"order_lt": 65},
        "weight": 7,
        "bias": {"order": 3},
        "choices": [
            {"text": "Усилить стражу и патрули.",
             "effects": {"treasury": -6, "order": +14, "nobles": -1, "tags_add": {"patrols": 3}},
             "outro": """Патрули множатся. Дороги становятся безопаснее. Некоторым это мешает работать — и они обижаются профессионально."""},
            {"text": "Амнистия: принять часть разбойников в ополчение.",
             "effects": {"order": +8, "border": +2, "nobles": -2, "tags_add": {"militia": 3}},
             "outro": """Вы берёте разбойников в ополчение. Вчерашний нож идёт строем. Вопрос лишь в том, куда он повернётся завтра."""},
            {"text": "Снизить налоги на деревни.",
             "effects": {"treasury": -8, "order": +6, "health": +2, "tags_add": {"tax_relief": 3}},
             "outro": """Вы снижаете налоги на деревни. Люди меньше злятся. Казна злеет за них — из принципа."""},
        ],
    },
    {
        "id": "night_market",
        "npc": "reeve",
        "domain": "order",
        "severity": 2,
        "title": "Ночной рынок: всё законно, если не смотреть",
        "intro": """Староста высыпает на стол мешочек монет — слишком знакомых, чтобы быть законными.

«Ваше, у нас ночной рынок. Там продают всё: от хлеба до молитв.
И всё — без налогов, разумеется. Стража делает вид, что это театр.

Можно закрыть. Можно крышевать. Можно… быть удивлённым каждый вечер.»""",
        "trigger": {"order_lt": 75},
        "weight": 5,
        "bias": {"order": 2, "treasury": 1},
        "choices": [
            {"text": "Разогнать лавки и наказать стражу.",
             "effects": {"order": +10, "treasury": -2, "nobles": -2},
             "outro": """Вы разгоняете лавки и наказываете стражу. Закон становится громче. Тени — тоже, но уже злобнее."""},
            {"text": "Ввести ‘ночную лицензию’ и забрать долю в казну.",
             "effects": {"treasury": +8, "order": -2, "faith": -2, "tags_add": {"licensed_smuggling": 3}},
             "outro": """Вы вводите ‘ночную лицензию’ и берёте долю. Казна толстеет. Репутация тоже — но в неправильных местах."""},
            {"text": "Не трогать. У людей должен быть клапан.",
             "effects": {"order": -4, "health": +2},
             "outro": """Вы не трогаете рынок. У людей появляется клапан. Иногда он работает. Иногда — шипит прямо вам в лицо."""},
        ],
    },
]


# -----------------------------
# System drift & decay logic
# -----------------------------
def event_resolution_decay_delta(k: Kingdom, before: dict, after: dict, ev: dict) -> Tuple[int, List[str]]:
    reasons: List[str] = []
    delta = 0
    domain = ev.get("domain")
    severity = int(ev.get("severity", 1))

    if domain and domain in after and domain in before:
        b = int(before[domain])
        a = int(after[domain])

        if a < YELLOW:
            delta += severity
            reasons.append(f"кризис дня не купирован ({STAT_LABELS.get(domain, domain)} в 🔴) +{severity}")
        if b < YELLOW and a >= YELLOW:
            delta -= 1
            reasons.append(f"кризис дня приглушён ({STAT_LABELS.get(domain, domain)} вышла из 🔴) -1")
        if b >= YELLOW and a < YELLOW:
            delta += 1
            reasons.append(f"ты открыл новую рану ({STAT_LABELS.get(domain, domain)} упала в 🔴) +1")

    return delta, reasons

def global_state_decay_delta(k: Kingdom) -> Tuple[int, List[str]]:
    reds = red_count(k)
    greens = green_count(k)
    reasons: List[str] = []
    delta = 0
    if reds >= 2:
        delta += 1
        reasons.append("в государстве 2+ 🔴 зон +1")
    if greens == 6:
        delta -= 1
        reasons.append("все показатели в 🟢 зоне -1")
    return delta, reasons

def system_end_of_day(k: Kingdom, rng: random.Random) -> List[str]:
    beats: List[str] = []

    k.treasury -= 2
    k.border -= 1

    if k.has_tag("tax_hike"):
        k.order -= 1
    if k.has_tag("quarantine"):
        k.treasury -= 1
        k.order -= 1
    if k.has_tag("licensed_smuggling"):
        k.order -= 1
    if k.has_tag("purge"):
        k.nobles -= 1
        k.faith -= 1

    if k.order < YELLOW:
        k.treasury -= 1
        k.health -= 1
    if k.health < YELLOW:
        k.order -= 1
    if k.treasury < YELLOW:
        k.order -= 1
    if k.border < YELLOW:
        k.order -= 1

    if k.order < 30 and rng.random() < 0.30:
        beats.append("К ночи слышны крики: в одном из кварталов ‘самоорганизовались’. Порядок — договор, а не предмет.")
        k.order -= 6
        k.treasury -= 3
    if k.health < 30 and rng.random() < 0.30:
        beats.append("К рассвету город пахнет уксусом и травами. Беда входит без стука — и выходит не всегда.")
        k.health -= 6
        k.order -= 3
    if k.border < 30 and rng.random() < 0.30:
        beats.append("Север присылает ‘письмо’ стрелами. Пограничники отвечают молчанием: они заняты выживанием.")
        k.border -= 6
        k.treasury -= 2

    k.clamp()
    return beats


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

    k.treasury = 55
    k.order = 55
    k.health = 55
    k.nobles = 55
    k.faith = 55
    k.border = 55
    k.decay = 0
    k.tags = []
    k.log = []
    k.current_event = None
    k.current_event_id = None
    k.announced_event_id = None

    k.push(
        "narrator",
        "**День первый — Трон и неизбежность.**\n\n"
        "Каждое утро вести стучатся в двери дворца.\n"
        "Каждый указ — либо гвоздь в гроб беды, либо гвоздь в крышку государства.\n\n"
        "**Семь дней** — и королевство станет устойчивым… или станет историей."
    )
    return k

def pick_event(k: Kingdom) -> dict:
    rng = k.rng()
    evs = eligible_events(k, EVENTS)
    weights = [weight_for_event(k, ev) for ev in evs]
    if sum(weights) <= 0:
        weights = [1 for _ in evs]
    return rng.choices(evs, weights=weights, k=1)[0]

def announce_event_if_needed(k: Kingdom):
    """Push the current day's news into the chat once."""
    if not k.current_event or not k.current_event_id:
        return
    if k.announced_event_id == k.current_event_id:
        return
    ev = k.current_event
    k.push("npc", f"{npc_header(ev['npc'])}\n\n{ev['intro']}")
    k.announced_event_id = k.current_event_id

def new_day_event(k: Kingdom):
    ev = pick_event(k)
    k.current_event = ev
    k.current_event_id = ev["id"]
    announce_event_if_needed(k)

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
        "tags": {t.name: t.days_left for t in k.tags},
        "event_id": k.current_event_id,
    }

def diff(a: dict, b: dict) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for key in ("treasury", "order", "health", "nobles", "faith", "border", "decay"):
        out[key] = int(b[key]) - int(a[key])
    return {kk: vv for kk, vv in out.items() if vv != 0}

def _delta_arrows(d: int) -> str:
    """No digits: show direction + intensity."""
    a = abs(int(d))
    if a >= 12:
        arrows = "⬆️⬆️⬆️" if d > 0 else "⬇️⬇️⬇️"
    elif a >= 7:
        arrows = "⬆️⬆️" if d > 0 else "⬇️⬇️"
    else:
        arrows = "⬆️" if d > 0 else "⬇️"
    return arrows

def deltas_line_readable(deltas: Dict[str, int]) -> str:
    """Readable deltas without numbers (chat-friendly)."""
    keys = ["treasury", "order", "health", "nobles", "faith", "border", "decay"]
    parts: List[str] = []
    for k in keys:
        if k in deltas and deltas[k] != 0:
            d = int(deltas[k])
            color = "#22c55e" if d > 0 else "#ef4444"
            parts.append(
                f"<span style='color:{color}; font-weight:700'>{STAT_LABELS[k]} {_delta_arrows(d)}</span>"
            )
    return " · ".join(parts) if parts else "Сдвиги тихие. Это не значит — добрые."

def stat_state_word(stat: str, v: int) -> str:
    """Qualitative state only (no digits)."""
    v = int(v)
    if v >= 80:
        tier = "цветёт"
    elif v >= GREEN:
        tier = "крепко держится"
    elif v >= YELLOW:
        tier = "шатается"
    elif v >= 20:
        tier = "хрипит"
    else:
        tier = "на краю"
    return f"{STAT_LABELS.get(stat, stat)} — {tier}"

def kingdom_states_line(k: Kingdom) -> str:
    parts = [
        stat_state_word("treasury", k.treasury),
        stat_state_word("order", k.order),
        stat_state_word("health", k.health),
        stat_state_word("nobles", k.nobles),
        stat_state_word("faith", k.faith),
        stat_state_word("border", k.border),
    ]
    return " · ".join(parts)

def choice_effect_preview(effects: dict) -> str:
    """Short preview for radio options (no numbers)."""
    show_keys = ["treasury", "order", "health", "nobles", "faith", "border"]
    parts = []
    for k in show_keys:
        if k in effects and int(effects[k]) != 0:
            d = int(effects[k])
            parts.append(f"{STAT_LABELS[k]}{_delta_arrows(d)}")
    if "tags_add" in effects:
        parts.append("следы…")
    return " · ".join(parts)


def enhanced_ending(k: Kingdom, reasons: list[str]) -> str:
    best = sorted(
        [("Казна", k.treasury), ("Порядок", k.order), ("Здоровье", k.health),
         ("Знать", k.nobles), ("Вера", k.faith), ("Граница", k.border)],
        key=lambda x: x[1],
        reverse=True
    )
    worst = sorted(best, key=lambda x: x[1])
    best_lines = "\n".join([f"• {name} — {value}. Ещё держится." for name, value in best[:2]])
    worst_lines = "\n".join([f"• {name} — {value}. Здесь трещина." for name, value in worst[:2]])
    cause = reasons[-1] if reasons else "Мир устал от решений. Или их отсутствия."
    tone = "🎉" if stable_state(k) else ("💀" if (k.decay>=6 or red_count(k)>=3) else "⚖️")
    return (
        f"{tone} **Суд семи дней вынес приговор.**\n\n"
        f"**Лучшее в королевстве:**\n{best_lines}\n\n"
        f"**Самые больные места:**\n{worst_lines}\n\n"
        f"**Главная причина упадка:**\n{cause}\n\n"
        f"И так завершилась неделя, где каждое слово стоило крови, а каждый указ — сна."
    )

def ending(k: Kingdom) -> str:
    if stable_state(k):
        return (
            "🎉 **ПОБЕДА: Королевство удержано.**\n\n"
            "Ты не победил мир — ты сделал невозможное: **заставил его не развалиться**.\n\n"
            f"**Упадок:** {k.decay}/10"
        )

    if k.decay >= 6 or red_count(k) >= 3:
        worst_name, worst_v = worst_stat(k)
        return (
            "💀 **ПОРАЖЕНИЕ: Упадок победил.**\n\n"
            "Государство рушится не красиво. Оно рушится по счетам.\n\n"
            f"Самая больная точка: **{worst_name}** ({worst_v}).\n\n"
            f"**Упадок:** {k.decay}/10"
        )

    worst_name, worst_v = worst_stat(k)
    return (
        "⚖️ **ФИНАЛ: На грани, но живы.**\n\n"
        "Ты удержал трон, но королевство держится на костылях, молитвах и привычке людей терпеть.\n\n"
        f"Самая слабая точка: **{worst_name}** ({worst_v}).\n\n"
        f"**Упадок:** {k.decay}/10"
    )

def play_choice(k: Kingdom, choice_idx: int) -> Optional[str]:
    rng = k.rng()
    ev = k.current_event
    if not ev:
        new_day_event(k)
        ev = k.current_event

    before = snapshot(k)
    before_decay = k.decay

    ch = ev["choices"][choice_idx]
    apply_effects(k, ch["effects"])
    k.push("npc", ch.get("outro", "Указ произнесён. Мир моргнул — и записал это в книгу последствий."))

    drift_beats = system_end_of_day(k, rng)
    for b in drift_beats:
        k.push("npc", b)

    after_mid = snapshot(k)
    ev_delta, ev_reasons = event_resolution_decay_delta(k, before, after_mid, ev)
    gl_delta, gl_reasons = global_state_decay_delta(k)

    k.decay += ev_delta + gl_delta
    k.clamp()

    decay_change = k.decay - before_decay
    reasons = ev_reasons + gl_reasons
    if decay_change != 0:
        sign = "+" if decay_change > 0 else ""
        if reasons:
            decay_explain = f"**Почему упадок {sign}{decay_change}:** " + "; ".join(reasons) + "."
        else:
            decay_explain = f"**Почему упадок {sign}{decay_change}:** так сложились обстоятельства (и твой указ)."
    else:
        decay_explain = "**Упадок не изменился:** сегодня ты не усилил трещины — и не залечил их до конца."

    k.tick_tags()

    k.day += 1
    k.clamp()
    after = snapshot(k)

    deltas = diff(before, after)
    k.last_turn_deltas = deltas

    narrator_text = (
        f"**День {before['day']} завершён**\n\n"
        f"**Сдвиги:** {deltas_line_readable(deltas)}\n\n"
        f"**Состояние:** {kingdom_states_line(k)}\n\n"
        f"{decay_explain}"
    )
    k.push("narrator", narrator_text)

    log_event(k, {
        "type": "turn",
        "turn": before["day"],
        "event_id": ev["id"],
        "choice_idx": choice_idx,
        "choice_text": ch["text"],
        "domain": ev.get("domain"),
        "severity": ev.get("severity"),
        "before": {kk: before[kk] for kk in ("treasury","order","health","nobles","faith","border","decay")},
        "after": {kk: after[kk] for kk in ("treasury","order","health","nobles","faith","border","decay")},
        "deltas": deltas,
        "decay_reason": reasons,
        "stability_score": stability_score(k),
        "red_count": red_count(k),
    })

    end = None
    if k.day > k.max_days:
        end = ending(k)
        enhanced = enhanced_ending(k, reasons)
        k.push("narrator", enhanced)
        log_event(k, {
            "type": "end",
            "turn": k.max_days,
            "ending": "win" if stable_state(k) else ("collapse" if (k.decay>=6 or red_count(k)>=3) else "edge"),
            "final": snapshot(k),
            "stability_score": stability_score(k),
        })

    return end


# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="Королевство за Семь Дней", layout="wide")

st.markdown("""
<style>
.block-container { padding-top: 1.0rem; max-width: 1400px; }
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
.small { font-size: 0.9rem; opacity: 0.85; }
.decay-wrap {
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 14px;
  padding: 10px 12px;
  background: rgba(255,255,255,0.02);
}
.decay-title { font-weight: 800; font-size: 1.05rem; }
.decay-sub { opacity: 0.85; margin-top: 2px; }
</style>
""", unsafe_allow_html=True)

st.title("Королевство за Семь Дней")
st.caption("Семь дней тебе дано — и ни мгновеньем более, что удержать корону на лезвии судьбы.")

with st.sidebar:
    st.header("Сессия")
    seed = st.number_input("Seed", min_value=1, max_value=999999, value=42, step=1)

    if st.button("Новая партия (7 дней)", type="primary"):
        st.session_state["k"] = init_game(seed)
        st.session_state["ending"] = None
        st.session_state["prev_log_len"] = 0
        st.toast("Партия началась", icon="🌍")
        new_day_event(st.session_state["k"])
        st.rerun()

    st.divider()
    st.subheader("Аналитика")
    st.caption("Логи: `./analytics/<session>.jsonl`")
    if "k" in st.session_state:
        st.code(analytics_path(st.session_state["k"]), language="text")

if "k" not in st.session_state:
    st.session_state["k"] = init_game(42)
    st.session_state["ending"] = None
    st.session_state["prev_log_len"] = 0
    new_day_event(st.session_state["k"])

k: Kingdom = st.session_state["k"]

# Ensure the current day's event is announced into chat (safe on reruns)
if k.current_event and k.current_event_id:
    announce_event_if_needed(k)
elif not k.current_event:
    new_day_event(k)

# ---- Main layout: chat left, stats right ----
left, right = st.columns([0.70, 0.30], gap="large")

with right:
    st.subheader("Показатели")
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown(f"**Упадок:** {k.decay}/10 · {decay_badge(k.decay)}")
    st.progress(k.decay / 10.0)
    st.markdown(f"- Казна: {zone(k.treasury)} {k.treasury}{(' ' + _delta_arrows(k.last_turn_deltas.get('treasury',0))) if k.last_turn_deltas.get('treasury',0) else ''}")
    st.markdown(f"- Порядок: {zone(k.order)} {k.order}{(' ' + _delta_arrows(k.last_turn_deltas.get('order',0))) if k.last_turn_deltas.get('order',0) else ''}")
    st.markdown(f"- Здоровье: {zone(k.health)} {k.health}{(' ' + _delta_arrows(k.last_turn_deltas.get('health',0))) if k.last_turn_deltas.get('health',0) else ''}")
    st.markdown(f"- Знать: {zone(k.nobles)} {k.nobles}{(' ' + _delta_arrows(k.last_turn_deltas.get('nobles',0))) if k.last_turn_deltas.get('nobles',0) else ''}")
    st.markdown(f"- Вера: {zone(k.faith)} {k.faith}{(' ' + _delta_arrows(k.last_turn_deltas.get('faith',0))) if k.last_turn_deltas.get('faith',0) else ''}")
    st.markdown(f"- Граница: {zone(k.border)} {k.border}{(' ' + _delta_arrows(k.last_turn_deltas.get('border',0))) if k.last_turn_deltas.get('border',0) else ''}")
    st.markdown("</div>", unsafe_allow_html=True)

with left:
    st.subheader(f"День {k.day}/{k.max_days}")

    if st.session_state["ending"]:
        st.info("Партия завершена. Нажми **Новая партия** в сайдбаре, чтобы начать заново.")

    chat_height = st.session_state.get("chat_height", 500)
    render_last = st.session_state.get("render_last", 120)

    feed = st.container(height=chat_height)
    with feed:
        st.markdown('<div class="chat-feed">', unsafe_allow_html=True)
        msgs = k.log[-render_last:] if k.log else []
        prev_len = st.session_state.get("prev_log_len", 0)
        current_len = len(k.log)
        start_idx = max(0, current_len - render_last)
        if not msgs:
            st.info("Пока пусто.")
        else:
            for i, m in enumerate(msgs):
                global_idx = start_idx + i
                if global_idx == prev_len:
                    st.markdown("<div id='new-start'></div>", unsafe_allow_html=True)

                avatar = None
                if m.role == "npc":
                    avatar = NPCS.get(k.current_event.get("npc") if k.current_event else "", {}).get("emoji", "📜")
                elif m.role == "narrator":
                    avatar = "🕯️"
                else:
                    avatar = "👑"
                with st.chat_message(ROLE_TO_CHAT[m.role], avatar=avatar):
                    st.markdown(f"{ROLE_PREFIX[m.role]}\n\n{m.content}", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("### Решение трона")
    disabled = bool(st.session_state["ending"]) or (k.day > k.max_days) or (k.current_event is None)

    ev = k.current_event
    if ev:
        choice_texts = [c["text"] for c in ev["choices"]]
        choice_idx = st.radio(
            "",
            options=list(range(len(choice_texts))),
            format_func=lambda i: f"{choice_texts[i]}  —  {choice_effect_preview(ev['choices'][i]['effects'])}",
            disabled=disabled,
            label_visibility="collapsed",
            key="choice_radio",
        )

        b1, b2 = st.columns([1, 1])
        with b1:
            if st.button("Издать указ", type="primary", use_container_width=True, disabled=disabled):
                st.session_state["prev_log_len"] = len(k.log)
                k.push("player", f"Я решаю: **{choice_texts[choice_idx]}**")
                end = play_choice(k, choice_idx)
                st.session_state["ending"] = end
                if not st.session_state["ending"] and k.day <= k.max_days:
                    new_day_event(k)
                st.rerun()

        with b2:
            if st.button("Пропустить (плохая идея)", use_container_width=True, disabled=disabled):
                st.session_state["prev_log_len"] = len(k.log)
                k.push("player", "Я решаю: **ничего не делать** (и надеюсь, что беда стесняется).")
                k.current_event = {
                    "id": "skip",
                    "npc": "chancellor",
                    "domain": "order",
                    "severity": 2,
                    "title": "Тишина (которая тоже событие)",
                    "intro": "Во дворце тихо. Это плохая тишина — когда слышно, как государство скрипит.",
                    "choices": [
                        {"text": "…", "effects": {"treasury": -2, "order": -2}, "outro": "Ты ничего не сделал. Мир сделал выводы."}
                    ],
                }
                k.current_event_id = "skip"
                k.announced_event_id = None
                announce_event_if_needed(k)

                end = play_choice(k, 0)
                st.session_state["ending"] = end
                if not st.session_state["ending"] and k.day <= k.max_days:
                    new_day_event(k)
                st.rerun()

# ---- Active tags (moved to the bottom) ----
with st.expander("Активные следы решений"):
    if not k.tags:
        st.caption("Пока ничего не прилипло.")
    else:
        for t in k.tags:
            st.markdown(f"- `{t.name}` ещё **{t.days_left}** дн.")

# ---- Hidden chat controls ----
with st.expander("Настройки ленты (не трогать без нужды)"):
    st.session_state["chat_height"] = st.slider("Высота ленты", 250, 900, int(st.session_state.get("chat_height", 500)), 50)
    st.session_state["render_last"] = st.slider("Сколько сообщений показывать", 20, 200, int(st.session_state.get("render_last", 120)), 10)
    st.caption("🟢 ≥60, 🟡 40–59, 🔴 <40. Упадок растёт, если кризис дня не купирован и/или есть 2+ 🔴 зоны.")
