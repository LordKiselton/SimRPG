import csv
import io
import json
import re
import copy
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st


APP_TITLE = "VS Season Builder"
PROJECT_SCHEMA_VERSION = 1
DEFAULT_APPEAR = "default"
RISKY_QUEST_KEYS = {"clanBossAttack", "ClanBossAttack"}


# =========================
# Utility helpers
# =========================

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def deep_clone(obj: Any) -> Any:
    return copy.deepcopy(obj)


def safe_json_dumps(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    return json.dumps(obj, ensure_ascii=False, indent=2)


def parse_json_maybe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (int, float, bool)):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return text


def csv_bytes_from_df(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-zA-Z0-9а-яА-Я_\-\s]", "", text)
    text = re.sub(r"\s+", "_", text)
    return text[:80] if text else "item"


def extract_reward_pairs(text: str) -> List[Tuple[str, str, str]]:
    # Expects pasted rows like: "consumable, [40228] name\n1"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        qty = ""
        if i + 1 < len(lines) and re.fullmatch(r"-?\d+(\.\d+)?", lines[i + 1]):
            qty = lines[i + 1]
            i += 2
        else:
            i += 1
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2:
            kind = parts[0]
            item = ",".join(parts[1:]).strip()
            out.append((kind, item, qty))
    return out


def reward_pairs_to_text(pairs: List[Tuple[str, str, Any]]) -> str:
    lines: List[str] = []
    for kind, item, qty in pairs:
        lines.append(f"{kind}, {item}")
        lines.append(str(qty))
    return "\n".join(lines)


# =========================
# Data model
# =========================

@dataclass
class ChangeLogEntry:
    ts: str
    action: str
    entity: str
    scope: str
    old_value: str
    new_value: str


@dataclass
class QuestTemplate:
    key: str
    name_ru: str
    technical_name: str
    translation_method: str
    locale_key: str
    label_template: str
    farm_condition: Dict[str, Any]
    reward: Dict[str, Any]
    reward_sorting: int = 1
    disabled: int = 0
    daily: int = 0
    appear_ident: str = DEFAULT_APPEAR
    category: str = "Прочее"
    risky: bool = False
    tags: Optional[List[str]] = None


@dataclass
class DayTemplate:
    key: str
    name_ru: str
    day_title_key: str
    quests: List[str]
    chest_rewards: List[Dict[str, Any]]


# =========================
# Session state setup
# =========================

def get_default_project() -> Dict[str, Any]:
    return {
        "schema_version": PROJECT_SCHEMA_VERSION,
        "meta": {
            "project_name": "Новый VS сезон",
            "season_name": "Season 23",
            "season_code": "S23",
            "appearIdent": "eventVS_23",
            "start_date": "30.03.2026 02:00",
            "end_date": "27.04.2026 01:59",
            "created_at": now_str(),
            "updated_at": now_str(),
        },
        "season": {
            "num_battles": 4,
            "battle_duration_days": 7,
            "round_duration_days": 1,
            "battle_offsets": [0, 7, 14, 21],
            "days_per_battle": 6,
            "battle_keys": [1, 2, 3, 4],
            "day_assignments": {},
        },
        "id_plan": {
            "type_start": None,
            "chain_start": None,
            "quest_start": None,
        },
        "generated": {
            "type_rows": [],
            "chain_rows": [],
            "quest_rows": [],
        },
        "catalog": {},
        "day_templates": {},
        "saved_day_presets": {},
        "change_log": [],
    }


def ensure_state() -> None:
    if "project" not in st.session_state:
        st.session_state.project = get_default_project()
        seed_default_catalog_and_templates(st.session_state.project)
    if "active_day_key" not in st.session_state:
        st.session_state.active_day_key = None


# =========================
# Seed catalog and templates
# =========================

def q_template(
    key: str,
    name_ru: str,
    technical_name: str,
    translation_method: str,
    locale_key: str,
    label_template: str,
    farm_condition: Dict[str, Any],
    reward: Dict[str, Any],
    category: str,
    risky: bool = False,
    reward_sorting: int = 1,
) -> QuestTemplate:
    return QuestTemplate(
        key=key,
        name_ru=name_ru,
        technical_name=technical_name,
        translation_method=translation_method,
        locale_key=locale_key,
        label_template=label_template,
        farm_condition=farm_condition,
        reward=reward,
        category=category,
        risky=risky,
        reward_sorting=reward_sorting,
        tags=[],
    )


