# app.py
# ============================================================
# 🧙 AI-Driven Adventure (Streamlit) — Rooms + Multi-Hero + Journal + Final Arc
#
# Key features (per GDD v1.4):
# - Rooms (room_id) isolate players on the same deployed app
# - Up to 10 heroes per room (unlimited storage conceptually, capped for MVP)
# - Always show hero selection menu on entering room (no auto-resume)
# - Delete hero (no confirmation) + deletes their last campaign/turns
# - One "last campaign" per hero (we overwrite previous; keep only the last)
# - After campaign finish: hero can start a new adventure (old overwritten)
# - DM output:
#   - Start: scene_text + choices + journal_update
#   - Turns: single turn_text (outcome+new scene) + choices + journal_update
# - Journal in sidebar: met NPCs, objectives (with strike-through on done), important events
# - Final Arc guidance to prevent "hard stop" endings
#
# Notes:
# - Single-file, structured sections, SQLite storage.
# - Requires: streamlit, openai
# ============================================================

from __future__ import annotations

import json
import os
import re
import sqlite3
import string
import time
import html as _html
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st


# ============================================================
# CONFIG
# ============================================================

APP_TITLE = "AI Adventure"
DB_PATH = os.environ.get("ADVENTURE_DB_PATH", "adventure.db")

DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
DEFAULT_MAX_TURNS = 15
DEFAULT_INV_LIMIT = 10
MAX_HEROES_PER_ROOM = 10

SUMMARY_EVERY_TURNS = 10  # optional compression (kept, but journal is primary)

FINAL_ARC_MAP_DEFAULT = {10: 3, 15: 4, 20: 5}
FINAL_ARC_FALLBACK = 4

LEN_PRESET = {
    "short": {"turn_chars": 750, "final_chars": 1050},
    "medium": {"turn_chars": 1050, "final_chars": 1400},
    "long": {"turn_chars": 1250, "final_chars": 1700},
}

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
    room_id: str
    name: str
    hero_class: str
    race: str
    created_at: float
    completed_campaigns: int = 0  # finished adventures count

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
class JournalObjective:
    text: str
    done: bool = False

@dataclass
class Journal:
    met_npcs: List[str] = field(default_factory=list)
    objectives: List[JournalObjective] = field(default_factory=list)
    important_events: List[str] = field(default_factory=list)

@dataclass
class DMSettings:
    model: str = DEFAULT_MODEL
    system_prompt: str = ""
    scene_length: str = "medium"  # short/medium/long
    tone: str = "classic"         # classic/heroic/dark/light_irony

    balance_combat: float = 0.33
    balance_exploration: float = 0.33
    balance_social: float = 0.34

    consequence_intensity: str = "normal"  # low/normal/high
    choices_count: int = 3  # 3 default, allow 4
    inventory_limit: int = DEFAULT_INV_LIMIT
    max_turns: int = DEFAULT_MAX_TURNS
    final_arc_turns: int = FINAL_ARC_FALLBACK

    debug_mode: bool = False
    temperature: Optional[float] = None

@dataclass
class Campaign:
    campaign_id: str
    room_id: str
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

    # Lightweight summary (kept optional; journal is primary)
    summary: Optional[Dict[str, Any]] = None

    journal: Journal = field(default_factory=Journal)

    # UI state
    last_turn_text: str = ""
    last_choices: List[Dict[str, str]] = field(default_factory=list)


# ============================================================
# STORAGE (SQLite) + MIGRATION
# ============================================================

def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def _table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    cur = conn.cursor()
    try:
        rows = cur.execute(f"PRAGMA table_info({table})").fetchall()
    except Exception:
        return []
    return [r["name"] for r in rows]

def db_init_and_migrate(conn: sqlite3.Connection) -> None:
    """
    Creates tables if missing and migrates older schemas safely.
    """
    cur = conn.cursor()

    # Base tables (older versions might exist)
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

    # --- Rooms migration (from earlier versions) ---
    hero_cols = _table_columns(conn, "hero")
    if "room_id" not in hero_cols:
        cur.execute("ALTER TABLE hero ADD COLUMN room_id TEXT")
        cur.execute("UPDATE hero SET room_id = 'DEFAULT' WHERE room_id IS NULL")
        conn.commit()

    # Completed campaigns counter
    hero_cols = _table_columns(conn, "hero")
    if "completed_campaigns" not in hero_cols:
        cur.execute("ALTER TABLE hero ADD COLUMN completed_campaigns INTEGER")
        cur.execute("UPDATE hero SET completed_campaigns = 0 WHERE completed_campaigns IS NULL")
        conn.commit()

    campaign_cols = _table_columns(conn, "campaign")
    if "room_id" not in campaign_cols:
        cur.execute("ALTER TABLE campaign ADD COLUMN room_id TEXT")
        cur.execute("UPDATE campaign SET room_id = 'DEFAULT' WHERE room_id IS NULL")
        conn.commit()

    # New: last_turn_text + journal_json
    campaign_cols = _table_columns(conn, "campaign")
    if "last_turn_text" not in campaign_cols:
        cur.execute("ALTER TABLE campaign ADD COLUMN last_turn_text TEXT")
        cur.execute("UPDATE campaign SET last_turn_text = '' WHERE last_turn_text IS NULL")
        conn.commit()

    campaign_cols = _table_columns(conn, "campaign")
    if "journal_json" not in campaign_cols:
        cur.execute("ALTER TABLE campaign ADD COLUMN journal_json TEXT")
        cur.execute("UPDATE campaign SET journal_json = '{}' WHERE journal_json IS NULL")
        conn.commit()

    turns_cols = _table_columns(conn, "turns")
    if "room_id" not in turns_cols:
        cur.execute("ALTER TABLE turns ADD COLUMN room_id TEXT")
        cur.execute("UPDATE turns SET room_id = 'DEFAULT' WHERE room_id IS NULL")
        conn.commit()

    turns_cols = _table_columns(conn, "turns")
    if "hero_id" not in turns_cols:
        cur.execute("ALTER TABLE turns ADD COLUMN hero_id TEXT")
        cur.execute("UPDATE turns SET hero_id = '' WHERE hero_id IS NULL")
        conn.commit()

    # Indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_hero_room ON hero(room_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_campaign_room ON campaign(room_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_campaign_hero ON campaign(hero_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_turns_room ON turns(room_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_turns_hero ON turns(hero_id)")
    conn.commit()

def _default_final_arc_turns(max_turns: int) -> int:
    val = FINAL_ARC_MAP_DEFAULT.get(int(max_turns), FINAL_ARC_FALLBACK)
    return max(2, min(int(val), max(2, int(max_turns) - 1)))

def load_settings(conn: sqlite3.Connection) -> DMSettings:
    cur = conn.cursor()
    row = cur.execute("SELECT json FROM settings WHERE id = 1").fetchone()
    if not row:
        s = DMSettings()
        s.final_arc_turns = _default_final_arc_turns(s.max_turns)
        save_settings(conn, s)
        return s

    try:
        data = json.loads(row["json"])
    except Exception:
        s = DMSettings()
        s.final_arc_turns = _default_final_arc_turns(s.max_turns)
        save_settings(conn, s)
        return s

    s = DMSettings()
    for k, v in data.items():
        if hasattr(s, k):
            setattr(s, k, v)

    # normalize
    try:
        s.max_turns = int(s.max_turns)
    except Exception:
        s.max_turns = DEFAULT_MAX_TURNS
    if "final_arc_turns" not in data:
        s.final_arc_turns = _default_final_arc_turns(s.max_turns)
    try:
        s.final_arc_turns = int(s.final_arc_turns)
    except Exception:
        s.final_arc_turns = _default_final_arc_turns(s.max_turns)
    s.final_arc_turns = max(2, min(s.final_arc_turns, max(2, s.max_turns - 1)))

    try:
        s.inventory_limit = int(s.inventory_limit)
    except Exception:
        s.inventory_limit = DEFAULT_INV_LIMIT

    try:
        s.choices_count = int(s.choices_count)
    except Exception:
        s.choices_count = 3
    s.choices_count = max(3, min(4, s.choices_count))

    return s

def save_settings(conn: sqlite3.Connection, settings: DMSettings) -> None:
    settings.max_turns = int(settings.max_turns)
    settings.final_arc_turns = max(2, min(int(settings.final_arc_turns), max(2, settings.max_turns - 1)))
    settings.choices_count = max(3, min(4, int(settings.choices_count)))
    settings.inventory_limit = int(settings.inventory_limit)

    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO settings (id, json) VALUES (1, ?)",
        (json.dumps(asdict(settings), ensure_ascii=False),),
    )
    conn.commit()


