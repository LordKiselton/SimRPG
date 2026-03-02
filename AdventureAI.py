import streamlit as st
import json
import random
import os
import uuid
import re
from openai import OpenAI

MODEL = "gpt-4o-mini"
client = OpenAI()

SAVE_DIR = "saves"
os.makedirs(SAVE_DIR, exist_ok=True)


# ===================================
# SAFE UTILS
# ===================================

def clamp(value, min_v, max_v):
    return max(min_v, min(value, max_v))


def safe_json_parse(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except:
            return None
    return None


def get_hero_path(hero_id):
    return os.path.join(SAVE_DIR, f"{hero_id}.json")


def load_hero_by_id(hero_id):
    path = get_hero_path(hero_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return None


def save_hero(hero):
    if not hero or "hero_id" not in hero:
        return
    with open(get_hero_path(hero["hero_id"]), "w", encoding="utf-8") as f:
        json.dump(hero, f, ensure_ascii=False, indent=2)


def load_all_heroes():
    heroes = []
    for file in os.listdir(SAVE_DIR):
        if file.endswith(".json"):
            try:
                with open(os.path.join(SAVE_DIR, file), "r", encoding="utf-8") as f:
                    heroes.append(json.load(f))
            except:
                pass
    return heroes


def delete_hero(hero_id):
    path = get_hero_path(hero_id)
    if os.path.exists(path):
        os.remove(path)


def migrate_hero(hero):
    defaults = {
        "current_scene": None,
        "effects_applied": False,
        "is_alive": True,
        "known_npcs": [],
        "active_threads": [],
        "history": [],
        "turn_count": 0,
        "inventory": [],
        "location": "Неизвестно"
    }

    for k, v in defaults.items():
        hero.setdefault(k, v)

    return hero


# ===================================
# GENERATE SCENE
# ===================================

def generate_scene(hero, previous_choice=None):

    system_prompt = """
Ты — мастер подземелий.
Строгие правила:
- 120–160 слов.
- 2–3 варианта действий.
- Строго JSON.
- Урон не более 20% от текущего HP героя.
- Смерть возможна только после 4-го хода.
- Без случайных изменений статов.
"""

    user_prompt = f"""
Имя: {hero.get('name')}
Класс: {hero.get('class')}
HP: {hero.get('hp')}
Статы: {hero.get('stats')}
Инвентарь: {hero.get('inventory')}
Локация: {hero.get('location')}
История: {hero.get('history')[-5:]}
Предыдущий выбор: {previous_choice}
"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.5,
            max_tokens=700
        )

        parsed = safe_json_parse(response.choices[0].message.content)

        if not parsed:
            return None

        if "scene_text" not in parsed or "choices" not in parsed:
            return None

        parsed.setdefault("effects", {})
        return parsed

    except:
        return None


# ===================================
# SESSION INIT
# ===================================

if "active_hero_id" not in st.session_state:
    st.session_state.active_hero_id = None

heroes = load_all_heroes()
alive = [h for h in heroes if h.get("is_alive", True)]

hero_map = {h.get("name"): h.get("hero_id") for h in alive if "hero_id" in h}

names = list(hero_map.keys())
names.append("➕ Создать героя")

selected = st.selectbox("Выберите героя", names)


# ===================================
# CREATE HERO
# ===================================

if selected == "➕ Создать героя":

    with st.form("create"):
        name = st.text_input("Имя")
        hero_class = st.selectbox("Класс", ["Воин", "Маг", "Вор"])
        ok = st.form_submit_button("Создать")

        if ok and name:

            stats = {
                "strength": random.randint(8, 15),
                "dexterity": random.randint(8, 15),
                "intelligence": random.randint(8, 15),
                "constitution": random.randint(8, 15),
                "charisma": random.randint(8, 15),
            }

            hero = {
                "hero_id": str(uuid.uuid4()),
                "name": name,
                "class": hero_class,
                "stats": stats,
                "hp": stats["constitution"] * 8 + 20,
            }

            hero = migrate_hero(hero)
            save_hero(hero)

            st.session_state.active_hero_id = hero["hero_id"]
            st.rerun()

    st.stop()


# ===================================
# LOAD HERO
# ===================================

if selected not in hero_map:
    st.stop()

hero_id = hero_map[selected]
hero = load_hero_by_id(hero_id)

if not hero:
    st.error("Ошибка загрузки героя")
    st.stop()

hero = migrate_hero(hero)
save_hero(hero)


# ===================================
# DELETE HERO
# ===================================

st.sidebar.markdown("---")
if st.sidebar.button("🗑 Удалить героя"):
    delete_hero(hero_id)
    st.session_state.active_hero_id = None
    st.rerun()


# ===================================
# SIDEBAR
# ===================================

st.sidebar.header(hero.get("name"))
st.sidebar.write(f"HP: {hero.get('hp')}")
st.sidebar.write(f"Ход: {hero.get('turn_count')}")


# ===================================
# GENERATE SCENE SAFE
# ===================================

if hero.get("current_scene") is None:
    scene_data = generate_scene(hero)
    if not scene_data:
        st.error("Ошибка генерации сцены")
        st.stop()

    hero["current_scene"] = scene_data
    hero["effects_applied"] = False
    save_hero(hero)

scene = hero.get("current_scene")

if not scene:
    st.error("Ошибка сцены")
    st.stop()


st.markdown("### Сцена")
st.write(scene.get("scene_text"))


# ===================================
# APPLY EFFECTS (BALANCED)
# ===================================

if not hero.get("effects_applied"):

    effects = scene.get("effects", {})
    hp_change = effects.get("hp", 0)

    # Ограничение максимального урона
    max_damage = max(5, hero["stats"]["constitution"] * 2)

    if hp_change < 0:
        hp_change = max(hp_change, -max_damage)

    # Нельзя умереть в первые 3 хода
    if hero["turn_count"] < 3:
        if hero["hp"] + hp_change <= 0:
            hp_change = -(hero["hp"] - 1)

    hero["hp"] = clamp(hero["hp"] + hp_change, 0, 300)

    hero["turn_count"] += 1
    hero["history"].append(scene.get("scene_text", ""))

    hero["effects_applied"] = True
    save_hero(hero)

    # Проверка смерти
    if hero["hp"] <= 0:
        hero["is_alive"] = False
        hero["current_scene"] = {
            "scene_text": "Вы пали. Ваше приключение окончено.",
            "choices": []
        }
        save_hero(hero)
        st.error("Герой погиб.")
        st.stop()


# ===================================
# CHOICES
# ===================================

for choice in scene.get("choices", []):

    key = f"{hero_id}_{hero.get('turn_count')}_{choice.get('id')}"

    if st.button(choice.get("text"), key=key):
        hero["history"].append(f"Выбор: {choice.get('text')}")

        new_scene = generate_scene(hero, choice.get("text"))
        if not new_scene:
            st.error("Ошибка генерации следующей сцены")
            st.stop()

        hero["current_scene"] = new_scene
        hero["effects_applied"] = False
        save_hero(hero)
        st.rerun()