def seed_default_catalog_and_templates(project: Dict[str, Any]) -> None:
    if project["catalog"]:
        return

    def coin_reward(amount: int) -> Dict[str, Any]:
        return {"coin": {"40198": amount}}

    catalog: Dict[str, Dict[str, Any]] = {}

    items = [
        q_template("titan_power", "Увеличь на 3 мощь Титанов", "titanTeamPower", "titanTeamPower", "LIB_QUEST_TRANSLATE_INCREASETITANPOWER", "{day_label}", {"eventFunc": {"name": "titanTeamPower"}, "amount": "3"}, coin_reward(10), "Титаны", False, 1),
        q_template("open_summoning", "Открой 1 раз сферу призыва", "openSummoningCircle", "openSummoningCircle", "LIB_QUEST_TRANSLATE_OPENSUMMONINGSPHERE", "{day_label}", {"eventFunc": {"name": "openSummoningCircle"}, "amount": "1"}, coin_reward(150), "Титаны", False, 2),
        q_template("open_elemental", "Открой 1 раз сферу стихий", "openTitanArtifactSphere", "openTitanArtifactSphere", "LIB_QUEST_TRANSLATE_OPENELEMENTALSPHERE", "{day_label}", {"eventFunc": {"name": "openTitanArtifactSphere"}, "amount": "1"}, coin_reward(120), "Титаны", False, 3),
        q_template("arena", "Сразись 1 раз на Арене", "arenaBattle", "arenaBattle", "LIB_QUEST_TRANSLATE_FIGHTARENA", "{day_label}", {"eventFunc": {"name": "arenaBattle", "args": {"type": "arena"}}, "amount": "1"}, coin_reward(600), "Арена", False, 4),
        q_template("tower", "Открой 1 сундук в Башне", "towerChestCount", "towerChestCount", "LIB_QUEST_TRANSLATE_OPENTOWERCHEST", "{day_label}", {"eventFunc": {"name": "towerChestCount"}, "amount": "1"}, coin_reward(400), "Башня", False, 5),
        q_template("daily", "Выполни 1 ежедневное задание", "dailyQuestFarm", "dailyQuestFarm", "LIB_QUEST_TRANSLATE_COMPLETEDAILYQUESTS", "{day_label}", {"eventFunc": {"name": "dailyQuestFarm"}, "amount": "1"}, coin_reward(200), "Ежедневки", False, 6),
        q_template("spend_spark", "Потрать 15 Искр мощи", "resourceSpentTypeId", "resourceSpentTypeId", "LIB_QUEST_TRANSLATE_SPENDSPARKOFPOWER", "{day_label}", {"eventFunc": {"name": "resourceSpentTypeId", "args": {"type": "consumable", "id": "24"}}, "amount": "15"}, coin_reward(3), "Титаны", False, 7),
        q_template("spend_rune", "Потрать 20 рунных камней", "spentCoin", "spentCoin", "LIB_QUEST_TRANSLATE_RUNESTONESPEND", "{day_label}", {"eventFunc": {"name": "spentCoin", "args": {"id": 40077}}, "amount": "20"}, coin_reward(10), "Руны", False, 8),
        q_template("heroic_chest", "Открой 1 раз Героический сундук", "chestOpen", "chestOpen", "LIB_QUEST_TRANSLATE_OPENHEROICCHEST", "{day_label}", {"eventFunc": {"name": "chestOpen"}, "amount": "1"}, coin_reward(400), "Сундуки", False, 9),
        q_template("vip", "Получи 1 VIP очков", "vipPoints", "vipPoints", "LIB_QUEST_TRANSLATE_GETVIPPOINTS", "{day_label}", {"eventFunc": {"name": "vipPoints"}, "amount": "1"}, coin_reward(10), "VIP", False, 10),
        q_template("skin_hero", "Потрать 15 Камней облика Героя", "spendSkinCoin", "resourceSpentTypeId", "LIB_QUEST_TRANSLATE_SPENDSKINSTONE", "{day_label}", {"eventFunc": {"name": "resourceSpentTypeId", "args": {"type": "coin", "id": [8, 9, 10]}}, "amount": "15"}, coin_reward(70), "Герои", False, 1),
        q_template("outland", "Открой 1 раз сундук в Запределье", "bossChestCount", "bossChestCount", "LIB_QUEST_TRANSLATE_OPENOUTLANDCHEST", "{day_label}", {"eventFunc": {"name": "bossChestCount"}, "amount": "1"}, coin_reward(200), "Сундуки", False, 2),
        q_template("expedition", "Начни 1 Экспедицию", "startExpedition", "startExpedition", "LIB_QUEST_TRANSLATE_EXPEDITIONSTART", "{day_label}", {"eventFunc": {"name": "startExpedition"}, "amount": "1"}, coin_reward(500), "Экспедиция", False, 4),
        q_template("spend_artifact_fragment", "Потрать 1 фрагмент артефактов Героев", "spendArtifactFragment", "spendArtifactFragment", "LIB_QUEST_TRANSLATE_SPENDARTIFACTFRAGMENT", "{day_label}", {"eventFunc": {"name": "spendArtifactFragment"}, "amount": "1"}, coin_reward(120), "Артефакты", False, 7),
        q_template("use_titan_potion", "Используй 100 зелий Титана", "resourceSpentTypeId", "resourceSpentTypeId", "LIB_QUEST_TRANSLATE_USETITANPOTION", "{day_label}", {"eventFunc": {"name": "resourceSpentTypeId", "args": {"type": "consumable", "id": "20"}}, "amount": "100"}, coin_reward(15), "Титаны", False, 8),
        q_template("artifact_chest", "Открой 1 раз Артефактный сундук", "ARTIFACTCHESTCOUNT", "openArtifactChest", "LIB_QUEST_TRANSLATE_ARTIFACTCHESTOPEN", "{day_label}", {"eventFunc": {"name": "openArtifactChest"}, "amount": "1"}, coin_reward(75), "Артефакты", False, 9),
        q_template("hero_red", "Надень 1 красный предмет", "heroInsertItem", "heroInsertItem", "LIB_QUEST_TRANSLATE_HEROINSERTITEM", "{day_label}", {"eventFunc": {"name": "heroInsertItem", "args": {"color": "red"}}, "amount": "1"}, coin_reward(125000), "Герои", False, 1),
        q_template("hero_orange", "Надень 1 оранжевый предмет", "heroInsertItem", "heroInsertItem", "LIB_QUEST_TRANSLATE_HEROINSERTITEM", "{day_label}", {"eventFunc": {"name": "heroInsertItem", "args": {"color": "orange"}}, "amount": "1"}, coin_reward(16000), "Герои", False, 2),
        q_template("hero_purple", "Надень 1 фиолетовый предмет", "heroInsertItem", "heroInsertItem", "LIB_QUEST_TRANSLATE_HEROINSERTITEM", "{day_label}", {"eventFunc": {"name": "heroInsertItem", "args": {"color": "purple"}}, "amount": "1"}, coin_reward(2700), "Герои", False, 3),
        q_template("hero_blue", "Надень 1 синий предмет", "heroInsertItem", "heroInsertItem", "LIB_QUEST_TRANSLATE_HEROINSERTITEM", "{day_label}", {"eventFunc": {"name": "heroInsertItem", "args": {"color": "blue"}}, "amount": "1"}, coin_reward(500), "Герои", False, 4),
        q_template("hero_green", "Надень 1 зеленый предмет", "heroInsertItem", "heroInsertItem", "LIB_QUEST_TRANSLATE_HEROINSERTITEM", "{day_label}", {"eventFunc": {"name": "heroInsertItem", "args": {"color": "green"}}, "amount": "1"}, coin_reward(100), "Герои", False, 5),
        q_template("hero_white", "Надень 1 белый предмет", "heroInsertItem", "heroInsertItem", "LIB_QUEST_TRANSLATE_HEROINSERTITEM", "{day_label}", {"eventFunc": {"name": "heroInsertItem", "args": {"color": "white"}}, "amount": "1"}, coin_reward(40), "Герои", False, 6),
        q_template("fairy_dust", "Потрать 25 Пыльцы Феи", "resourceSpentTypeId", "resourceSpentTypeId", "LIB_QUEST_TRANSLATE_SPENDFAIRYDUST", "{day_label}", {"eventFunc": {"name": "resourceSpentTypeId", "args": {"id": 18, "type": "coin"}}, "amount": "25"}, coin_reward(5), "Прочее", False, 11),
        q_template("energy", "Потрать 3 Энергии", "energySpend", "energySpend", "LIB_QUEST_TRANSLATE_ENERGYSPENDVS", "{day_label}", {"eventFunc": {"name": "energySpend"}, "amount": "3"}, coin_reward(10), "Энергия", False, 12),
        q_template("grand_arena", "Сразись 1 раз на Гранд Арене", "arenaBattle_grandOnly", "arenaBattle", "LIB_QUEST_TRANSLATE_FIGHTGRANDARENA", "{day_label}", {"eventFunc": {"name": "arenaBattle", "args": {"type": "grand"}}, "amount": "1"}, coin_reward(600), "Арена", False, 3),
        q_template("hero_soul", "Получи 1 Камень души Героя", "fragmentHeroGet", "fragmentHeroGet", "LIB_QUEST_TRANSLATE_GETHEROSOULSTONE", "{day_label}", {"eventFunc": {"name": "fragmentHeroGet"}, "amount": "1"}, coin_reward(50), "Герои", False, 6),
        q_template("skin_titan", "Потрать 15 Камней облика Титана", "resourceSpentTypeId", "resourceSpentTypeId", "LIB_QUEST_TRANSLATE_SPENDTITANSKINSTONE", "{day_label}", {"eventFunc": {"name": "resourceSpentTypeId", "args": {"id": 20, "type": "coin"}}, "amount": "15"}, coin_reward(10), "Титаны", False, 7),
        q_template("rune_sphere", "Потрать 100 рунных сфер", "spentCoin", "spentCoin", "LIB_QUEST_TRANSLATE_SPENDRUNESPHERE", "{day_label}", {"eventFunc": {"name": "spentCoin", "args": {"id": 40078}}, "amount": "100"}, coin_reward(5000), "Руны", False, 1),
        q_template("hero_power", "Увеличь на 1 мощь героев", "heroTeamPower", "heroTeamPower", "LIB_QUEST_TRANSLATE_INCREASEHEROPOWER", "{day_label}", {"eventFunc": {"name": "heroTeamPower"}, "amount": "1"}, coin_reward(10), "Герои", False, 1),
        q_template("hydra", "Сразись 1 раз с Гидрой", "clanBossAttack", "clanBossAttack", "LIB_QUEST_TRANSLATE_FIGHTHYDRA", "{day_label}", {"eventFunc": {"name": "clanBossAttack"}, "amount": "1"}, coin_reward(1000), "Гидра", True, 2),
        q_template("metacube", "Потрать 10 Метакубов", "spentCoin", "resourceSpentTypeId", "LIB_QUEST_TRANSLATE_SPANDMETACUBES", "{day_label}", {"eventFunc": {"name": "resourceSpentTypeId", "args": {"id": 40065, "type": "coin"}}, "amount": "10"}, coin_reward(1), "Прочее", False, 9),
        q_template("mastery", "Потрать 15 кристаллов мастерства", "spentCoin", "resourceSpentTypeId", "LIB_QUEST_TRANSLATE_SPENDMASTERYCRYSTAL", "{day_label}", {"eventFunc": {"name": "resourceSpentTypeId", "args": {"id": 40067, "type": "coin"}}, "amount": "15"}, coin_reward(20), "Прочее", False, 8),
        q_template("chaos_core", "Потрать 1 Ядро Хаоса", "spendChaosCore", "resourceSpentTypeId", "LIB_QUEST_TRANSLATE_CHAOSCORESPEND", "{day_label}", {"eventFunc": {"name": "resourceSpentTypeId", "args": {"type": "consumable", "id": "44"}}, "amount": "1"}, coin_reward(300), "Реликвии", False, 7),
        q_template("relic_shard", "Потрать 10 осколков реликвии", "spendRelicShard", "spendRelicShard", "LIB_QUEST_TRANSLATE_SPENDRELICSHARD", "{day_label}", {"eventFunc": {"name": "spendRelicShard"}, "amount": "10"}, coin_reward(22500), "Реликвии", False, 1),
    ]

    for item in items:
        catalog[item.key] = asdict(item)

    # Human-readable chest templates used in project only
    chest_templates = {
        "chest_1": [{"kind": "stamina", "item": "Энергия", "qty": 50}, {"kind": "gold", "item": "Золото", "qty": 30000}, {"kind": "consumable", "item": "Зелье Титана", "qty": 250}, {"kind": "consumable", "item": "Лутбокс VS героический", "qty": 1}, {"kind": "consumable", "item": "Лутбокс VS титаны", "qty": 1}],
        "chest_2": [{"kind": "stamina", "item": "Энергия", "qty": 100}, {"kind": "gold", "item": "Золото", "qty": 50000}, {"kind": "consumable", "item": "Зелье Титана", "qty": 500}, {"kind": "consumable", "item": "Лутбокс VS героический", "qty": 2}, {"kind": "consumable", "item": "Лутбокс VS титаны", "qty": 2}],
        "chest_3": [{"kind": "patron", "item": "Универсальный осколок реликвии", "qty": 1}, {"kind": "consumable", "item": "Бутылка энергии", "qty": 1}, {"kind": "consumable", "item": "Зелье Титана", "qty": 1250}, {"kind": "consumable", "item": "Лутбокс VS героический", "qty": 3}, {"kind": "consumable", "item": "Лутбокс VS титаны", "qty": 3}],
        "chest_4": [{"kind": "stamina", "item": "Энергия", "qty": 200}, {"kind": "coin", "item": "Рунный камень", "qty": 250}, {"kind": "consumable", "item": "Лутбокс VS героический", "qty": 3}, {"kind": "consumable", "item": "Лутбокс VS титаны", "qty": 3}],
        "chest_5": [{"kind": "stamina", "item": "Энергия", "qty": 300}, {"kind": "coin", "item": "Рунный камень", "qty": 350}, {"kind": "consumable", "item": "Лутбокс VS героический", "qty": 4}, {"kind": "consumable", "item": "Лутбокс VS титаны", "qty": 4}],
        "chest_6": [{"kind": "patron", "item": "Универсальный осколок реликвии", "qty": 1}, {"kind": "consumable", "item": "Бутылка энергии", "qty": 2}, {"kind": "consumable", "item": "Лутбокс VS героический", "qty": 5}, {"kind": "consumable", "item": "Лутбокс VS титаны", "qty": 5}, {"kind": "consumable", "item": "Лутбокс с именными осколками реликвий", "qty": 2}],
        "chest_7": [{"kind": "consumable", "item": "Бутылка энергии", "qty": 2}, {"kind": "coin", "item": "Рунный камень", "qty": 550}, {"kind": "consumable", "item": "Лутбокс VS героический", "qty": 5}, {"kind": "consumable", "item": "Лутбокс VS титаны", "qty": 5}],
        "chest_8": [{"kind": "consumable", "item": "Бутылка энергии", "qty": 3}, {"kind": "coin", "item": "Рунный камень", "qty": 750}, {"kind": "consumable", "item": "Лутбокс VS героический", "qty": 7}, {"kind": "consumable", "item": "Лутбокс VS титаны", "qty": 7}],
        "chest_9": [{"kind": "patron", "item": "Универсальный осколок реликвии", "qty": 2}, {"kind": "consumable", "item": "Бутылка энергии", "qty": 5}, {"kind": "consumable", "item": "Лутбокс продвинутый геройский", "qty": 5}, {"kind": "consumable", "item": "Лутбокс продвинутый титанический", "qty": 5}, {"kind": "consumable", "item": "Лутбокс с именными осколками реликвий", "qty": 5}],
    }

    day_templates = {
        "day_1": asdict(DayTemplate("day_1", "День 1 - Мощь Титанов", "GUILDVERSUS_UI_DAYTITLE_1", ["titan_power", "open_summoning", "open_elemental", "arena", "tower", "daily", "spend_spark", "spend_rune", "heroic_chest", "vip"], chest_templates["chest_1"])),
        "day_2": asdict(DayTemplate("day_2", "День 2 - Облики Героев", "GUILDVERSUS_UI_DAYTITLE_2", ["skin_hero", "outland", "arena", "expedition", "tower", "daily", "spend_artifact_fragment", "use_titan_potion", "artifact_chest", "vip"], chest_templates["chest_2"])),
        "day_3": asdict(DayTemplate("day_3", "День 3 - Экипировка героев", "GUILDVERSUS_UI_DAYTITLE_3", ["hero_red", "hero_orange", "hero_purple", "hero_blue", "hero_green", "hero_white", "spend_artifact_fragment", "arena", "daily", "tower", "fairy_dust", "energy", "vip"], chest_templates["chest_3"])),
        "day_4": asdict(DayTemplate("day_4", "День 4 - Мастерство рун", "GUILDVERSUS_UI_DAYTITLE_4", ["rune_sphere", "spend_rune", "grand_arena", "arena", "daily", "hero_soul", "skin_titan", "heroic_chest", "vip"], chest_templates["chest_4"])),
        "day_5": asdict(DayTemplate("day_5", "День 5 - Мощь героев", "GUILDVERSUS_UI_DAYTITLE_5", ["hero_power", "hero_red", "hero_orange", "hero_purple", "hero_blue", "hero_green", "hero_white", "spend_spark", "arena", "tower", "daily", "energy", "vip"], chest_templates["chest_5"])),
        "day_6": asdict(DayTemplate("day_6", "День 6 - Улучшение реликвий", "GUILDVERSUS_UI_DAYTITLE_6", ["relic_shard", "hydra", "arena", "expedition", "tower", "daily", "chaos_core", "mastery", "metacube", "vip"], chest_templates["chest_6"])),
    }

    project["catalog"] = catalog
    project["day_templates"] = day_templates