# ---------------- Heroes ----------------

def list_heroes(conn: sqlite3.Connection, room_id: str) -> List[Hero]:
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT * FROM hero WHERE room_id = ? ORDER BY created_at DESC",
        (room_id,),
    ).fetchall()
    out: List[Hero] = []
    for r in rows:
        out.append(Hero(
            hero_id=r["hero_id"],
            room_id=r["room_id"],
            name=r["name"],
            hero_class=r["hero_class"],
            race=r["race"],
            created_at=r["created_at"],
            completed_campaigns=int(r["completed_campaigns"] or 0),
        ))
    return out

def get_hero(conn: sqlite3.Connection, room_id: str, hero_id: str) -> Optional[Hero]:
    cur = conn.cursor()
    row = cur.execute(
        "SELECT * FROM hero WHERE room_id = ? AND hero_id = ?",
        (room_id, hero_id),
    ).fetchone()
    if not row:
        return None
    return Hero(
        hero_id=row["hero_id"],
        room_id=row["room_id"],
        name=row["name"],
        hero_class=row["hero_class"],
        race=row["race"],
        created_at=row["created_at"],
        completed_campaigns=int(row["completed_campaigns"] or 0),
    )

def save_hero(conn: sqlite3.Connection, hero: Hero) -> None:
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO hero (hero_id, room_id, name, hero_class, race, created_at, completed_campaigns)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (hero.hero_id, hero.room_id, hero.name, hero.hero_class, hero.race, hero.created_at, int(hero.completed_campaigns)))
    conn.commit()

def increment_hero_completed(conn: sqlite3.Connection, room_id: str, hero_id: str) -> None:
    cur = conn.cursor()
    cur.execute("""
        UPDATE hero SET completed_campaigns = COALESCE(completed_campaigns, 0) + 1
        WHERE room_id = ? AND hero_id = ?
    """, (room_id, hero_id))
    conn.commit()

def delete_hero(conn: sqlite3.Connection, room_id: str, hero_id: str) -> None:
    # delete turns/campaign for this hero
    delete_campaign_for_hero(conn, room_id, hero_id)
    cur = conn.cursor()
    cur.execute("DELETE FROM hero WHERE room_id = ? AND hero_id = ?", (room_id, hero_id))
    conn.commit()

def count_heroes(conn: sqlite3.Connection, room_id: str) -> int:
    cur = conn.cursor()
    row = cur.execute("SELECT COUNT(*) AS c FROM hero WHERE room_id = ?", (room_id,)).fetchone()
    return int(row["c"] if row else 0)


# ---------------- Campaigns ----------------

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

def _load_journal(journal_json: str) -> Journal:
    try:
        obj = json.loads(journal_json) if journal_json else {}
    except Exception:
        obj = {}
    met = obj.get("met_npcs", []) if isinstance(obj, dict) else []
    events = obj.get("important_events", []) if isinstance(obj, dict) else []
    objectives_raw = obj.get("objectives", []) if isinstance(obj, dict) else []

    objectives: List[JournalObjective] = []
    if isinstance(objectives_raw, list):
        for it in objectives_raw:
            if isinstance(it, dict) and "text" in it:
                objectives.append(JournalObjective(text=str(it.get("text", "")).strip(), done=bool(it.get("done", False))))
            elif isinstance(it, str):
                objectives.append(JournalObjective(text=it.strip(), done=False))

    return Journal(
        met_npcs=[str(x).strip() for x in met if str(x).strip()],
        objectives=[o for o in objectives if o.text],
        important_events=[str(x).strip() for x in events if str(x).strip()],
    )

def _dump_journal(j: Journal) -> str:
    return json.dumps({
        "met_npcs": j.met_npcs,
        "objectives": [asdict(o) for o in j.objectives],
        "important_events": j.important_events,
    }, ensure_ascii=False)

def load_campaign_for_hero(conn: sqlite3.Connection, room_id: str, hero_id: str) -> Optional[Campaign]:
    cur = conn.cursor()
    row = cur.execute(
        "SELECT * FROM campaign WHERE room_id = ? AND hero_id = ? ORDER BY created_at DESC LIMIT 1",
        (room_id, hero_id),
    ).fetchone()
    if not row:
        return None

    # Backward compat: if last_turn_text is empty, try composing from old fields
    last_turn_text = (row["last_turn_text"] or "").strip()
    if not last_turn_text:
        old_cons = (row["last_consequence"] or "").strip()
        old_scene = (row["last_scene"] or "").strip()
        if old_cons and old_scene:
            last_turn_text = f"{old_cons}\n\n{old_scene}"
        else:
            last_turn_text = old_scene or old_cons

    summary = None
    try:
        summary = json.loads(row["summary_json"]) if row["summary_json"] else None
    except Exception:
        summary = None

    return Campaign(
        campaign_id=row["campaign_id"],
        room_id=row["room_id"],
        hero_id=row["hero_id"],
        created_at=row["created_at"],
        max_turns=int(row["max_turns"]),
        turn_index=int(row["turn_index"]),
        is_completed=bool(row["is_completed"]),
        world_bible=json.loads(row["world_bible_json"]) if row["world_bible_json"] else {},
        blueprint=json.loads(row["blueprint_json"]) if row["blueprint_json"] else {},
        inventory=_load_items(row["inventory_json"]),
        spells=_load_spells(row["spells_json"]),
        flags=json.loads(row["flags_json"]) if row["flags_json"] else {},
        summary=summary if isinstance(summary, (dict, type(None))) else None,
        journal=_load_journal(row["journal_json"] if "journal_json" in row.keys() else "{}"),
        last_turn_text=last_turn_text,
        last_choices=json.loads(row["last_choices_json"]) if row["last_choices_json"] else [],
    )

def save_campaign(conn: sqlite3.Connection, c: Campaign) -> None:
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO campaign (
            campaign_id, room_id, hero_id, created_at, max_turns, turn_index, is_completed,
            world_bible_json, blueprint_json, inventory_json, spells_json, flags_json, summary_json,
            last_consequence, last_scene, last_choices_json, last_turn_text, journal_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        c.campaign_id,
        c.room_id,
        c.hero_id,
        c.created_at,
        int(c.max_turns),
        int(c.turn_index),
        int(c.is_completed),
        json.dumps(c.world_bible, ensure_ascii=False),
        json.dumps(c.blueprint, ensure_ascii=False),
        json.dumps([asdict(i) for i in c.inventory], ensure_ascii=False),
        json.dumps([asdict(s) for s in c.spells], ensure_ascii=False),
        json.dumps(c.flags, ensure_ascii=False),
        json.dumps(c.summary, ensure_ascii=False) if c.summary else None,
        "",  # legacy last_consequence (unused)
        "",  # legacy last_scene (unused)
        json.dumps(c.last_choices, ensure_ascii=False),
        c.last_turn_text or "",
        _dump_journal(c.journal),
    ))
    conn.commit()

def delete_campaign_for_hero(conn: sqlite3.Connection, room_id: str, hero_id: str) -> None:
    cur = conn.cursor()
    # Find last campaign id to delete turns reliably (even if multiple rows exist from older versions)
    rows = cur.execute(
        "SELECT campaign_id FROM campaign WHERE room_id = ? AND hero_id = ?",
        (room_id, hero_id),
    ).fetchall()
    for r in rows:
        cid = r["campaign_id"]
        cur.execute("DELETE FROM turns WHERE room_id = ? AND hero_id = ? AND campaign_id = ?", (room_id, hero_id, cid))
    cur.execute("DELETE FROM campaign WHERE room_id = ? AND hero_id = ?", (room_id, hero_id))
    conn.commit()

def add_turn(
    conn: sqlite3.Connection,
    room_id: str,
    hero_id: str,
    campaign_id: str,
    turn_index: int,
    choice_id: Optional[str],
    choice_text: Optional[str],
    response_obj: Dict[str, Any]
) -> None:
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO turns (room_id, hero_id, campaign_id, turn_index, choice_id, choice_text, response_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        room_id,
        hero_id,
        campaign_id,
        int(turn_index),
        choice_id,
        choice_text,
        json.dumps(response_obj, ensure_ascii=False),
        time.time(),
    ))
    conn.commit()

