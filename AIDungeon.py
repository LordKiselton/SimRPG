# app.py
# ============================================================
# 🧙 AI-Driven Adventure (Streamlit MVP)
# One hero • One active campaign • One-call-per-turn DM
# Russian narrative • Inventory + Spells • Summary every N turns
# After finale -> "🔁 Начать новую историю" (same hero, new world)
# ============================================================

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

# ============================================================
# CONFIG
# ============================================================

APP_TITLE = "🧙 AI Adventure"
DB_PATH = os.environ.get("ADVENTURE_DB_PATH", "adventure.db")

DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")  # safe default; can override in UI/env
DEFAULT_MAX_TURNS = 15
DEFAULT_INV_LIMIT = 10

SUMMARY_EVERY_TURNS = 10  # create summary every N turns (when possible)

# Text length targets (soft; used in prompting)
LEN_PRESET = {
    "short": {"scene_chars": 700, "consequence_chars": 250},
    "medium": {"scene_chars": 1000, "consequence_chars": 400},
    "long": {"scene_chars": 1300, "consequence_chars": 550},
}

# Tone presets (Russian)
TONE_PRESET = {
    "classic": "Классическое фэнтези. Сдержанная драматургия, без крайностей, без гротеска.",
    "heroic": "Героическое фэнтези. Чуть больше эпика, но без пафоса ради пафоса.",
    "dark": "Мрачное фэнтези. Напряжение и опасность, но без чрезмерной жестокости и натурализма.",
    "light_irony": "Лёгкая ирония. Улыбка и живость, но история остаётся серьёзной и цельной.",
}

# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class Hero:
    hero_id: str
    name: str
    hero_class: str
    race: str
    created_at: float

@dataclass
class Item:
    item_id: str
    name: str
    description: str
    type: str  # weapon/consumable/quest/utility/artifact

@dataclass
class Spell:
    spell_id: str
    name: str
    description: str
    type: str  # combat/utility/social

@dataclass
class DMSettings:
    model: str = DEFAULT_MODEL
    system_prompt: str = ""
    scene_length: str = "medium"  # short/medium/long
    tone: str = "classic"         # classic/heroic/dark/light_irony
    # balance sliders: stored as floats 0..1; we normalize in prompting
    balance_combat: float = 0.33
    balance_exploration: float = 0.33
    balance_social: float = 0.34
    consequence_intensity: str = "normal"  # low/normal/high
    choices_count: int = 3  # default 3, can be 4 (architectural)
    inventory_limit: int = DEFAULT_INV_LIMIT
    max_turns: int = DEFAULT_MAX_TURNS
    debug_mode: bool = False
    temperature: Optional[float] = None  # optional advanced (if supported)

@dataclass
class Campaign:
    campaign_id: str
    hero_id: str
    created_at: float
    max_turns: int
    turn_index: int = 0
    is_completed: bool = False

    world_bible: Dict[str, Any] = field(default_factory=dict)
    blueprint: Dict[str, Any] = field(default_factory=dict)

    inventory: List[Item] = field(default_factory=list)
    spells: List[Spell] = field(default_factory=list)
    flags: Dict[str, Any] = field(default_factory=dict)

    summary: Optional[Dict[str, Any]] = None  # {"summary":[], "open_threads":[], "canon":[]}

    # for UI: last generated content
    last_consequence: str = ""
    last_scene: str = ""
    last_choices: List[Dict[str, str]] = field(default_factory=list)  # [{"id":"A","text":"..."}]


# ============================================================
# STORAGE (SQLite)
# ============================================================