# =========================
# Project mutation helpers
# =========================

def log_change(project: Dict[str, Any], action: str, entity: str, scope: str, old_value: Any, new_value: Any) -> None:
    project["change_log"].append(asdict(ChangeLogEntry(
        ts=now_str(),
        action=action,
        entity=entity,
        scope=scope,
        old_value=str(old_value),
        new_value=str(new_value),
    )))
    project["meta"]["updated_at"] = now_str()


def build_s23_season(project: Dict[str, Any]) -> None:
    assignments = {}
    template_order = ["day_1", "day_2", "day_3", "day_4", "day_5", "day_6"]
    for battle in range(1, 5):
        for day_num, template_key in enumerate(template_order, start=1):
            assignments[f"{battle}_{day_num}"] = {
                "battle": battle,
                "day": day_num,
                "template_key": template_key,
                "name_ru": project["day_templates"][template_key]["name_ru"],
                "day_title_key": project["day_templates"][template_key]["day_title_key"],
                "quests": deep_clone(project["day_templates"][template_key]["quests"]),
                "chest_rewards": deep_clone(project["day_templates"][template_key]["chest_rewards"]),
            }
    old = deep_clone(project["season"].get("day_assignments", {}))
    project["season"]["day_assignments"] = assignments
    log_change(project, "добавлено", "season", "S23 template", f"days={len(old)}", f"days={len(assignments)}")