def load_recent_turns(conn: sqlite3.Connection, room_id: str, hero_id: str, campaign_id: str, limit: int = 3) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT turn_index, choice_id, choice_text, response_json
        FROM turns
        WHERE room_id = ? AND hero_id = ? AND campaign_id = ?
        ORDER BY id DESC
        LIMIT ?
    """, (room_id, hero_id, campaign_id, int(limit))).fetchall()

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
# ROOM HELPERS
# ============================================================

def normalize_room_id(s: str) -> str:
    s = (s or "").strip().upper()
    s = re.sub(r"[^A-Z0-9_-]", "", s)
    return s[:24]

def generate_room_id(length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    t = int(time.time() * 1000)
    out = []
    for i in range(length):
        out.append(alphabet[(t + i * 37) % len(alphabet)])
        t = (t * 1103515245 + 12345) & 0x7FFFFFFF
    return "".join(out)

def new_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time()*1000)}"


# ============================================================
# OPENAI CLIENT (Responses API)
# ============================================================

def get_openai_client():
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

def safe_get_output_text(resp: Any) -> str:
    if hasattr(resp, "output_text") and isinstance(resp.output_text, str):
        return resp.output_text
    if isinstance(resp, dict) and "output_text" in resp and isinstance(resp["output_text"], str):
        return resp["output_text"]
    return str(resp)

def extract_first_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end + 1]
        obj = json.loads(candidate)
        if isinstance(obj, dict):
            return obj

    raise ValueError("Could not parse JSON from model output.")

def call_llm_json(
    client,
    model: str,
    input_messages: List[Dict[str, str]],
    max_output_tokens: int = 1400,
    temperature: Optional[float] = None,
    retries: int = 2
) -> Dict[str, Any]:
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            kwargs: Dict[str, Any] = {
                "model": model,
                "input": input_messages,
                "max_output_tokens": int(max_output_tokens),
            }
            if temperature is not None:
                kwargs["temperature"] = float(temperature)

            resp = client.responses.create(**kwargs)
            text = safe_get_output_text(resp)
            return extract_first_json(text)

        except Exception as e:
            last_err = e
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
    turn_chars = LEN_PRESET.get(settings.scene_length, LEN_PRESET["medium"])["turn_chars"]
    final_chars = LEN_PRESET.get(settings.scene_length, LEN_PRESET["medium"])["final_chars"]
    bc, be, bs = normalize_balance(settings.balance_combat, settings.balance_exploration, settings.balance_social)

    consequence_rule = {
        "low": "Последствия мягкие; потери редки, награды небольшие.",
        "normal": "Последствия умеренные и правдоподобные; есть риски и выгоды.",
        "high": "Последствия более жёсткие и ощутимые; риск потерь выше, но без смертельного исхода.",
    }.get(settings.consequence_intensity, "Последствия умеренные и правдоподобные; есть риски и выгоды.")

    extra = settings.system_prompt.strip()
    if extra:
        extra = "\n\nДополнительные правила автора:\n" + extra

    return f"""Ты — AI-ведущий (DM) интерактивного фэнтези-приключения в духе DnD/Baldur’s Gate, но это НАРРАТИВНАЯ КНИГА.
Язык: русский.

Тон: {tone}

Ключевые принципы:
- Консистентность NPC, локаций, фактов (не переименовывай и не противоречь уже введённому).
- Каждое решение игрока ощутимо влияет на историю (факты/флаги/ресурсы/отношения), но БЕЗ смерти героя.
- Мягкий провал допустим.
- Не повторяйся. Не пересказывай одно и то же разными словами в одном тексте.
- Запрещены мета-фразы: «перед вами выбор», «не спешите», «тактическая линия определит исход» и т.п.
- Избегай двойных кавычек \". Если нужны кавычки — используй «ёлочки».

Голос и POV:
- Всегда обращайся к игроку во 2-м лице: «ты». Не описывай героя в третьем лице.
  Плохо: «Арен делает шаг…». Хорошо: «Ты делаешь шаг…».
- NPC можно описывать в третьем лице. NPC могут обращаться к герою по имени и упоминать его, если нужно.

Формат текста хода:
- Делай 2–3 коротких логичных абзаца (переносы строк по смыслу), без увеличения объёма.
- Каждый абзац должен добавлять новую информацию/ставку/изменение.

Темп и баланс сцен:
- Бои/опасность: {bc:.2f}
- Исследование: {be:.2f}
- Социалка: {bs:.2f}

Последствия: {consequence_rule}

Стиль подачи хода:
- Всегда один текстовый блок (turn_text): исход выбора + новое событие.
- 2–3 абзаца максимум.
- Ориентир длины turn_text: ~{turn_chars} символов.
- Финал: до ~{final_chars} символов.

NPC при первой встрече:
- Если NPC встречается впервые (его нет в journal.met_npcs), добавь ОДНО короткое предложение описания в turn_text
  и добавь NPC в journal_update.met_add. Далее не повторяй описание.

Враги:
- Избегай абстракций угрозы («тени», «нечто», «странные существа») вместо конкретики.
  Используй конкретных противников из world_bible/enemies, либо вводи врага так, чтобы у него были
  ясные приметы, поведение и тип угрозы.

Ключевые выборы и story_score (скрыто от игрока):
- В кампании есть скрытый счёт story_score в диапазоне [-10; +10]. Игрок не видит число, но должен
  примерно понимать ставки.
- Иногда payload укажет, что сейчас KEY CHOICE (key_choice_due=true). Тогда варианты выбора должны быть
  «ключевыми»: с ясными ставками и возможными хорошими/плохими последствиями.
- Обновление story_score делай ТОЛЬКО на ключевых выборах через state_changes.flags_delta.story_score.
  Используй base_delta из множества {{-2,-1,0,+1,+2}} и умножай на вес по фазе:
  - NORMAL: w=1
  - FINAL_ARC: w=2
  - FINAL_TURN: w=0
  Формула: delta = base_delta * w.
  Пример: base_delta=+1 в FINAL_ARC => story_score += +2.

Архетипы финала (фэнтези) по story_score:
- >= +4: Triumphant Victory
- +2..+3: Bittersweet / Noble Sacrifice (опирайся на факты/флаги)
- -1..+1: Pyrrhic / Mixed
- -2..-3: Tragic Failure
- <= -4: Corrupted Win / Dark Ascendancy (если решения вели к «тёмной» победе), иначе Tragic Failure

Бои:
- Боевые моменты должны быть конкретными: действие героя → ответ противника → итог/последствие.
- Стиль боя зависит от класса:
  - Fighter: физическая конкретика, позиция, оружие.
  - Rogue: скрытность, трюки, преимущества.
  - Wizard: магические эффекты, контроль, ритуалы.

ВАЖНО: возвращай ТОЛЬКО валидный JSON, без markdown и пояснений.

Схема JSON для старта кампании (первый ход):
{{
  "scene_text": "…",
  "choices": [{{"id":"A","text":"…"}},{{"id":"B","text":"…"}},{{"id":"C","text":"…"}}],
  "canonical_updates": {{
    "new_npcs": [{{"name":"…","role":"…","short_description":"…"}}],
    "new_locations": [{{"name":"…","type":"…"}}],
    "new_facts": ["…"]
  }},
  "journal_update": {{
    "met_add": ["..."],
    "objectives_add": ["..."],
    "objectives_done": [],
    "events_add": ["..."]
  }}
}}

Схема JSON для обычного хода:
{{
  "turn_text": "…",
  "choices": [{{"id":"A","text":"…"}},{{"id":"B","text":"…"}},{{"id":"C","text":"…"}}],
  "state_changes": {{
    "inventory_add": [{{"name":"…","description":"…","type":"consumable|weapon|quest|utility|artifact"}}],
    "inventory_remove": ["item_name_or_id"],
    "spells_add": [{{"name":"…","description":"…","type":"combat|utility|social"}}],
    "spells_remove": ["spell_name_or_id"],
    "flags_set": {{"key":"value"}},
    "flags_delta": {{"story_score": 0, "relation_x": 1}}
  }},
  "canonical_updates": {{
    "new_npcs": [],
    "new_locations": [],
    "new_facts": []
  }},
  "journal_update": {{
    "met_add": [],
    "objectives_add": [],
    "objectives_done": [],
    "events_add": []
  }},
  "is_final": false
}}

Финальный ход:
- Верни is_final=true
- НЕ возвращай choices
- Дай развязку + короткий эпилог
- Закрой цели и нити (используй journal.objectives и journal.important_events)
- Не вводи новые крупные сюжетные линии
- Выбери архетип финала на основе story_score и фактов/флагов

{extra}
""".strip()

def world_and_blueprint_prompt(hero: Hero) -> str:
    return f"""Создай базу мира и скрытый план кампании для героя.