def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def db_init(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS hero (
            hero_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            hero_class TEXT NOT NULL,
            race TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            json TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS campaign (
            campaign_id TEXT PRIMARY KEY,
            hero_id TEXT NOT NULL,
            created_at REAL NOT NULL,
            max_turns INTEGER NOT NULL,
            turn_index INTEGER NOT NULL,
            is_completed INTEGER NOT NULL,
            world_bible_json TEXT NOT NULL,
            blueprint_json TEXT NOT NULL,
            inventory_json TEXT NOT NULL,
            spells_json TEXT NOT NULL,
            flags_json TEXT NOT NULL,
            summary_json TEXT,
            last_consequence TEXT NOT NULL,
            last_scene TEXT NOT NULL,
            last_choices_json TEXT NOT NULL,
            FOREIGN KEY(hero_id) REFERENCES hero(hero_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id TEXT NOT NULL,
            turn_index INTEGER NOT NULL,
            choice_id TEXT,
            choice_text TEXT,
            response_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            FOREIGN KEY(campaign_id) REFERENCES campaign(campaign_id)
        )
    """)
    conn.commit()

def load_settings(conn: sqlite3.Connection) -> DMSettings:
    cur = conn.cursor()
    row = cur.execute("SELECT json FROM settings WHERE id = 1").fetchone()
    if not row:
        s = DMSettings()
        save_settings(conn, s)
        return s
    try:
        data = json.loads(row["json"])
    except Exception:
        s = DMSettings()
        save_settings(conn, s)
        return s
    # allow partial/missing keys
    s = DMSettings()
    for k, v in data.items():
        if hasattr(s, k):
            setattr(s, k, v)
    return s

def save_settings(conn: sqlite3.Connection, settings: DMSettings) -> None:
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO settings (id, json) VALUES (1, ?)", (json.dumps(asdict(settings), ensure_ascii=False),))
    conn.commit()

def load_hero(conn: sqlite3.Connection) -> Optional[Hero]:
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM hero LIMIT 1").fetchone()
    if not row:
        return None
    return Hero(
        hero_id=row["hero_id"],
        name=row["name"],
        hero_class=row["hero_class"],
        race=row["race"],
        created_at=row["created_at"],
    )

def save_hero(conn: sqlite3.Connection, hero: Hero) -> None:
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO hero (hero_id, name, hero_class, race, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (hero.hero_id, hero.name, hero.hero_class, hero.race, hero.created_at))
    conn.commit()

def delete_all(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM turns")
    cur.execute("DELETE FROM campaign")
    cur.execute("DELETE FROM hero")
    conn.commit()

def load_campaign(conn: sqlite3.Connection) -> Optional[Campaign]:
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM campaign LIMIT 1").fetchone()
    if not row:
        return None

    def _load_items(items_json: str) -> List[Item]:
        try:
            arr = json.loads(items_json)
            return [Item(**x) for x in arr]
        except Exception:
            return []

    def _load_spells(spells_json: str) -> List[Spell]:
        try:
            arr = json.loads(spells_json)
            return [Spell(**x) for x in arr]
        except Exception:
            return []

    try:
        world_bible = json.loads(row["world_bible_json"])
    except Exception:
        world_bible = {}
    try:
        blueprint = json.loads(row["blueprint_json"])
    except Exception:
        blueprint = {}
    try:
        flags = json.loads(row["flags_json"])
    except Exception:
        flags = {}
    try:
        summary = json.loads(row["summary_json"]) if row["summary_json"] else None
    except Exception:
        summary = None
    try:
        last_choices = json.loads(row["last_choices_json"])
    except Exception:
        last_choices = []

    return Campaign(
        campaign_id=row["campaign_id"],
        hero_id=row["hero_id"],
        created_at=row["created_at"],
        max_turns=row["max_turns"],
        turn_index=row["turn_index"],
        is_completed=bool(row["is_completed"]),
        world_bible=world_bible,
        blueprint=blueprint,
        inventory=_load_items(row["inventory_json"]),
        spells=_load_spells(row["spells_json"]),
        flags=flags,
        summary=summary,
        last_consequence=row["last_consequence"],
        last_scene=row["last_scene"],
        last_choices=last_choices,
    )

def save_campaign(conn: sqlite3.Connection, c: Campaign) -> None:
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO campaign (
            campaign_id, hero_id, created_at, max_turns, turn_index, is_completed,
            world_bible_json, blueprint_json, inventory_json, spells_json, flags_json, summary_json,
            last_consequence, last_scene, last_choices_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        c.campaign_id,
        c.hero_id,
        c.created_at,
        c.max_turns,
        c.turn_index,
        int(c.is_completed),
        json.dumps(c.world_bible, ensure_ascii=False),
        json.dumps(c.blueprint, ensure_ascii=False),
        json.dumps([asdict(i) for i in c.inventory], ensure_ascii=False),
        json.dumps([asdict(s) for s in c.spells], ensure_ascii=False),
        json.dumps(c.flags, ensure_ascii=False),
        json.dumps(c.summary, ensure_ascii=False) if c.summary else None,
        c.last_consequence or "",
        c.last_scene or "",
        json.dumps(c.last_choices, ensure_ascii=False),
    ))
    conn.commit()

def add_turn(conn: sqlite3.Connection, campaign_id: str, turn_index: int, choice_id: Optional[str], choice_text: Optional[str], response_obj: Dict[str, Any]) -> None:
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO turns (campaign_id, turn_index, choice_id, choice_text, response_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        campaign_id,
        turn_index,
        choice_id,
        choice_text,
        json.dumps(response_obj, ensure_ascii=False),
        time.time(),
    ))
    conn.commit()

def load_recent_turns(conn: sqlite3.Connection, campaign_id: str, limit: int = 3) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT turn_index, choice_id, choice_text, response_json
        FROM turns
        WHERE campaign_id = ?
        ORDER BY id DESC
        LIMIT ?
    """, (campaign_id, limit)).fetchall()
    out: List[Dict[str, Any]] = []
    for r in reversed(rows):
        try:
            resp = json.loads(r["response_json"])
        except Exception:
            resp = {}
        out.append({
            "turn_index": r["turn_index"],
            "choice_id": r["choice_id"],
            "choice_text": r["choice_text"],
            "response": resp,
        })
    return out


# ============================================================
# OPENAI CLIENT (Responses API)
# ============================================================

def get_openai_client():
    """
    Uses OPENAI_API_KEY from env or Streamlit secrets.
    """
    api_key = None
    if "OPENAI_API_KEY" in st.secrets:
        api_key = st.secrets["OPENAI_API_KEY"]
    api_key = api_key or os.environ.get("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set. Add it to env or Streamlit secrets.")

    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:
        raise RuntimeError("openai package is not installed. Run: pip install openai") from e

    return OpenAI(api_key=api_key)

def extract_first_json(text: str) -> Dict[str, Any]:
    """
    Robust-ish JSON extraction:
    - If model returns pure JSON: json.loads works.
    - If it wraps JSON in text/fences: we attempt to extract the first {...} block.
    """
    text = text.strip()

    # strip markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    # try direct
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # find first {...} (naive but effective for MVP)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end + 1]
        obj = json.loads(candidate)
        if isinstance(obj, dict):
            return obj

    raise ValueError("Could not parse JSON from model output.")

def safe_get_output_text(resp: Any) -> str:
    """
    Works with OpenAI Responses API objects.
    We try common access patterns.
    """
    # openai-python typically: resp.output_text
    if hasattr(resp, "output_text") and isinstance(resp.output_text, str):
        return resp.output_text

    # fallback: try dict-like
    if isinstance(resp, dict):
        if "output_text" in resp and isinstance(resp["output_text"], str):
            return resp["output_text"]

    # last resort: try to stringify
    return str(resp)

def call_llm_json(client, model: str, input_messages: List[Dict[str, str]], max_output_tokens: int = 1200,
                  temperature: Optional[float] = None, retries: int = 2) -> Dict[str, Any]:
    """
    Calls Responses API. Expects JSON in text output. Retries with stricter instruction if invalid.
    """
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            kwargs: Dict[str, Any] = {
                "model": model,
                "input": input_messages,
                "max_output_tokens": max_output_tokens,
            }
            if temperature is not None:
                kwargs["temperature"] = temperature

            resp = client.responses.create(**kwargs)
            text = safe_get_output_text(resp)
            return extract_first_json(text)
        except Exception as e:
            last_err = e
            # tighten the instruction on retry
            if attempt < retries:
                input_messages = input_messages + [{
                    "role": "system",
                    "content": "ВАЖНО: верни ТОЛЬКО валидный JSON, без пояснений, без markdown, без текста вокруг."
                }]
                continue
            break
    raise RuntimeError(f"LLM call failed: {last_err}")


# ============================================================
# DM ENGINE (Prompting + State application)
# ============================================================

def normalize_balance(a: float, b: float, c: float) -> Tuple[float, float, float]:
    s = max(a + b + c, 1e-9)
    return a / s, b / s, c / s

def make_base_system_prompt(settings: DMSettings) -> str:
    tone = TONE_PRESET.get(settings.tone, TONE_PRESET["classic"])
    scene_chars = LEN_PRESET.get(settings.scene_length, LEN_PRESET["medium"])["scene_chars"]
    cons_chars = LEN_PRESET.get(settings.scene_length, LEN_PRESET["medium"])["consequence_chars"]
    bc, be, bs = normalize_balance(settings.balance_combat, settings.balance_exploration, settings.balance_social)

    consequence_rule = {
        "low": "Последствия мягкие; потери редки, награды небольшие.",
        "normal": "Последствия умеренные и правдоподобные; есть риски и выгоды.",
        "high": "Последствия более жёсткие и ощутимые; риск потерь выше, но без смертельного исхода.",
    }.get(settings.consequence_intensity, "Последствия умеренные и правдоподобные; есть риски и выгоды.")

    # User-editable system prompt appended at end
    extra = settings.system_prompt.strip()
    if extra:
        extra = "\n\nДополнительные правила автора:\n" + extra

    return f"""Ты — AI-ведущий (DM) интерактивного фэнтези-приключения в духе DnD/Baldur’s Gate, но без крайностей.
Язык: русский.

Тон: {tone}

Цели:
- Консистентность NPC, локаций, фактов (не переименовывай и не противоречь уже введённому).
- Каждое решение игрока должно ощутимо влиять на историю (факты/флаги/ресурсы/отношения), но БЕЗ смерти героя.
- Не повторяйся и не пересказывай одно и то же в разных формулировках.
- Избегай лишней воды и повторов. Стиль художественный, но плотный.

Темп и баланс сцен:
- Бои/опасность: {bc:.2f}
- Исследование: {be:.2f}
- Социалка: {bs:.2f}

Последствия: {consequence_rule}

Длины (ориентиры):
- consequence_text: ~{cons_chars} символов
- scene_text: ~{scene_chars} символов

Число вариантов выбора: {settings.choices_count} (обычно 3; максимум 4).
Не используй больше 4 вариантов.

ВАЖНО: Ты обязан возвращать ТОЛЬКО валидный JSON, без markdown и пояснений.

Формат JSON для первого хода (когда ещё нет выбора):
{{
  "scene_text": "…",
  "choices": [{{"id":"A","text":"…"}}, {{"id":"B","text":"…"}}, {{"id":"C","text":"…"}}],
  "canonical_updates": {{
    "new_npcs": [{{"name":"…","role":"…","traits":["…"]}}],
    "new_locations": [{{"name":"…","type":"…"}}],
    "new_facts": ["…"]
  }}
}}

Формат JSON для следующего хода (после выбора):
{{
  "consequence_text": "…",
  "scene_text": "…",
  "choices": [{{"id":"A","text":"…"}}, {{"id":"B","text":"…"}}, {{"id":"C","text":"…"}}],
  "state_changes": {{
    "inventory_add": [{{"name":"…","description":"…","type":"consumable|weapon|quest|utility|artifact"}}],
    "inventory_remove": ["item_name_or_id"],
    "spells_add": [{{"name":"…","description":"…","type":"combat|utility|social"}}],
    "spells_remove": ["spell_name_or_id"],
    "flags_set": {{"key":"value"}},
    "flags_delta": {{"relation_x": 1}}
  }},
  "canonical_updates": {{
    "new_npcs": [],
    "new_locations": [],
    "new_facts": []
  }},
  "is_final": false
}}

Если это финальный ход:
- Верни is_final = true
- НЕ возвращай choices
- Дай завершённую развязку, закрой открытые нити
- НЕ вводи новые сюжетные линии

{extra}
""".strip()

def world_and_blueprint_prompt(hero: Hero) -> str:
    return f"""Создай базу мира и скрытый план кампании для героя.

Герой:
- Имя: {hero.name}
- Класс: {hero.hero_class}
- Раса: {hero.race}

Нужно сгенерировать:
1) world_bible: фракции, ключевые локации, общий конфликт, атмосфера.
2) campaign_blueprint: главный конфликт, 2–4 ключевых NPC (имя/роль/мотивация/секрет), 3–6 локаций, возможные финалы.
3) Затем — первую игровую сцену (scene_text) и choices.

Верни JSON строго такого вида:
{{
  "world_bible": {{...}},
  "campaign_blueprint": {{...}},
  "scene": {{
    "scene_text": "...",
    "choices": [{{"id":"A","text":"..."}},{{"id":"B","text":"..."}},{{"id":"C","text":"..."}}],
    "canonical_updates": {{ "new_npcs":[], "new_locations":[], "new_facts":[] }}
  }}
}}
"""

def next_turn_prompt(c: Campaign, hero: Hero, chosen: Dict[str, str], recent_turns: List[Dict[str, Any]], settings: DMSettings) -> str:
    """
    One call per turn: consequence + next scene + next choices.
    """
    inv = [asdict(i) for i in c.inventory]
    spl = [asdict(s) for s in c.spells]

    # compact recent turns for context (no long raw text)
    compact_recent: List[Dict[str, Any]] = []
    for t in recent_turns:
        r = t.get("response", {}) or {}
        compact_recent.append({
            "turn_index": t.get("turn_index"),
            "choice": {"id": t.get("choice_id"), "text": t.get("choice_text")},
            "consequence_text": r.get("consequence_text", ""),
            "scene_text": r.get("scene_text", ""),
        })

    # final turn signals
    final_turn = (c.turn_index >= c.max_turns - 1)

    return json.dumps({
        "hero": {"name": hero.name, "class": hero.hero_class, "race": hero.race},
        "turn": {"index": c.turn_index, "max_turns": c.max_turns, "is_final_turn": final_turn},
        "chosen": chosen,
        "inventory": inv,
        "spells": spl,
        "flags": c.flags,
        "summary": c.summary,
        "recent_turns": compact_recent,
        "world_bible": c.world_bible,
        "campaign_blueprint": c.blueprint,
        "instructions": {
            "must_be_consistent": True,
            "no_death": True,
            "soft_fail_allowed": True,
            "inventory_limit": settings.inventory_limit,
            "final_turn_rules": "If is_final_turn=true, return is_final=true and no choices. Resolve threads, no new plotlines."
        }
    }, ensure_ascii=False, indent=2)

def apply_state_changes(c: Campaign, changes: Dict[str, Any], settings: DMSettings) -> None:
    """
    Applies inventory/spells/flags changes safely.
    """
    if not changes:
        return

    # inventory remove
    remove = changes.get("inventory_remove") or []
    if isinstance(remove, list) and remove:
        remove_set = set(str(x) for x in remove)
        c.inventory = [it for it in c.inventory if it.item_id not in remove_set and it.name not in remove_set]

    # spells remove
    sremove = changes.get("spells_remove") or []
    if isinstance(sremove, list) and sremove:
        remove_set = set(str(x) for x in sremove)
        c.spells = [sp for sp in c.spells if sp.spell_id not in remove_set and sp.name not in remove_set]

    # inventory add (respect limit)
    add = changes.get("inventory_add") or []
    if isinstance(add, list) and add:
        for x in add:
            if len(c.inventory) >= settings.inventory_limit:
                break
            try:
                name = str(x.get("name", "")).strip()
                if not name:
                    continue
                desc = str(x.get("description", "")).strip()
                typ = str(x.get("type", "utility")).strip()
                item = Item(
                    item_id=f"it_{int(time.time()*1000)}_{len(c.inventory)}",
                    name=name,
                    description=desc,
                    type=typ,
                )
                c.inventory.append(item)
            except Exception:
                continue

    # spells add
    sadd = changes.get("spells_add") or []
    if isinstance(sadd, list) and sadd:
        for x in sadd:
            try:
                name = str(x.get("name", "")).strip()
                if not name:
                    continue
                desc = str(x.get("description", "")).strip()
                typ = str(x.get("type", "utility")).strip()
                sp = Spell(
                    spell_id=f"sp_{int(time.time()*1000)}_{len(c.spells)}",
                    name=name,
                    description=desc,
                    type=typ,
                )
                # avoid duplicates by name
                if any(s.name.lower() == sp.name.lower() for s in c.spells):
                    continue
                c.spells.append(sp)
            except Exception:
                continue

    # flags set
    fset = changes.get("flags_set") or {}
    if isinstance(fset, dict):
        for k, v in fset.items():
            c.flags[str(k)] = v

    # flags delta
    fdelta = changes.get("flags_delta") or {}
    if isinstance(fdelta, dict):
        for k, v in fdelta.items():
            key = str(k)
            try:
                delta = float(v)
            except Exception:
                continue
            cur = c.flags.get(key, 0)
            try:
                cur_num = float(cur)
            except Exception:
                cur_num = 0.0
            c.flags[key] = cur_num + delta

def maybe_create_summary(client, hero: Hero, c: Campaign, settings: DMSettings, conn: sqlite3.Connection) -> None:
    """
    Every SUMMARY_EVERY_TURNS turns (and not too early), ask model to summarize to keep context compact.
    Uses recent turns from DB for better fidelity.
    """
    if c.turn_index <= 0:
        return
    if c.turn_index % SUMMARY_EVERY_TURNS != 0:
        return
    if c.is_completed:
        return

    recent = load_recent_turns(conn, c.campaign_id, limit=SUMMARY_EVERY_TURNS)
    system = make_base_system_prompt(settings)
    prompt = {
        "hero": {"name": hero.name, "class": hero.hero_class, "race": hero.race},
        "turn_index": c.turn_index,
        "recent_turns": [
            {
                "turn_index": t["turn_index"],
                "choice": {"id": t["choice_id"], "text": t["choice_text"]},
                "consequence_text": (t.get("response") or {}).get("consequence_text", ""),
                "scene_text": (t.get("response") or {}).get("scene_text", ""),
            }
            for t in recent
        ],
        "inventory": [asdict(i) for i in c.inventory],
        "spells": [asdict(s) for s in c.spells],
        "flags": c.flags,
        "task": "Сделай краткое саммари последних ходов, чтобы дальше можно было продолжать без раздувания контекста.",
        "return_schema": {
            "summary": ["..."],
            "open_threads": ["..."],
            "canon": ["..."]
        }
    }

    input_messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "Сгенерируй саммари строго в JSON по схеме {summary, open_threads, canon}.\n\n" + json.dumps(prompt, ensure_ascii=False)}
    ]
    try:
        obj = call_llm_json(
            client=client,
            model=settings.model,
            input_messages=input_messages,
            max_output_tokens=600,
            temperature=settings.temperature,
            retries=2,
        )
        # minimal validation
        if isinstance(obj, dict) and "summary" in obj:
            c.summary = {
                "summary": obj.get("summary", []),
                "open_threads": obj.get("open_threads", []),
                "canon": obj.get("canon", []),
            }
    except Exception:
        # summary is optional; don't break the game
        return