def get_day_keys(project: Dict[str, Any]) -> List[str]:
    keys = list(project["season"]["day_assignments"].keys())
    return sorted(keys, key=lambda k: (project["season"]["day_assignments"][k]["battle"], project["season"]["day_assignments"][k]["day"]))


def remove_quest_from_all_battles_same_day(project: Dict[str, Any], template_day_num: int, quest_key: str) -> int:
    count = 0
    for day_key, day in project["season"]["day_assignments"].items():
        if day["day"] == template_day_num and quest_key in day["quests"]:
            old = deep_clone(day["quests"])
            day["quests"] = [q for q in day["quests"] if q != quest_key]
            count += 1
            log_change(project, "удалено", "quest", f"battle {day['battle']} day {day['day']}", old, day["quests"])
    return count


def replace_quest(project: Dict[str, Any], scope_mode: str, source_key: str, target_key: str, day_num: Optional[int] = None) -> int:
    count = 0
    for _, day in project["season"]["day_assignments"].items():
        if scope_mode == "day" and day_num is not None and day["day"] != day_num:
            continue
        if source_key in day["quests"]:
            old = deep_clone(day["quests"])
            day["quests"] = [target_key if q == source_key else q for q in day["quests"]]
            count += 1
            log_change(project, "заменено", "quest", f"battle {day['battle']} day {day['day']}", old, day["quests"])
    return count