Герой:
- Имя: {hero.name}
- Класс: {hero.hero_class}
- Раса: {hero.race}

Нужно:
1) world_bible: фракции, ключевые локации, общий конфликт, атмосфера.
2) Враги (важно для конкретики):
   - enemy_archetypes: 6–10 типовых противников. Каждый: name, visual(1–2 детали), behavior, tell(признак угрозы), stakes(тип угрозы).
   - key_antagonists: 2–3 ключевых антагониста. Для каждого: name, motivation, weakness, attitude_to_hero, hidden_truth, signature, minions.
   Часть противников может не встретиться, но все должны органично вписываться в сеттинг.
3) campaign_blueprint: главный конфликт, 2–4 ключевых NPC (имя/роль/мотивация/секрет), 3–6 локаций, возможные финалы.
4) Затем — первую сцену (scene_text) и choices.
5) Также — краткий journal_update для старта (цели/события).

Верни JSON строго такого вида:
{{
  "world_bible": {{
    "...": "...",
    "enemies": {{
      "enemy_archetypes": [{{"name":"...","visual":"...","behavior":"...","tell":"...","stakes":"..."}}],
      "key_antagonists": [{{"name":"...","motivation":"...","weakness":"...","attitude_to_hero":"...","hidden_truth":"...","signature":"...","minions":["..."]}}]
    }}
  }},
  "campaign_blueprint": {{...}},
  "scene": {{
    "scene_text": "...",
    "choices": [{{"id":"A","text":"..."}},{{"id":"B","text":"..."}},{{"id":"C","text":"..."}}],
    "canonical_updates": {{ "new_npcs":[], "new_locations":[], "new_facts":[] }},
    "journal_update": {{ "met_add":[], "objectives_add":[], "objectives_done":[], "events_add":[] }}
  }}
}}
"""

def _final_phase(c: Campaign, settings: DMSettings) -> Tuple[str, int, int]:
    remaining_after_next = c.max_turns - (c.turn_index + 1)
    final_arc_turns = max(2, min(int(settings.final_arc_turns), max(2, c.max_turns - 1)))
    if remaining_after_next <= 0:
        return "FINAL_TURN", remaining_after_next, final_arc_turns
    if remaining_after_next <= final_arc_turns:
        return "FINAL_ARC", remaining_after_next, final_arc_turns
    return "NORMAL", remaining_after_next, final_arc_turns

def next_turn_prompt(
    c: Campaign,
    hero: Hero,
    chosen: Dict[str, str],
    recent_turns: List[Dict[str, Any]],
    settings: DMSettings
) -> str:
    inv = [asdict(i) for i in c.inventory]
    spl = [asdict(s) for s in c.spells]

    compact_recent: List[Dict[str, Any]] = []
    for t in recent_turns:
        r = t.get("response", {}) or {}
        compact_recent.append({
            "turn_index": t.get("turn_index"),
            "choice": {"id": t.get("choice_id"), "text": t.get("choice_text")},
            "turn_text": r.get("turn_text") or r.get("scene_text") or "",
        })

    phase, remaining_after_next, final_arc_turns = _final_phase(c, settings)

    phase_guidance = ""
    if phase == "FINAL_ARC":
        phase_guidance = (
            f"FINAL ARC MODE: до финала осталось {remaining_after_next} ход(а). "
            "Веди к кульминации и развязке на последнем ходу. "
            "Не вводи новых крупных линий/главных злодеев/фракций. "
            "Закрывай цели и нити из journal."
        )
    elif phase == "FINAL_TURN":
        phase_guidance = (
            "FINAL TURN: это последний ход. Дай развязку и эпилог. "
            "Закрой цели/нити из journal. Верни is_final=true и без choices."
        )

    # Key choice planner (from flags); key choices start from turn_index >= 1
    key_turns: List[int] = []
    try:
        key_turns = list(c.flags.get("key_choice_turns", []) or [])
    except Exception:
        key_turns = []
    key_done: set[int] = set()
    try:
        key_done = set(int(x) for x in (c.flags.get("key_choices_done", []) or []))
    except Exception:
        key_done = set()
    next_turn_index = int(c.turn_index + 1)
    key_choice_due = (next_turn_index in set(int(x) for x in key_turns)) and (next_turn_index not in key_done)

    payload = {
        "hero": {"name": hero.name, "class": hero.hero_class, "race": hero.race},
        "turn": {
            "index": c.turn_index,
            "max_turns": c.max_turns,
            "phase": phase,
            "remaining_after_next": remaining_after_next,
            "final_arc_turns": final_arc_turns
        },
        "chosen": chosen,
        "inventory": inv,
        "spells": spl,
        "flags": c.flags,
        "journal": json.loads(_dump_journal(c.journal)),
        "summary": c.summary,
        "recent_turns": compact_recent,
        "world_bible": c.world_bible,
        "campaign_blueprint": c.blueprint,
        "instructions": {
            "must_be_consistent": True,
            "no_death": True,
            "soft_fail_allowed": True,
            "inventory_limit": settings.inventory_limit,
            "phase_guidance": phase_guidance,
            "key_choice_due": bool(key_choice_due),
            "key_choice_turns": [int(x) for x in key_turns],
            "story_score": float(c.flags.get("story_score", 0.0) or 0.0),
        }
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)

def apply_state_changes(c: Campaign, changes: Dict[str, Any], settings: DMSettings) -> None:
    if not changes:
        return

    remove = changes.get("inventory_remove") or []
    if isinstance(remove, list) and remove:
        remove_set = set(str(x) for x in remove)
        c.inventory = [it for it in c.inventory if it.item_id not in remove_set and it.name not in remove_set]

    sremove = changes.get("spells_remove") or []
    if isinstance(sremove, list) and sremove:
        remove_set = set(str(x) for x in sremove)
        c.spells = [sp for sp in c.spells if sp.spell_id not in remove_set and sp.name not in remove_set]

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
                c.inventory.append(Item(
                    item_id=f"it_{int(time.time()*1000)}_{len(c.inventory)}",
                    name=name,
                    description=desc,
                    type=typ,
                ))
            except Exception:
                continue

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
                if any(s.name.lower() == sp.name.lower() for s in c.spells):
                    continue
                c.spells.append(sp)
            except Exception:
                continue

    fset = changes.get("flags_set") or {}
    if isinstance(fset, dict):
        for k, v in fset.items():
            c.flags[str(k)] = v

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
            # Clamp story_score to [-10, +10]
            if key == "story_score":
                try:
                    c.flags[key] = max(-10.0, min(10.0, float(c.flags[key])))
                except Exception:
                    c.flags[key] = 0.0

def _dedup_list_keep_order(xs: List[str], limit: Optional[int] = None) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in xs:
        s = str(x).strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if limit is not None and len(out) >= limit:
            break
    return out

def apply_journal_update(c: Campaign, update: Dict[str, Any]) -> None:
    if not isinstance(update, dict):
        return

    met_add = update.get("met_add") or []
    objectives_add = update.get("objectives_add") or []
    objectives_done = update.get("objectives_done") or []
    events_add = update.get("events_add") or []

    # met_npcs
    if isinstance(met_add, list):
        merged = c.journal.met_npcs + [str(x) for x in met_add]
        c.journal.met_npcs = _dedup_list_keep_order(merged)

    # objectives add
    if isinstance(objectives_add, list):
        existing = {o.text.strip().lower() for o in c.journal.objectives}
        for x in objectives_add:
            t = str(x).strip()
            if not t:
                continue
            if t.lower() in existing:
                continue
            c.journal.objectives.append(JournalObjective(text=t, done=False))
            existing.add(t.lower())

    # objectives done (mark as done if matches text)
    if isinstance(objectives_done, list):
        done_set = {str(x).strip().lower() for x in objectives_done if str(x).strip()}
        if done_set:
            for o in c.journal.objectives:
                if o.text.strip().lower() in done_set:
                    o.done = True

    # important events (cap to 15)
    if isinstance(events_add, list):
        merged = c.journal.important_events + [str(x) for x in events_add]
        c.journal.important_events = _dedup_list_keep_order(merged, limit=15)

def maybe_create_summary(
    client,
    hero: Hero,
    c: Campaign,
    settings: DMSettings,
    conn: sqlite3.Connection
) -> None:
    # Optional: keep as a safety; journal is main now
    if c.turn_index <= 0:
        return
    if c.turn_index % SUMMARY_EVERY_TURNS != 0:
        return
    if c.is_completed:
        return

    recent = load_recent_turns(conn, c.room_id, hero.hero_id, c.campaign_id, limit=SUMMARY_EVERY_TURNS)
    system = make_base_system_prompt(settings)
    payload = {
        "hero": {"name": hero.name, "class": hero.hero_class, "race": hero.race},
        "turn_index": c.turn_index,
        "recent_turns": [
            {
                "turn_index": t["turn_index"],
                "choice": {"id": t["choice_id"], "text": t["choice_text"]},
                "turn_text": (t.get("response") or {}).get("turn_text") or "",
            } for t in recent
        ],
        "journal": json.loads(_dump_journal(c.journal)),
        "task": "Сделай краткое саммари последних ходов (без воды). Верни JSON: {summary, open_threads, canon}.",
        "schema": {"summary": [], "open_threads": [], "canon": []}
    }
    msgs = [
        {"role": "system", "content": system},
        {"role": "user", "content": "Верни строго JSON {summary, open_threads, canon}.\n\n" + json.dumps(payload, ensure_ascii=False)}
    ]
    try:
        obj = call_llm_json(client, settings.model, msgs, max_output_tokens=600, temperature=settings.temperature, retries=2)
        if isinstance(obj, dict) and "summary" in obj:
            c.summary = {
                "summary": obj.get("summary", []),
                "open_threads": obj.get("open_threads", []),
                "canon": obj.get("canon", []),
            }
    except Exception:
        return


# ============================================================
# GAME LOGIC (Create/Start Campaign)
# ============================================================

def start_hero(room_id: str, name: str, hero_class: str, race: str) -> Hero:
    return Hero(
        hero_id=new_id("hero"),
        room_id=room_id,
        name=name.strip() or "Безымянный",
        hero_class=hero_class,
        race=race,
        created_at=time.time(),
        completed_campaigns=0,
    )

def start_campaign(room_id: str, hero: Hero, settings: DMSettings, client) -> Campaign:
    # overwrite: ensure only one last campaign exists (delete old)
    # (call-site is responsible for deletion)
    c = Campaign(
        campaign_id=new_id("camp"),
        room_id=room_id,
        hero_id=hero.hero_id,
        created_at=time.time(),
        max_turns=int(settings.max_turns),
        turn_index=0,
        is_completed=False,
        inventory=[],
        spells=[],
        flags={},
        # Hidden narrative meta (GDD v2.0)
        # story_score is clamped to [-10, +10]
        # key_choice_turns lists turn_index values where DM should produce a KEY CHOICE
        summary=None,
        journal=Journal(),
        last_turn_text="",
        last_choices=[],
    )

    # Initialize hidden narrative meta
    c.flags = c.flags or {}
    c.flags.setdefault("story_score", 0.0)

    # Plan key choices: round(max_turns/5), spread across NORMAL and FINAL_ARC (not on final turn)
    key_target = max(1, int(round(c.max_turns / 5)))
    final_arc_turns = max(2, min(int(settings.final_arc_turns), max(2, c.max_turns - 1)))
    last_non_final = max(0, c.max_turns - 2)  # avoid final turn (max_turns-1)

    turns: List[int] = []
    if key_target == 1:
        turns = [max(1, min(last_non_final, c.max_turns // 2))]
    else:
        t1 = max(1, min(last_non_final, c.max_turns // 2))
        turns.append(t1)
        start_final_arc_at = max(1, c.max_turns - final_arc_turns)
        t2 = max(1, min(last_non_final, start_final_arc_at - 1))
        if t2 not in turns:
            turns.append(t2)
        for k in range(2, key_target):
            span = max(1, (last_non_final - start_final_arc_at + 1))
            denom = max(1, (key_target - 2))
            pos = start_final_arc_at + int(round((k - 1) * (span - 1) / denom))
            pos = max(start_final_arc_at, min(last_non_final, pos))
            if pos not in turns:
                turns.append(pos)
    turns = sorted(set(int(x) for x in turns if int(x) >= 1))
    c.flags["key_choice_turns"] = turns
    c.flags.setdefault("key_choices_done", [])

    system = make_base_system_prompt(settings)
    user_prompt = world_and_blueprint_prompt(hero)
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user_prompt}]

    obj = call_llm_json(
        client=client,
        model=settings.model,
        input_messages=msgs,
        max_output_tokens=1600,
        temperature=settings.temperature,
        retries=2,
    )

    world_bible = obj.get("world_bible", {}) if isinstance(obj, dict) else {}
    blueprint = obj.get("campaign_blueprint", {}) if isinstance(obj, dict) else {}
    scene = obj.get("scene", {}) if isinstance(obj, dict) else {}

    scene_text = str(scene.get("scene_text", "")).strip()
    choices = scene.get("choices", [])
    canon = scene.get("canonical_updates", {}) if isinstance(scene, dict) else {}
    jupd = scene.get("journal_update", {}) if isinstance(scene, dict) else {}

    if not scene_text or not isinstance(choices, list) or len(choices) < 2:
        scene_text = "Ты приходишь в себя в тёплом свете трактирной свечи. За стеной слышен спор о пропавших людях и чём-то, что шепчет из леса."
        choices = [
            {"id": "A", "text": "Подойти ближе и прислушаться к спору."},
            {"id": "B", "text": "Расспросить трактирщика о слухах."},
            {"id": "C", "text": "Выйти наружу и осмотреть улицу."},
        ]
        canon = {"new_npcs": [], "new_locations": [], "new_facts": []}
        jupd = {"met_add": [], "objectives_add": ["Разобраться, что происходит с пропавшими"], "objectives_done": [], "events_add": []}

    c.world_bible = world_bible if isinstance(world_bible, dict) else {}
    c.blueprint = blueprint if isinstance(blueprint, dict) else {}
    c.last_turn_text = scene_text
    c.last_choices = [
        {"id": str(x.get("id", "")).strip(), "text": str(x.get("text", "")).strip()}
        for x in choices
    ][: max(2, min(4, int(settings.choices_count)))]

    apply_journal_update(c, jupd if isinstance(jupd, dict) else {})
    # Also: if canonical updates includes new_npcs, add to journal met if journal_update forgot
    if isinstance(canon, dict):
        nn = canon.get("new_npcs") or []
        if isinstance(nn, list):
            for npc in nn:
                if isinstance(npc, dict) and npc.get("name"):
                    nm = str(npc["name"]).strip()
                    if nm and nm not in c.journal.met_npcs:
                        # DM should still decide via journal_update, but this is a safety net:
                        pass

    return c

def validate_turn_response(obj: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(obj, dict):
        return False, "Ответ не JSON-объект."
    is_final = bool(obj.get("is_final")) if "is_final" in obj else False
    if is_final:
        if "turn_text" not in obj:
            return False, "Финал: нет turn_text."
        return True, ""
    if "turn_text" not in obj:
        return False, "Нет turn_text."
    if "choices" not in obj or not isinstance(obj["choices"], list) or len(obj["choices"]) < 2:
        return False, "Нет choices или choices некорректны."
    return True, ""

def dm_next_turn(
    client,
    room_id: str,
    hero: Hero,
    c: Campaign,
    chosen: Dict[str, str],
    settings: DMSettings,
    conn: sqlite3.Connection
) -> Dict[str, Any]:
    system = make_base_system_prompt(settings)
    recent = load_recent_turns(conn, room_id, hero.hero_id, c.campaign_id, limit=3)
    payload = next_turn_prompt(c, hero, chosen, recent, settings)
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": payload}]

    max_out = 1400
    obj = call_llm_json(client, settings.model, msgs, max_output_tokens=max_out, temperature=settings.temperature, retries=2)

    ok, err = validate_turn_response(obj)
    if not ok:
        msgs.append({"role": "system", "content": f"Исправь ответ. Ошибка: {err}. Верни валидный JSON по схеме."})
        obj = call_llm_json(client, settings.model, msgs, max_output_tokens=max_out, temperature=settings.temperature, retries=1)

    return obj


# ============================================================
# UI HELPERS
# ============================================================

def pill(text: str) -> str:
    return (
        "<span style='padding:2px 8px;border-radius:999px;"
        "background:#f1f3f6;font-size:12px;color:#111'>"
        f"{text}"
        "</span>"
    )

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

def render_journal(j: Journal, show_title: bool = True) -> None:
    if show_title:
        st.subheader("📓 Журнал")

    st.markdown("**Встречены:**")
    if j.met_npcs:
        for n in j.met_npcs[:20]:
            st.write(f"• {n}")
    else:
        st.caption("Пока никого")

    st.markdown("**Цели:**")
    if j.objectives:
        for o in j.objectives[:20]:
            if o.done:
                st.markdown(f"• <s>{o.text}</s>", unsafe_allow_html=True)
            else:
                st.write(f"• {o.text}")
    else:
        st.caption("Пока нет")

def choice_button(label: str, key: str, disabled: bool = False) -> bool:
    return st.button(label, key=key, use_container_width=True, disabled=disabled)

def ensure_session_defaults() -> None:
    if "room_id" not in st.session_state:
        st.session_state.room_id = ""
    if "view" not in st.session_state:
        st.session_state.view = "room"  # room -> menu -> hero_creation/adventure
    if "active_hero_id" not in st.session_state:
        st.session_state.active_hero_id = ""
    if "last_choice_lock" not in st.session_state:
        st.session_state.last_choice_lock = False
    if "error" not in st.session_state:
        st.session_state.error = ""
    if "info" not in st.session_state:
        st.session_state.info = ""
    # Style-only UI state: prevent re-typing the same turn on rerun
    if "typed_turn_index" not in st.session_state:
        st.session_state.typed_turn_index = -1

def _client_or_error():
    try:
        return get_openai_client(), ""
    except Exception as e:
        return None, str(e)


# ============================================================
# THEME + TYPEWRITER (STYLE/RENDER ONLY — NO GAME LOGIC CHANGES)
# ============================================================

THEME_DEFAULT = "hybrid"  # "hybrid" | "terminal" | "parchment"

def inject_css(theme: str = "hybrid") -> None:
    if theme == "terminal":
        css_vars = """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Inter:wght@400;600;700&display=swap');
        :root{
          --bg:#070A0F; --panel:#0B1220; --panel2:#0A1020;
          --text:#D1FAE5; --muted:#6EE7B7;
          --accent:#34D399; --accent2:#A7F3D0;
          --border:rgba(52,211,153,.25);
          --shadow:0 14px 40px rgba(0,0,0,.45);
          --radius:18px;
        }
        </style>
        """
    elif theme == "parchment":
        css_vars = """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Merriweather:wght@400;700&family=Inter:wght@400;600;700&display=swap');
        :root{
          --bg:#F6F1E6; --panel:#FFF9EE; --panel2:#FDF2D7;
          --text:#1F2937; --muted:#6B7280;
          --accent:#7C3AED; --accent2:#B45309;
          --border:rgba(31,41,55,.15);
          --shadow:0 10px 24px rgba(17,24,39,.12);
          --radius:18px;
        }
        </style>
        """
    else:
        css_vars = """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@400;600;700&display=swap');
        :root{
          --bg:#0B0E14; --panel:#0F172A; --panel2:#111827;
          --text:#E5E7EB; --muted:#9CA3AF;
          --accent:#7C3AED; --accent2:#22D3EE;
          --border:rgba(124,58,237,.25);
          --shadow:0 14px 40px rgba(0,0,0,.45);
          --radius:18px;
        }
        </style>
        """

    core = """
    <style>
      .stApp{
        background:
          radial-gradient(1200px 600px at 20% 10%, rgba(124,58,237,.18), transparent 55%),
          radial-gradient(900px 500px at 80% 20%, rgba(34,211,238,.10), transparent 60%),
          var(--bg);
        color: var(--text);
      }
      html, body, [class*="css"]{
        font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
      }
      .stMarkdown, .stText, .stCaption{ color: var(--text); }

      .adventure-card{
        font-family: "IBM Plex Mono", "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
        letter-spacing: 0.1px;
      }
      .parchment-story .adventure-card{
        font-family: Merriweather, Georgia, serif;
        letter-spacing: 0px;
      }

      section[data-testid="stSidebar"]{
        background: linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,.01));
        border-right: 1px solid rgba(255,255,255,.06);
      }

      h1, h2, h3{ letter-spacing: .2px; }
      h2, h3{ font-weight: 700; }

      .card{
        background: linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,.02));
        border: 1px solid rgba(255,255,255,.08);
        border-radius: var(--radius);
        box-shadow: var(--shadow);
      }
      .parchment-ui .card{
        background: linear-gradient(180deg, rgba(255,255,255,.85), rgba(255,255,255,.70));
        border: 1px solid rgba(31,41,55,.12);
      }

      .stButton > button{
        border-radius: 14px !important;
        border: 1px solid rgba(255,255,255,.10) !important;
        background: linear-gradient(180deg, rgba(124,58,237,.25), rgba(124,58,237,.10)) !important;
        color: var(--text) !important;
        padding: 0.85rem 1rem !important;
        font-weight: 600 !important;
        transition: transform .06s ease, filter .15s ease, border-color .15s ease;
      }
      .stButton > button:hover{
        filter: brightness(1.12);
        border-color: rgba(124,58,237,.55) !important;
        transform: translateY(-1px);
      }
      .stButton > button:active{
        transform: translateY(0px);
        filter: brightness(1.05);
      }

      .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"]{
        border-radius: 14px !important;
        background: rgba(255,255,255,.04) !important;
        border: 1px solid rgba(255,255,255,.10) !important;
        color: var(--text) !important;
      }
      .parchment-ui .stTextInput input,
      .parchment-ui .stTextArea textarea,
      .parchment-ui .stSelectbox div[data-baseweb="select"]{
        background: rgba(255,255,255,.70) !important;
        border: 1px solid rgba(31,41,55,.12) !important;
        color: var(--text) !important;
      }

      hr, .stDivider{ border-color: rgba(255,255,255,.10) !important; }

      span[style*="border-radius:999px"]{
        background: rgba(255,255,255,.06) !important;
        color: var(--text) !important;
        border: 1px solid rgba(255,255,255,.08) !important;
      }

      div[role="progressbar"]{ border-radius: 999px; }

      .stApp:before{
        content:"";
        position: fixed;
        inset: 0;
        pointer-events: none;
        background: linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px);
        background-size: 100% 3px;
        opacity: .05;
        mix-blend-mode: overlay;
      }
    </style>
    """
    st.markdown(css_vars + core, unsafe_allow_html=True)

def render_story_card(text: str, use_typewriter: bool, cps: int = 35) -> None:
    """
    Renders story text in a styled card. Optionally typewrites it.
    Rendering only; does not touch campaign/state logic.
    """
    text = text or ""
    placeholder = st.empty()

    def draw(t: str) -> None:
        safe = _html.escape(t).replace("\n", "<br>")
        placeholder.markdown(
            f"""
            <div class="card adventure-card" style="padding:16px 18px; line-height:1.7; font-size:16px;">
              {safe}
            </div>
            """,
            unsafe_allow_html=True
        )

    if not use_typewriter:
        draw(text)
        return

    cps = max(5, int(cps))
    delay = 1.0 / cps

    buf: List[str] = []
    for ch in text:
        buf.append(ch)
        draw("".join(buf))
        time.sleep(delay)


# ============================================================
# STREAMLIT APP
# ============================================================

st.set_page_config(page_title=APP_TITLE, page_icon="🧙", layout="wide")
st.title(APP_TITLE)

ensure_session_defaults()

conn = db_connect()
db_init_and_migrate(conn)
settings = load_settings(conn)

# ---------------- Sidebar: Room + DM settings ----------------

with st.sidebar:
    st.header("🎨 Визуальный стиль")
    theme_choice = st.selectbox("Тема", ["hybrid", "terminal", "parchment"], index=0)
    st.header("⌨️ Текст")
    typewriter = st.checkbox("Печатать текст", value=True)
    type_speed = st.slider("Скорость печати (симв/сек)", 10, 80, 35, 1)

    # CSS injection (style only)
    if theme_choice == "parchment":
        st.markdown("<div class='parchment-ui parchment-story'>", unsafe_allow_html=True)
        inject_css(theme_choice)
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        inject_css(theme_choice)

    st.divider()

    st.header("🏠 Комната")
    current_room = st.session_state.room_id or ""
    st.caption("Комната — код, который изолирует героев/кампании. Разные комнаты = разные игроки.")

    if current_room:
        st.markdown(f"**Текущая:** `{current_room}`")
        if st.button("🚪 Сменить", use_container_width=True):
            st.session_state.view = "room"
            st.session_state.active_hero_id = ""
            st.session_state.last_choice_lock = False
            st.rerun()
    else:
        st.markdown("**Текущая:** _не выбрана_")

    st.divider()

    st.header("⚙ Настройки DM")
    scene_length = st.selectbox("Длина текста", ["short", "medium", "long"], index=["short", "medium", "long"].index(settings.scene_length))
    tone = st.selectbox("Тон", ["classic", "heroic", "dark", "light_irony"], index=["classic", "heroic", "dark", "light_irony"].index(settings.tone))

    st.subheader("🎚 Баланс")
    bc = st.slider("⚔️ Бои/опасность", 0.0, 1.0, float(settings.balance_combat), 0.01)
    be = st.slider("🧭 Исследование", 0.0, 1.0, float(settings.balance_exploration), 0.01)
    bs = st.slider("💬 Социалка", 0.0, 1.0, float(settings.balance_social), 0.01)

    consequence_intensity = st.selectbox("Жёсткость последствий", ["low", "normal", "high"], index=["low", "normal", "high"].index(settings.consequence_intensity))
    choices_count = st.selectbox("Вариантов выбора", [3, 4], index=[3, 4].index(int(settings.choices_count)))
    max_turns = st.selectbox("Длина сессии (ходов)", [10, 15, 20], index=[10, 15, 20].index(int(settings.max_turns)) if int(settings.max_turns) in [10, 15, 20] else 1)
    inv_limit = st.number_input("Лимит инвентаря", min_value=3, max_value=30, value=int(settings.inventory_limit), step=1)

    st.subheader("📝 Системный промпт (доп. правила)")
    system_prompt = st.text_area(" ", value=settings.system_prompt, height=140, placeholder="Например: меньше клише; больше детективности; избегай мата...")

    with st.expander("🔧 Advanced"):
        debug_mode = st.checkbox("Debug mode", value=bool(settings.debug_mode))

        temp_enabled = st.checkbox("Указать temperature", value=settings.temperature is not None)
        temperature = None
        if temp_enabled:
            temperature = st.slider("temperature", 0.0, 1.0, float(settings.temperature if settings.temperature is not None else 0.7), 0.05)

        default_fa = _default_final_arc_turns(int(max_turns))
        final_arc_turns = st.number_input(
            "Final Arc (N ходов до финала)",
            min_value=2,
            max_value=max(2, int(max_turns) - 1),
            value=int(settings.final_arc_turns) if int(settings.max_turns) == int(max_turns) else int(default_fa),
            step=1,
            help="Когда до конца остаётся N ходов, DM ведёт к развязке и не вводит новые крупные линии."
        )

    if st.button("💾 Сохранить настройки", use_container_width=True):
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
        settings.final_arc_turns = int(final_arc_turns)
        save_settings(conn, settings)
        st.success("Сохранено. Применится со следующего хода.")

# ---------------- Info/Error banners ----------------

if st.session_state.info:
    st.info(st.session_state.info)
    st.session_state.info = ""
if st.session_state.error:
    st.error(st.session_state.error)

# ============================================================
# VIEW: ROOM (enter/switch room)
# ============================================================

if st.session_state.view == "room":
    st.subheader("🏠 Вход в комнату")

    col1, col2 = st.columns([2, 1])
    with col1:
        room_input = st.text_input("Код комнаты", value=st.session_state.room_id or "", placeholder="Например: X4F8Q2")
    with col2:
        if st.button("🎲 Сгенерировать", use_container_width=True):
            st.session_state.room_id = generate_room_id(6)
            st.rerun()

    st.caption("Используй один и тот же код, чтобы вернуться к своим героям с другого устройства.")

    if st.button("➡️ Продолжить", use_container_width=True):
        rid = normalize_room_id(room_input)
        if not rid:
            st.session_state.error = "Введи код комнаты (или сгенерируй)."
            st.rerun()
        st.session_state.room_id = rid
        st.session_state.view = "menu"
        st.session_state.active_hero_id = ""  # always show hero selection menu
        st.session_state.last_choice_lock = False
        st.session_state.error = ""
        st.rerun()

    st.stop()

room_id = normalize_room_id(st.session_state.room_id)
if not room_id:
    st.session_state.view = "room"
    st.rerun()

# Load heroes for room
heroes = list_heroes(conn, room_id)

# ============================================================
# VIEW: MENU (Always hero selection)
# ============================================================

if st.session_state.view == "menu":
    st.subheader("🏠 Меню")
    st.caption(f"Комната: `{room_id}` • Герои: {len(heroes)}/{MAX_HEROES_PER_ROOM}")

    # Hero list
    st.markdown("### 👤 Выбери героя")

    if not heroes:
        st.info("В этой комнате пока нет героев. Создай первого.")
    else:
        for h in heroes:
            camp = load_campaign_for_hero(conn, room_id, h.hero_id)
            status = "нет кампании"
            progress = ""
            if camp:
                status = "🏁 завершена" if camp.is_completed else "▶️ в процессе"
                progress = f"{camp.turn_index + 1}/{camp.max_turns}"

            row = st.columns([2.2, 1.2, 1.2, 1.2, 1.2, 2.0])
            with row[0]:
                st.markdown(f"**{h.name}**")
                st.markdown(f"{pill(h.hero_class)} {pill(h.race)}", unsafe_allow_html=True)
            with row[1]:
                st.caption("Приключений")
                st.write(f"{h.completed_campaigns}")
            with row[2]:
                st.caption("Статус")
                st.write(status)
            with row[3]:
                st.caption("Ход")
                st.write(progress if progress else "—")
            with row[4]:
                # Play/continue/new adventure
                if camp and camp.is_completed:
                    label = "🔁 Новое"
                elif camp and not camp.is_completed:
                    label = "▶ Играть"
                else:
                    label = "🌟 Начать"
                if st.button(label, key=f"play_{h.hero_id}", use_container_width=True):
                    st.session_state.active_hero_id = h.hero_id
                    st.session_state.view = "adventure"
                    st.rerun()
            with row[5]:
                if st.button("🗑 Удалить героя", key=f"del_{h.hero_id}", use_container_width=True):
                    delete_hero(conn, room_id, h.hero_id)
                    st.session_state.active_hero_id = ""
                    st.session_state.info = "Герой удалён."
                    st.rerun()

            st.divider()

    # Create hero
    can_create = len(heroes) < MAX_HEROES_PER_ROOM
    if st.button("🧙 Создать героя", use_container_width=True, disabled=not can_create):
        st.session_state.view = "hero_creation"
        st.session_state.active_hero_id = ""
        st.rerun()

    if not can_create:
        st.warning("Достигнут лимит героев (10). Удали одного героя или создай новую комнату.")

    st.stop()

# ============================================================
# VIEW: HERO CREATION
# ============================================================

if st.session_state.view == "hero_creation":
    st.subheader("🧙 Создание героя")
    st.caption(f"Комната: `{room_id}` • Герои: {len(heroes)}/{MAX_HEROES_PER_ROOM}")

    if len(heroes) >= MAX_HEROES_PER_ROOM:
        st.error("Нельзя создать героя: достигнут лимит (10).")
        if st.button("⬅️ В меню", use_container_width=True):
            st.session_state.view = "menu"
            st.rerun()
        st.stop()

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        name = st.text_input("Имя героя", value="", placeholder="Например: Арен, Лира, Торин")
    with col2:
        hero_class = st.selectbox("Класс", ["Fighter", "Rogue", "Wizard"], index=0)
    with col3:
        race = st.selectbox("Раса", ["Human", "Elf", "Dwarf"], index=0)

    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("⬅️ В меню", use_container_width=True):
            st.session_state.view = "menu"
            st.rerun()
    with c2:
        if st.button("✅ Создать", use_container_width=True):
            hero = start_hero(room_id=room_id, name=name, hero_class=hero_class, race=race)
            save_hero(conn, hero)
            st.session_state.info = f"Герой создан: {hero.name}"
            st.session_state.view = "menu"  # always show menu selection
            st.rerun()

    st.stop()

# ============================================================
# VIEW: ADVENTURE (per selected hero)
# ============================================================

if st.session_state.view != "adventure":
    st.session_state.view = "menu"
    st.rerun()

active_hero_id = str(st.session_state.active_hero_id or "").strip()
hero = get_hero(conn, room_id, active_hero_id) if active_hero_id else None
if not hero:
    # invalid selection -> back to menu
    st.session_state.view = "menu"
    st.session_state.active_hero_id = ""
    st.rerun()

campaign = load_campaign_for_hero(conn, room_id, hero.hero_id)

left, right = st.columns([2.2, 1])

with right:
    st.subheader("👤 Герой")
    st.markdown(f"**{hero.name}**  \n{pill(hero.hero_class)} {pill(hero.race)}", unsafe_allow_html=True)
    st.caption(f"Приключений завершено: **{hero.completed_campaigns}**")
    st.divider()

    # Journal (collapsible) — placed above inventory, open by default
    with st.expander("📓 Журнал", expanded=True):
        render_journal(campaign.journal if campaign else Journal(), show_title=False)
    st.divider()

    st.subheader(f"🎒 Инвентарь ({len(campaign.inventory) if campaign else 0}/{settings.inventory_limit})")
    render_inventory(campaign.inventory if campaign else [])
    st.divider()

    st.subheader("✨ Заклинания")
    render_spells(campaign.spells if campaign else [])
    st.divider()

    st.subheader("🏠 Навигация")
    if st.button("🏠 В меню", use_container_width=True):
        st.session_state.view = "menu"
        st.session_state.active_hero_id = ""  # always choose hero again per spec
        st.session_state.last_choice_lock = False
        st.rerun()

    if settings.debug_mode and campaign:
        with st.expander("🧪 Debug: World Bible"):
            st.json(campaign.world_bible)
        with st.expander("🧪 Debug: Blueprint"):
            st.json(campaign.blueprint)
        with st.expander("🧪 Debug: Summary"):
            st.json(campaign.summary or {})
        with st.expander("🧪 Debug: Final Arc"):
            phase, rem, fa = _final_phase(campaign, settings)
            st.write({"phase": phase, "remaining_after_next": rem, "final_arc_turns": fa})

with left:
    st.subheader("📖 Приключение")

    # If no campaign yet, allow start
    if campaign is None:
        st.info("У этого героя ещё нет активного приключения.")
        if st.button("🌟 Начать приключение", use_container_width=True):
            client, err = _client_or_error()
            if not client:
                st.session_state.error = err
                st.rerun()
            try:
                # overwrite "last campaign": ensure clean slate for this hero
                delete_campaign_for_hero(conn, room_id, hero.hero_id)
                campaign = start_campaign(room_id, hero, settings, client)
                save_campaign(conn, campaign)
                # record turn 0 as scene_text
                add_turn(conn, room_id, hero.hero_id, campaign.campaign_id, 0, None, None, {
                    "scene_text": campaign.last_turn_text,
                    "choices": campaign.last_choices,
                    "journal_update": json.loads(_dump_journal(campaign.journal)),
                    "canonical_updates": {},
                })
                # reset typed tracker on new campaign
                st.session_state.typed_turn_index = -1
                st.rerun()
            except Exception as e:
                st.session_state.error = f"Не удалось начать кампанию: {e}"
                st.rerun()
        st.stop()

    # Show progress
    prog = min(1.0, (campaign.turn_index / max(1, campaign.max_turns)))
    st.progress(prog, text=f"Ход {campaign.turn_index + 1} из {campaign.max_turns}")

    # Styled story card + optional typewriter
    should_type = bool(typewriter) and (int(st.session_state.typed_turn_index) != int(campaign.turn_index))
    render_story_card(campaign.last_turn_text, use_typewriter=should_type, cps=int(type_speed))
    st.session_state.typed_turn_index = int(campaign.turn_index)

    st.write("")

    # Completed campaign state
    if campaign.is_completed:
        st.success("🏁 История завершена.")
        cA, cB = st.columns([1, 1])
        with cA:
            if st.button("🔁 Новое приключение этим героем", use_container_width=True):
                client, err = _client_or_error()
                if not client:
                    st.session_state.error = err
                    st.rerun()
                try:
                    # overwrite old campaign
                    delete_campaign_for_hero(conn, room_id, hero.hero_id)
                    # start new
                    campaign = start_campaign(room_id, hero, settings, client)
                    save_campaign(conn, campaign)
                    add_turn(conn, room_id, hero.hero_id, campaign.campaign_id, 0, None, None, {
                        "scene_text": campaign.last_turn_text,
                        "choices": campaign.last_choices,
                        "journal_update": json.loads(_dump_journal(campaign.journal)),
                        "canonical_updates": {},
                    })
                    st.session_state.last_choice_lock = False
                    st.session_state.typed_turn_index = -1
                    st.rerun()
                except Exception as e:
                    st.session_state.error = f"Не удалось начать новое приключение: {e}"
                    st.rerun()
        with cB:
            if st.button("🏠 В меню", use_container_width=True):
                st.session_state.view = "menu"
                st.session_state.active_hero_id = ""
                st.session_state.last_choice_lock = False
                st.rerun()
        st.stop()

    # Choices (3-4)
    disabled = bool(st.session_state.last_choice_lock)
    shown_choices = (campaign.last_choices or [])[: max(2, min(4, int(settings.choices_count)))]
    if not shown_choices:
        st.warning("Нет вариантов выбора. Вернись в меню и начни новое приключение.")
        st.stop()

    st.markdown("### 👉 Что ты сделаешь?")
    for i, ch in enumerate(shown_choices):
        label = (ch.get("text") or "").strip()
        cid = (ch.get("id") or f"opt{i}").strip() or f"opt{i}"

        if choice_button(label, key=f"choice_{room_id}_{hero.hero_id}_{campaign.campaign_id}_{campaign.turn_index}_{cid}", disabled=disabled):
            st.session_state.last_choice_lock = True
            st.session_state.error = ""

            client, err = _client_or_error()
            if not client:
                st.session_state.error = err
                st.session_state.last_choice_lock = False
                st.rerun()

            chosen = {"id": cid, "text": label}

            try:
                resp = dm_next_turn(client, room_id, hero, campaign, chosen, settings, conn)

                # Store full response
                add_turn(conn, room_id, hero.hero_id, campaign.campaign_id, campaign.turn_index + 1, cid, label, resp)

                # Apply state changes
                state_changes = resp.get("state_changes", {}) if isinstance(resp, dict) else {}
                apply_state_changes(campaign, state_changes if isinstance(state_changes, dict) else {}, settings)

                # Mark key choice as consumed if it was due for this turn (meta only)
                try:
                    key_turns = list((campaign.flags or {}).get("key_choice_turns", []) or [])
                    key_done = list((campaign.flags or {}).get("key_choices_done", []) or [])
                    next_turn_index = int(campaign.turn_index + 1)
                    due = (next_turn_index in set(int(x) for x in key_turns)) and (next_turn_index not in set(int(x) for x in key_done))
                    if due:
                        if next_turn_index not in set(int(x) for x in key_done):
                            key_done.append(next_turn_index)
                        (campaign.flags or {})["key_choices_done"] = key_done
                except Exception:
                    pass

                # Apply journal update
                jupd = resp.get("journal_update", {}) if isinstance(resp, dict) else {}
                apply_journal_update(campaign, jupd if isinstance(jupd, dict) else {})

                # Update turn text
                campaign.last_turn_text = str(resp.get("turn_text", "")).strip()

                # Turn advance
                is_final = bool(resp.get("is_final")) if isinstance(resp, dict) else False
                campaign.turn_index += 1

                if is_final or (campaign.turn_index >= campaign.max_turns):
                    campaign.is_completed = True
                    campaign.last_choices = []
                    # increment completed adventures counter once per completion
                    increment_hero_completed(conn, room_id, hero.hero_id)
                else:
                    choices = resp.get("choices", [])
                    if not isinstance(choices, list) or len(choices) < 2:
                        choices = [
                            {"id": "A", "text": "Продолжить осторожно."},
                            {"id": "B", "text": "Поговорить и узнать больше."},
                            {"id": "C", "text": "Сменить подход."},
                        ]
                    campaign.last_choices = [
                        {"id": str(x.get("id", "")).strip(), "text": str(x.get("text", "")).strip()}
                        for x in choices
                    ][: max(2, min(4, int(settings.choices_count)))]

                # Optional: summary compression
                maybe_create_summary(client, hero, campaign, settings, conn)

                # Persist campaign
                save_campaign(conn, campaign)

                # reset typewriter for new turn
                st.session_state.typed_turn_index = -1

                st.session_state.last_choice_lock = False
                st.rerun()

            except Exception as e:
                st.session_state.error = f"Ошибка хода: {e}"
                st.session_state.last_choice_lock = False
                st.rerun()

    st.write("")
    st.caption("Настройки DM в сайдбаре влияют на последующие ходы.")

# ============================================================
# RUN INSTRUCTIONS
# ============================================================
# 1) pip install streamlit openai
# 2) export OPENAI_API_KEY="..."
# 3) streamlit run app.py
#
# Optional:
# - export OPENAI_MODEL="gpt-4.1-mini"
# - export ADVENTURE_DB_PATH="/path/to/adventure.db"