# ============================================================
# GAME LOGIC
# ============================================================

def new_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time()*1000)}"

def start_hero(name: str, hero_class: str, race: str) -> Hero:
    return Hero(
        hero_id=new_id("hero"),
        name=name.strip() or "Безымянный",
        hero_class=hero_class,
        race=race,
        created_at=time.time(),
    )

def start_campaign(hero: Hero, settings: DMSettings, client) -> Campaign:
    """
    Creates new world + blueprint + first scene.
    """
    c = Campaign(
        campaign_id=new_id("camp"),
        hero_id=hero.hero_id,
        created_at=time.time(),
        max_turns=int(settings.max_turns),
        turn_index=0,
        is_completed=False,
        inventory=[],
        spells=[],
        flags={},
        summary=None,
        last_consequence="",
        last_scene="",
        last_choices=[],
    )

    system = make_base_system_prompt(settings)
    user_prompt = world_and_blueprint_prompt(hero)

    input_messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]

    obj = call_llm_json(
        client=client,
        model=settings.model,
        input_messages=input_messages,
        max_output_tokens=1400,
        temperature=settings.temperature,
        retries=2,
    )

    world_bible = obj.get("world_bible", {}) if isinstance(obj, dict) else {}
    blueprint = obj.get("campaign_blueprint", {}) if isinstance(obj, dict) else {}
    scene = obj.get("scene", {}) if isinstance(obj, dict) else {}

    # validate scene
    scene_text = str(scene.get("scene_text", "")).strip()
    choices = scene.get("choices", [])
    if not scene_text or not isinstance(choices, list) or len(choices) < 2:
        # fail safe: create a minimal fallback scene
        scene_text = "Ты открываешь глаза в шумном трактире на окраине города. За соседним столом спорят о странных исчезновениях в лесу."
        choices = [
            {"id": "A", "text": "Подойти и подслушать спор."},
            {"id": "B", "text": "Расспросить трактирщика о лесной дороге."},
            {"id": "C", "text": "Выйти наружу и осмотреть улицу."},
        ]

    # clamp choices to 4 and to settings.choices_count if possible
    choices = choices[: max(2, min(4, int(settings.choices_count)))]

    c.world_bible = world_bible if isinstance(world_bible, dict) else {}
    c.blueprint = blueprint if isinstance(blueprint, dict) else {}
    c.last_scene = scene_text
    c.last_choices = [{"id": str(x.get("id", "")).strip(), "text": str(x.get("text", "")).strip()} for x in choices]

    return c