def save_day_as_preset(project: Dict[str, Any], day_key: str, preset_name: str) -> None:
    day = project["season"]["day_assignments"][day_key]
    project["saved_day_presets"][preset_name] = deep_clone(day)
    log_change(project, "добавлено", "preset", preset_name, "", day["name_ru"])


def apply_preset_to_day(project: Dict[str, Any], day_key: str, preset_name: str) -> None:
    preset = deep_clone(project["saved_day_presets"][preset_name])
    current = project["season"]["day_assignments"][day_key]
    old = deep_clone(current)
    project["season"]["day_assignments"][day_key].update({
        "template_key": preset.get("template_key"),
        "name_ru": preset.get("name_ru"),
        "day_title_key": preset.get("day_title_key"),
        "quests": preset.get("quests", []),
        "chest_rewards": preset.get("chest_rewards", []),
    })
    log_change(project, "изменено", "day", day_key, old, project["season"]["day_assignments"][day_key])


# =========================
# Generation logic
# =========================

def calculate_counts(project: Dict[str, Any]) -> Dict[str, int]:
    days = len(project["season"]["day_assignments"])
    quests = sum(len(day["quests"]) for day in project["season"]["day_assignments"].values())
    return {
        "type": days,
        "chain": quests,
        "quest": quests,
        "days": days,
        "quest_instances": quests,
    }


def validate_project(project: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    catalog = project["catalog"]
    assignments = project["season"]["day_assignments"]

    if not assignments:
        errors.append("В сезоне нет дней. Сначала соберите сезон по шаблону S23 или импортируйте проект.")

    for day_key, day in assignments.items():
        if not day.get("quests"):
            errors.append(f"{day_key}: день без квестов")
        for q in day.get("quests", []):
            if q not in catalog:
                errors.append(f"{day_key}: неизвестный квест {q}")
            elif catalog[q].get("risky"):
                warnings.append(f"{day_key}: в составе есть рискованный квест {catalog[q]['name_ru']}")

    id_plan = project["id_plan"]
    starts_set = [id_plan.get("type_start"), id_plan.get("chain_start"), id_plan.get("quest_start")]
    if any(x is not None for x in starts_set) and not all(isinstance(x, int) and x > 0 for x in starts_set):
        warnings.append("Не все стартовые ID заданы корректно. Генерация ссылок может быть неполной.")

    return errors, warnings


def generate_rows(project: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    catalog = project["catalog"]
    appear_ident = project["meta"]["appearIdent"]
    assignments = project["season"]["day_assignments"]
    id_plan = project["id_plan"]

    type_counter = id_plan["type_start"] if isinstance(id_plan.get("type_start"), int) else 1
    chain_counter = id_plan["chain_start"] if isinstance(id_plan.get("chain_start"), int) else 1
    quest_counter = id_plan["quest_start"] if isinstance(id_plan.get("quest_start"), int) else 1

    type_rows: List[Dict[str, Any]] = []
    chain_rows: List[Dict[str, Any]] = []
    quest_rows: List[Dict[str, Any]] = []

    for day_key in get_day_keys(project):
        day = assignments[day_key]
        event_id = type_counter
        type_row = {
            "id": event_id,
            "sortOrder": 100,
            "_label": f"{project['meta']['season_code']} {day['name_ru']} - баттл {day['battle']} раунд {day['day']}",
            "requirement": safe_json_dumps({
                "questEventGroup": {"groupId": 200 + day["battle"] * 10 + day["day"], "order": 1},
                "enable": 1,
            }),
            "name_localeKey": "LIB_SPECIAL_QUEST_EVENT_NAME_PICKER",
            "desc_localeKey": "LIB_SPECIAL_QUEST_EVENT_NAME_PICKER",
            "localeKey": "LIB_SPECIAL_QUEST_EVENT_NAME_PICKER",
            "eventLoopData": safe_json_dumps({"group": 200 + day["battle"] * 10 + day["day"], "groupOrder": 1, "duration": 1}),
            "tab_icon": safe_json_dumps({"imagePath": "Btn_quest_picker_event_162x78.png"}),
            "back_image": safe_json_dumps({"imagePath": "background_picker_event_1400_640.png"}),
            "exchangeRule": "",
            "networkIdent": "ios,android",
            "clientData": safe_json_dumps({"hideInSpecialQuestPopup": 1, "parseQuestsReward": True}),
            "assets": "",
            "appearIdent": appear_ident,
        }
        type_rows.append(type_row)
        type_counter += 1

        for idx, quest_key in enumerate(day["quests"], start=1):
            tmpl = catalog[quest_key]
            chain_id = chain_counter
            chain_row = {
                "id": chain_id,
                "eventId": event_id,
                "_label": f"{project['meta']['season_code']} {day['name_ru']} - баттл {day['battle']} раунд {day['day']} квест {idx}",
                "localeKey": tmpl["locale_key"],
                "sortOrder": 1,
                "repeatData": safe_json_dumps({"enable": 1}),
                "appearIdent": appear_ident,
            }
            chain_rows.append(chain_row)
            chain_counter += 1

            quest_row = {
                "id": quest_counter,
                "translationMethod": tmpl["translation_method"],
                "label": f"{project['meta']['season_code']} {day['name_ru']} - баттл {day['battle']} раунд {day['day']} квест {idx}",
                "eventChainId": chain_id,
                "chainOrder": idx,
                "farmCondition": safe_json_dumps(tmpl["farm_condition"]),
                "reward": safe_json_dumps(tmpl["reward"]),
                "alterRewardRequirement": "",
                "alterReward": "",
                "rewardSorting": tmpl.get("reward_sorting", idx),
                "disabled": tmpl.get("disabled", 0),
                "daily": tmpl.get("daily", 0),
                "appearIdent": appear_ident,
            }
            quest_rows.append(quest_row)
            quest_counter += 1

    generated = {"type_rows": type_rows, "chain_rows": chain_rows, "quest_rows": quest_rows}
    project["generated"] = generated
    return generated


# =========================
# Import / export helpers
# =========================

def project_to_json_bytes(project: Dict[str, Any]) -> bytes:
    return json.dumps(project, ensure_ascii=False, indent=2).encode("utf-8")


def build_zip_export(project: Dict[str, Any]) -> bytes:
    if not project["generated"]["type_rows"]:
        generate_rows(project)

    type_df = pd.DataFrame(project["generated"]["type_rows"])
    chain_df = pd.DataFrame(project["generated"]["chain_rows"])
    quest_df = pd.DataFrame(project["generated"]["quest_rows"])

    buff = io.BytesIO()
    with zipfile.ZipFile(buff, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("specialQuestEvent_type.csv", csv_bytes_from_df(type_df))
        zf.writestr("specialQuestEvent_chain.csv", csv_bytes_from_df(chain_df))
        zf.writestr("quest_special.csv", csv_bytes_from_df(quest_df))
        zf.writestr("project.json", project_to_json_bytes(project))
    buff.seek(0)
    return buff.read()


def read_uploaded_csv(uploaded_file) -> pd.DataFrame:
    return pd.read_csv(uploaded_file)


def read_pasted_table(text: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(text), sep=None, engine="python")


def import_project_json(file) -> Dict[str, Any]:
    return json.load(file)


# =========================
# UI components
# =========================

def sidebar_project_summary(project: Dict[str, Any]) -> None:
    counts = calculate_counts(project)
    st.sidebar.header("Проект")
    st.sidebar.write(project["meta"]["project_name"])
    st.sidebar.caption(f"Сезон: {project['meta']['season_name']}")
    st.sidebar.caption(f"Appear: {project['meta']['appearIdent']}")
    st.sidebar.metric("Дней", counts["days"])
    st.sidebar.metric("Квестов", counts["quest_instances"])
    st.sidebar.metric("Type", counts["type"])
    st.sidebar.metric("Chain", counts["chain"])
    st.sidebar.metric("Quest", counts["quest"])


def page_project(project: Dict[str, Any]) -> None:
    st.subheader("Проект")
    c1, c2 = st.columns(2)
    with c1:
        project["meta"]["project_name"] = st.text_input("Название проекта", value=project["meta"]["project_name"])
        project["meta"]["season_name"] = st.text_input("Название сезона", value=project["meta"]["season_name"])
        project["meta"]["season_code"] = st.text_input("Код сезона", value=project["meta"]["season_code"])
    with c2:
        project["meta"]["appearIdent"] = st.text_input("appearIdent", value=project["meta"]["appearIdent"])
        project["meta"]["start_date"] = st.text_input("Дата старта", value=project["meta"]["start_date"])
        project["meta"]["end_date"] = st.text_input("Дата конца", value=project["meta"]["end_date"])

    col_a, col_b, col_c = st.columns(3)
    if col_a.button("Собрать сезон по шаблону S23", use_container_width=True):
        build_s23_season(project)
        st.success("Шаблон S23 применен")
    if col_b.button("Сгенерировать таблицы", use_container_width=True):
        generate_rows(project)
        st.success("Таблицы собраны")
    if col_c.button("Проверить проект", use_container_width=True):
        errors, warnings = validate_project(project)
        if errors:
            for e in errors:
                st.error(e)
        if warnings:
            for w in warnings:
                st.warning(w)
        if not errors and not warnings:
            st.success("Ошибок и предупреждений не найдено")

    st.markdown("### Сохранение / загрузка")
    d1, d2 = st.columns(2)
    with d1:
        st.download_button(
            "Скачать project.json",
            data=project_to_json_bytes(project),
            file_name=f"{slugify(project['meta']['project_name'])}.json",
            mime="application/json",
        )
    with d2:
        uploaded = st.file_uploader("Загрузить project.json", type=["json"], key="project_json")
        if uploaded is not None:
            try:
                st.session_state.project = import_project_json(uploaded)
                ensure_state()
                st.success("Проект загружен")
            except Exception as exc:
                st.error(f"Не удалось загрузить проект: {exc}")


def page_catalog(project: Dict[str, Any]) -> None:
    st.subheader("Каталог квестов")
    catalog = project["catalog"]
    search = st.text_input("Поиск по имени / ключу")
    category = st.selectbox("Категория", ["Все"] + sorted({v["category"] for v in catalog.values()}))

    filtered = []
    for key, item in catalog.items():
        hay = f"{key} {item['name_ru']} {item['technical_name']} {item['locale_key']}".lower()
        if search and search.lower() not in hay:
            continue
        if category != "Все" and item["category"] != category:
            continue
        filtered.append((key, item))

    st.caption(f"Найдено: {len(filtered)}")
    for key, item in filtered:
        with st.expander(f"{item['name_ru']} [{key}]"):
            left, right = st.columns(2)
            left.write(f"Technical: {item['technical_name']}")
            left.write(f"Translation: {item['translation_method']}")
            left.write(f"Locale: {item['locale_key']}")
            right.write(f"Категория: {item['category']}")
            right.write(f"Рискованный: {'Да' if item.get('risky') else 'Нет'}")
            st.code(safe_json_dumps(item['farm_condition']), language="json")
            st.code(safe_json_dumps(item['reward']), language="json")


def page_templates(project: Dict[str, Any]) -> None:
    st.subheader("Шаблоны дней")
    templates = project["day_templates"]
    template_key = st.selectbox("Шаблон", list(templates.keys()), format_func=lambda x: templates[x]["name_ru"])
    tmpl = templates[template_key]

    st.write(f"Название: {tmpl['name_ru']}")
    st.write(f"Day title key: {tmpl['day_title_key']}")

    quest_names = [project['catalog'][q]['name_ru'] if q in project['catalog'] else q for q in tmpl['quests']]
    st.write("Квесты:")
    st.dataframe(pd.DataFrame({"quest_key": tmpl["quests"], "quest_name": quest_names}), use_container_width=True)

    st.write("Состав сундука:")
    st.dataframe(pd.DataFrame(tmpl["chest_rewards"]), use_container_width=True)


def page_season(project: Dict[str, Any]) -> None:
    st.subheader("Сезон")
    assignments = project["season"]["day_assignments"]
    if not assignments:
        st.info("Сначала соберите сезон по шаблону S23")
        return

    day_options = get_day_keys(project)
    selected_day_key = st.selectbox(
        "День",
        day_options,
        format_func=lambda k: f"Баттл {assignments[k]['battle']} / День {assignments[k]['day']} — {assignments[k]['name_ru']}",
    )
    st.session_state.active_day_key = selected_day_key
    day = assignments[selected_day_key]

    c1, c2 = st.columns([2, 1])
    with c1:
        day["name_ru"] = st.text_input("Название дня", value=day["name_ru"])
        day["day_title_key"] = st.text_input("theme/day title key", value=day["day_title_key"])
    with c2:
        preset_name = st.text_input("Сохранить как шаблон дня", value=f"preset_{day['battle']}_{day['day']}")
        if st.button("Сохранить шаблон дня"):
            save_day_as_preset(project, selected_day_key, preset_name)
            st.success("Шаблон сохранен")

    st.markdown("### Квесты дня")
    current_quests = day["quests"]
    catalog_keys = list(project["catalog"].keys())
    new_quests = st.multiselect(
        "Состав дня",
        catalog_keys,
        default=current_quests,
        format_func=lambda x: f"{project['catalog'][x]['name_ru']} [{'RISK' if project['catalog'][x].get('risky') else x}]",
        key=f"multiselect_{selected_day_key}",
    )
    if new_quests != current_quests:
        old = deep_clone(current_quests)
        day["quests"] = new_quests
        log_change(project, "изменено", "day_quests", selected_day_key, old, new_quests)

    st.dataframe(pd.DataFrame({
        "#": list(range(1, len(day['quests']) + 1)),
        "quest_key": day["quests"],
        "quest_name": [project['catalog'][q]['name_ru'] for q in day['quests']],
        "risky": [project['catalog'][q].get('risky', False) for q in day['quests']],
    }), use_container_width=True)

    st.markdown("### Массовые операции")
    m1, m2 = st.columns(2)
    with m1:
        day_num_for_delete = st.selectbox("Номер дня для массового удаления", [1, 2, 3, 4, 5, 6], key="mass_day_delete")
        quest_for_delete = st.selectbox("Квест для удаления", catalog_keys, format_func=lambda x: project['catalog'][x]['name_ru'], key="mass_quest_delete")
        if st.button("Удалить квест из всех баттлов этого дня"):
            changed = remove_quest_from_all_battles_same_day(project, day_num_for_delete, quest_for_delete)
            st.success(f"Изменено дней: {changed}")
    with m2:
        scope_mode = st.radio("Область замены", ["day", "all"], horizontal=True, format_func=lambda x: "Только этот день во всех баттлах" if x == "day" else "Весь проект")
        day_num_for_replace = st.selectbox("Номер дня", [1, 2, 3, 4, 5, 6], key="mass_day_replace")
        source_q = st.selectbox("Заменить квест", catalog_keys, format_func=lambda x: project['catalog'][x]['name_ru'], key="source_q")
        target_q = st.selectbox("На квест", catalog_keys, format_func=lambda x: project['catalog'][x]['name_ru'], key="target_q")
        if st.button("Заменить квест"):
            changed = replace_quest(project, scope_mode, source_q, target_q, day_num_for_replace)
            st.success(f"Изменено дней: {changed}")

    if project["saved_day_presets"]:
        st.markdown("### Применить сохраненный шаблон")
        preset = st.selectbox("Шаблон", list(project["saved_day_presets"].keys()))
        if st.button("Применить шаблон к текущему дню"):
            apply_preset_to_day(project, selected_day_key, preset)
            st.success("Шаблон применен")


def page_chests(project: Dict[str, Any]) -> None:
    st.subheader("Конструктор сундуков")
    assignments = project["season"]["day_assignments"]
    if not assignments:
        st.info("Сначала соберите сезон")
        return
    selected_day_key = st.selectbox(
        "День для редактирования сундука",
        get_day_keys(project),
        format_func=lambda k: f"Баттл {assignments[k]['battle']} / День {assignments[k]['day']} — {assignments[k]['name_ru']}",
        key="chest_day_key",
    )
    day = assignments[selected_day_key]
    chest_df = pd.DataFrame(day["chest_rewards"])
    st.dataframe(chest_df, use_container_width=True)

    st.markdown("### Добавить строку в сундук")
    c1, c2, c3 = st.columns(3)
    kind = c1.text_input("Тип", value="consumable")
    item = c2.text_input("Предмет", value="Новая награда")
    qty = c3.number_input("Количество", min_value=0, step=1, value=1)
    if st.button("Добавить награду"):
        old = deep_clone(day["chest_rewards"])
        day["chest_rewards"].append({"kind": kind, "item": item, "qty": int(qty)})
        log_change(project, "добавлено", "chest_reward", selected_day_key, old, day["chest_rewards"])
        st.success("Награда добавлена")

    st.markdown("### Удалить строку")
    if day["chest_rewards"]:
        idx = st.number_input("Индекс строки", min_value=0, max_value=len(day["chest_rewards"]) - 1, value=0, step=1)
        if st.button("Удалить награду"):
            old = deep_clone(day["chest_rewards"])
            del day["chest_rewards"][idx]
            log_change(project, "удалено", "chest_reward", selected_day_key, old, day["chest_rewards"])
            st.success("Награда удалена")


def page_ids_and_build(project: Dict[str, Any]) -> None:
    st.subheader("ID и сборка таблиц")
    counts = calculate_counts(project)
    st.write({
        "type": counts["type"],
        "chain": counts["chain"],
        "quest": counts["quest"],
    })

    c1, c2, c3 = st.columns(3)
    project["id_plan"]["type_start"] = c1.number_input("Стартовый ID type", min_value=1, step=1, value=int(project['id_plan']['type_start'] or 1))
    project["id_plan"]["chain_start"] = c2.number_input("Стартовый ID chain", min_value=1, step=1, value=int(project['id_plan']['chain_start'] or 1))
    project["id_plan"]["quest_start"] = c3.number_input("Стартовый ID quest", min_value=1, step=1, value=int(project['id_plan']['quest_start'] or 1))

    st.caption(
        f"Диапазоны: type {project['id_plan']['type_start']}–{project['id_plan']['type_start'] + counts['type'] - 1}, "
        f"chain {project['id_plan']['chain_start']}–{project['id_plan']['chain_start'] + counts['chain'] - 1}, "
        f"quest {project['id_plan']['quest_start']}–{project['id_plan']['quest_start'] + counts['quest'] - 1}"
    )

    if st.button("Собрать финальные строки"):
        generate_rows(project)
        st.success("Финальные строки собраны")

    generated = project["generated"]
    if generated["type_rows"]:
        st.markdown("### Предпросмотр type")
        st.dataframe(pd.DataFrame(generated["type_rows"]).head(20), use_container_width=True)
        st.markdown("### Предпросмотр chain")
        st.dataframe(pd.DataFrame(generated["chain_rows"]).head(20), use_container_width=True)
        st.markdown("### Предпросмотр quest")
        st.dataframe(pd.DataFrame(generated["quest_rows"]).head(20), use_container_width=True)


def page_validation(project: Dict[str, Any]) -> None:
    st.subheader("Валидация")
    errors, warnings = validate_project(project)
    if errors:
        for e in errors:
            st.error(e)
    if warnings:
        for w in warnings:
            st.warning(w)
    if not errors and not warnings:
        st.success("Валидация пройдена")

    counts = calculate_counts(project)
    st.write("Автоматический пересчет:")
    st.json(counts)


def page_import(project: Dict[str, Any]) -> None:
    st.subheader("Импорт")
    mode = st.radio("Источник", ["CSV", "Вставка таблицы"], horizontal=True)
    table_name = st.selectbox("Таблица", ["specialQuestEvent_type", "specialQuestEvent_chain", "quest_special"])

    if mode == "CSV":
        up = st.file_uploader("Загрузить CSV", type=["csv"])
        if up is not None:
            try:
                df = read_uploaded_csv(up)
                st.dataframe(df.head(30), use_container_width=True)
                st.info("В MVP импорт показывает данные и помогает проверить структуру. Автоматическая реконструкция проекта из 3 таблиц может быть добавлена следующим этапом.")
            except Exception as exc:
                st.error(f"Ошибка чтения CSV: {exc}")
    else:
        text = st.text_area("Вставьте таблицу", height=260)
        if text.strip():
            try:
                df = read_pasted_table(text)
                st.dataframe(df.head(30), use_container_width=True)
            except Exception as exc:
                st.error(f"Ошибка разбора таблицы: {exc}")


def page_export(project: Dict[str, Any]) -> None:
    st.subheader("Экспорт")
    if st.button("Пересобрать перед экспортом"):
        generate_rows(project)
        st.success("Таблицы пересобраны")

    if not project["generated"]["type_rows"]:
        st.info("Сначала соберите таблицы")
        return

    type_df = pd.DataFrame(project["generated"]["type_rows"])
    chain_df = pd.DataFrame(project["generated"]["chain_rows"])
    quest_df = pd.DataFrame(project["generated"]["quest_rows"])

    st.download_button("Скачать specialQuestEvent_type.csv", csv_bytes_from_df(type_df), "specialQuestEvent_type.csv", "text/csv")
    st.download_button("Скачать specialQuestEvent_chain.csv", csv_bytes_from_df(chain_df), "specialQuestEvent_chain.csv", "text/csv")
    st.download_button("Скачать quest_special.csv", csv_bytes_from_df(quest_df), "quest_special.csv", "text/csv")
    st.download_button("Скачать ZIP (3 CSV + project.json)", build_zip_export(project), "vs_season_export.zip", "application/zip")


def page_change_log(project: Dict[str, Any]) -> None:
    st.subheader("Журнал изменений")
    if not project["change_log"]:
        st.info("Журнал пока пуст")
        return
    df = pd.DataFrame(project["change_log"])
    st.dataframe(df.sort_values("ts", ascending=False), use_container_width=True)


# =========================
# Main app
# =========================

def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    ensure_state()
    project = st.session_state.project

    st.title(APP_TITLE)
    sidebar_project_summary(project)

    page = st.sidebar.radio(
        "Раздел",
        [
            "Проект",
            "Каталог квестов",
            "Шаблоны дней",
            "Сезон",
            "Сундуки",
            "ID и сборка",
            "Валидация",
            "Импорт",
            "Экспорт",
            "Журнал изменений",
        ],
    )

    if page == "Проект":
        page_project(project)
    elif page == "Каталог квестов":
        page_catalog(project)
    elif page == "Шаблоны дней":
        page_templates(project)
    elif page == "Сезон":
        page_season(project)
    elif page == "Сундуки":
        page_chests(project)
    elif page == "ID и сборка":
        page_ids_and_build(project)
    elif page == "Валидация":
        page_validation(project)
    elif page == "Импорт":
        page_import(project)
    elif page == "Экспорт":
        page_export(project)
    elif page == "Журнал изменений":
        page_change_log(project)


if __name__ == "__main__":
    main()