def validate_turn_response(obj: Dict[str, Any], expect_choices: bool) -> Tuple[bool, str]:
    """
    Minimal validation with helpful error messages.
    """
    if not isinstance(obj, dict):
        return False, "Ответ не является JSON-объектом."
    if "scene_text" not in obj:
        return False, "Нет поля scene_text."
    if "consequence_text" not in obj and expect_choices:
        return False, "Нет поля consequence_text (после выбора оно должно быть)."
    if "is_final" in obj and obj.get("is_final") is True:
        # final: no choices required
        return True, ""
    if expect_choices:
        if "choices" not in obj or not isinstance(obj["choices"], list) or len(obj["choices"]) < 2:
            return False, "Нет choices или choices некорректны."
    return True, ""

def dm_next_turn(client, hero: Hero, c: Campaign, chosen: Dict[str, str], settings: DMSettings, conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    One-call-per-turn: consequence + next scene + next choices OR final.
    """
    system = make_base_system_prompt(settings)
    recent = load_recent_turns(conn, c.campaign_id, limit=3)
    prompt_payload = next_turn_prompt(c, hero, chosen, recent, settings)

    input_messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt_payload},
    ]

    max_out = 1400 if not (c.turn_index >= c.max_turns - 1) else 1700
    obj = call_llm_json(
        client=client,
        model=settings.model,
        input_messages=input_messages,
        max_output_tokens=max_out,
        temperature=settings.temperature,
        retries=2,
    )

    ok, err = validate_turn_response(obj, expect_choices=True)
    if not ok:
        # attempt one more “hard” retry with explicit error
        input_messages.append({"role": "system", "content": f"Исправь ответ. Ошибка: {err}. Верни валидный JSON по схеме."})
        obj = call_llm_json(
            client=client,
            model=settings.model,
            input_messages=input_messages,
            max_output_tokens=max_out,
            temperature=settings.temperature,
            retries=1,
        )

    return obj


# ============================================================
# UI HELPERS
# ============================================================

def pill(text: str) -> str:
    return f"<span style='padding:2px 8px;border-radius:999px;background:#f1f3f6;font-size:12px'>{text}</span>"

def render_inventory(items: List[Item]) -> None:
    if not items:
        st.caption("Пусто")
        return
    for it in items:
        icon = "🧪" if it.type == "consumable" else ("🗡️" if it.type == "weapon" else ("🧿" if it.type == "artifact" else "🎒"))
        st.markdown(f"{icon} **{it.name}**  \n<small>{it.description}</small>", unsafe_allow_html=True)

def render_spells(spells: List[Spell]) -> None:
    if not spells:
        st.caption("Нет заклинаний")
        return
    for sp in spells:
        icon = "🔥" if sp.type == "combat" else ("🧠" if sp.type == "social" else "✨")
        st.markdown(f"{icon} **{sp.name}**  \n<small>{sp.description}</small>", unsafe_allow_html=True)

def choice_button(label: str, key: str, disabled: bool = False) -> bool:
    return st.button(label, key=key, use_container_width=True, disabled=disabled)

def ensure_session_defaults() -> None:
    if "pending_settings_apply_next_turn" not in st.session_state:
        st.session_state.pending_settings_apply_next_turn = False
    if "last_choice_lock" not in st.session_state:
        st.session_state.last_choice_lock = False
    if "error" not in st.session_state:
        st.session_state.error = ""
    if "info" not in st.session_state:
        st.session_state.info = ""


# ============================================================
# STREAMLIT APP
# ============================================================

st.set_page_config(page_title=APP_TITLE, page_icon="🧙", layout="wide")
st.title(APP_TITLE)

ensure_session_defaults()

conn = db_connect()
db_init(conn)

settings = load_settings(conn)
hero = load_hero(conn)
campaign = load_campaign(conn)

# Sidebar: DM settings
with st.sidebar:
    st.header("⚙ Настройки DM")

    # These settings can change during play; apply next turn by design.
    model = st.text_input("Модель", value=settings.model)
    scene_length = st.selectbox("Длина сцен", ["short", "medium", "long"], index=["short", "medium", "long"].index(settings.scene_length))
    tone = st.selectbox("Тон", ["classic", "heroic", "dark", "light_irony"], index=["classic", "heroic", "dark", "light_irony"].index(settings.tone))

    st.subheader("🎚 Баланс")
    bc = st.slider("⚔️ Бои/опасность", 0.0, 1.0, float(settings.balance_combat), 0.01)
    be = st.slider("🧭 Исследование", 0.0, 1.0, float(settings.balance_exploration), 0.01)
    bs = st.slider("💬 Социалка", 0.0, 1.0, float(settings.balance_social), 0.01)

    consequence_intensity = st.selectbox("Жёсткость последствий", ["low", "normal", "high"], index=["low", "normal", "high"].index(settings.consequence_intensity))
    choices_count = st.selectbox("Вариантов выбора", [3, 4], index=[3, 4].index(int(settings.choices_count)))
    max_turns = st.selectbox("Длина сессии (ходов)", [10, 15, 20], index=[10, 15, 20].index(int(settings.max_turns)) if int(settings.max_turns) in [10,15,20] else 1)
    inv_limit = st.number_input("Лимит инвентаря", min_value=3, max_value=30, value=int(settings.inventory_limit), step=1)

    st.subheader("📝 Системный промпт (доп. правила)")
    system_prompt = st.text_area(" ", value=settings.system_prompt, height=160, placeholder="Например: меньше кровищи; больше детективности; избегай клише...")

    with st.expander("🔧 Advanced"):
        debug_mode = st.checkbox("Debug mode (показывать world/blueprint)", value=bool(settings.debug_mode))
        temp_enabled = st.checkbox("Указать temperature", value=settings.temperature is not None)
        temperature = None
        if temp_enabled:
            temperature = st.slider("temperature", 0.0, 1.0, float(settings.temperature if settings.temperature is not None else 0.7), 0.05)

    # Save settings button (applies next turn)
    if st.button("💾 Сохранить настройки", use_container_width=True):
        settings.model = model.strip() or DEFAULT_MODEL
        settings.scene_length = scene_length
        settings.tone = tone
        settings.balance_combat = float(bc)
        settings.balance_exploration = float(be)
        settings.balance_social = float(bs)
        settings.consequence_intensity = consequence_intensity
        settings.choices_count = int(choices_count)
        settings.max_turns = int(max_turns)
        settings.inventory_limit = int(inv_limit)
        settings.system_prompt = system_prompt
        settings.debug_mode = bool(debug_mode)
        settings.temperature = float(temperature) if temp_enabled else None

        save_settings(conn, settings)
        st.session_state.pending_settings_apply_next_turn = True
        st.success("Сохранено. Применится со следующего хода.")

    st.divider()

    st.subheader("🧹 Сброс")
    if st.button("🗑️ Сбросить всё (герой + кампания)", use_container_width=True):
        delete_all(conn)
        st.session_state.last_choice_lock = False
        st.session_state.error = ""
        st.session_state.info = "Сброшено. Создай героя заново."
        st.rerun()

# Info/Error banners
if st.session_state.info:
    st.info(st.session_state.info)
    st.session_state.info = ""
if st.session_state.error:
    st.error(st.session_state.error)

# Client creation (only when needed)
def _client_or_error():
    try:
        return get_openai_client(), ""
    except Exception as e:
        return None, str(e)

# ------------------------------------------------------------
# HERO CREATION SCREEN (no hero yet)
# ------------------------------------------------------------
if hero is None:
    st.subheader("👤 Создание героя")

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        name = st.text_input("Имя героя", value="", placeholder="Например: Арен, Лира, Торин")
    with col2:
        hero_class = st.selectbox("Класс", ["Fighter", "Rogue", "Wizard"], index=0)
    with col3:
        race = st.selectbox("Раса", ["Human", "Elf", "Dwarf"], index=0)

    st.caption("После создания герой сразу начнёт новую историю.")

    if st.button("🚀 Начать приключение", use_container_width=True):
        client, err = _client_or_error()
        if not client:
            st.session_state.error = err
            st.rerun()

        hero = start_hero(name=name, hero_class=hero_class, race=race)
        save_hero(conn, hero)

        # Start new campaign right away
        try:
            campaign = start_campaign(hero, settings, client)
            save_campaign(conn, campaign)
            add_turn(conn, campaign.campaign_id, 0, None, None, {
                "scene_text": campaign.last_scene,
                "choices": campaign.last_choices,
                "canonical_updates": {}
            })
        except Exception as e:
            st.session_state.error = f"Не удалось начать кампанию: {e}"
            st.rerun()

        st.rerun()

    st.stop()

# ------------------------------------------------------------
# CAMPAIGN INIT (hero exists but campaign not)
# ------------------------------------------------------------
if campaign is None:
    st.subheader("📜 Кампания не найдена")
    st.write("Нажми кнопку, чтобы начать новую историю.")

    if st.button("🌟 Начать новую историю", use_container_width=True):
        client, err = _client_or_error()
        if not client:
            st.session_state.error = err
            st.rerun()

        try:
            campaign = start_campaign(hero, settings, client)
            save_campaign(conn, campaign)
            add_turn(conn, campaign.campaign_id, 0, None, None, {
                "scene_text": campaign.last_scene,
                "choices": campaign.last_choices,
                "canonical_updates": {}
            })
        except Exception as e:
            st.session_state.error = f"Не удалось начать кампанию: {e}"
            st.rerun()

        st.rerun()

    st.stop()

# ------------------------------------------------------------
# MAIN ADVENTURE SCREEN
# ------------------------------------------------------------

left, right = st.columns([2.2, 1])

with right:
    st.subheader("👤 Герой")
    st.markdown(f"**{hero.name}**  \n{pill(hero.hero_class)} {pill(hero.race)}", unsafe_allow_html=True)
    st.divider()

    st.subheader(f"🎒 Инвентарь ({len(campaign.inventory)}/{settings.inventory_limit})")
    render_inventory(campaign.inventory)
    st.divider()

    st.subheader("✨ Заклинания")
    render_spells(campaign.spells)
    st.divider()

    # Debug view (hidden by default, but easy to enable)
    if settings.debug_mode:
        with st.expander("🧪 Debug: World Bible"):
            st.json(campaign.world_bible)
        with st.expander("🧪 Debug: Blueprint"):
            st.json(campaign.blueprint)
        with st.expander("🧪 Debug: Summary"):
            st.json(campaign.summary or {})

with left:
    st.subheader("📖 Приключение")

    prog = min(1.0, (campaign.turn_index / max(1, campaign.max_turns)))
    st.progress(prog, text=f"Ход {campaign.turn_index + 1} из {campaign.max_turns}")

    if campaign.last_consequence:
        st.markdown(
            f"<div style='padding:10px 12px;border-radius:12px;background:#f7f8fa;color:#111'>"
            f"⚡ {campaign.last_consequence}"
            f"</div>",
            unsafe_allow_html=True
        )

    st.markdown(
        f"<div style='padding:14px 16px;border-radius:16px;background:white;border:1px solid #111'>"
        f"{campaign.last_scene}"
        f"</div>",
        unsafe_allow_html=True
    )

    st.write("")

    # FINAL STATE
    if campaign.is_completed:
        st.success("🏁 История завершена.")
        if st.button("🔁 Начать новую историю", use_container_width=True):
            client, err = _client_or_error()
            if not client:
                st.session_state.error = err
                st.rerun()

            # wipe campaign and turns, keep hero
            cur = conn.cursor()
            cur.execute("DELETE FROM turns WHERE campaign_id = ?", (campaign.campaign_id,))
            cur.execute("DELETE FROM campaign")
            conn.commit()

            try:
                campaign = start_campaign(hero, settings, client)
                save_campaign(conn, campaign)
                add_turn(conn, campaign.campaign_id, 0, None, None, {
                    "scene_text": campaign.last_scene,
                    "choices": campaign.last_choices,
                    "canonical_updates": {}
                })
                st.session_state.last_choice_lock = False
                st.session_state.pending_settings_apply_next_turn = False
            except Exception as e:
                st.session_state.error = f"Не удалось начать новую кампанию: {e}"

            st.rerun()

        st.stop()

    # CHOICES
    disabled = bool(st.session_state.last_choice_lock)

    # Clamp to settings count (can change mid-run; applies next turn, but UI can show current)
    shown_choices = (campaign.last_choices or [])[: max(2, min(4, int(settings.choices_count)))]

    if not shown_choices:
        st.warning("Нет вариантов выбора. Попробуй начать новую историю.")
        st.stop()

    st.markdown("### 👉 Что ты сделаешь?")
    for i, ch in enumerate(shown_choices):
        label = ch.get("text", "").strip()
        cid = ch.get("id", f"opt{i}").strip() or f"opt{i}"
        if choice_button(label, key=f"choice_{campaign.campaign_id}_{campaign.turn_index}_{cid}", disabled=disabled):
            # lock to prevent double clicks
            st.session_state.last_choice_lock = True
            st.session_state.error = ""

            client, err = _client_or_error()
            if not client:
                st.session_state.error = err
                st.session_state.last_choice_lock = False
                st.rerun()

            chosen = {"id": cid, "text": label}

            try:
                # One-call-per-turn
                resp = dm_next_turn(client, hero, campaign, chosen, settings, conn)

                # record turn BEFORE applying (we store full response)
                add_turn(conn, campaign.campaign_id, campaign.turn_index + 1, cid, label, resp)

                # Apply changes
                state_changes = resp.get("state_changes", {}) if isinstance(resp, dict) else {}
                apply_state_changes(campaign, state_changes if isinstance(state_changes, dict) else {}, settings)

                # Update UI texts
                campaign.last_consequence = str(resp.get("consequence_text", "")).strip()
                campaign.last_scene = str(resp.get("scene_text", "")).strip()

                # Final?
                is_final = bool(resp.get("is_final")) if isinstance(resp, dict) else False
                campaign.turn_index += 1

                if is_final or (campaign.turn_index >= campaign.max_turns):
                    campaign.is_completed = True
                    campaign.last_choices = []
                else:
                    choices = resp.get("choices", [])
                    if not isinstance(choices, list) or len(choices) < 2:
                        # fallback safe choices if model misbehaves
                        choices = [
                            {"id": "A", "text": "Продолжить осторожно."},
                            {"id": "B", "text": "Попробовать другой подход."},
                            {"id": "C", "text": "Поговорить и узнать больше."},
                        ]
                    choices = choices[: max(2, min(4, int(settings.choices_count)))]
                    campaign.last_choices = [{"id": str(x.get("id", "")).strip(), "text": str(x.get("text", "")).strip()} for x in choices]

                # Maybe create summary (optional, doesn't break)
                maybe_create_summary(client, hero, campaign, settings, conn)

                # Persist
                save_campaign(conn, campaign)

                # unlock
                st.session_state.last_choice_lock = False
                st.rerun()

            except Exception as e:
                st.session_state.error = f"Ошибка хода: {e}"
                st.session_state.last_choice_lock = False
                st.rerun()

    st.write("")
    st.caption("Совет: если стиль «поехал», поменяй настройки DM — они применятся со следующего хода.")

# ============================================================
# RUN INSTRUCTIONS (for you)
# ============================================================
# 1) pip install streamlit openai
# 2) export OPENAI_API_KEY="..."
# 3) streamlit run app.py
#
# Optional:
# - export OPENAI_MODEL="gpt-4.1-mini"
# - export ADVENTURE_DB_PATH="/path/to/adventure.db"
