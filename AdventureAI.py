import streamlit as st
import json
import random
import os
import uuid
import re
from openai import OpenAI

# ===================================
# CONFIG
# ===================================

MODEL = "gpt-4o-mini"
client = OpenAI()

SAVE_DIR = "saves"
os.makedirs(SAVE_DIR, exist_ok=True)

# ===================================
# UTILS
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


def save_hero(hero):
    path = os.path.join(SAVE_DIR, f"{hero['hero_id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(hero, f, ensure_ascii=False, indent=2)


def load_heroes():
    heroes = []
    for file in os.listdir(SAVE_DIR):
        if file.endswith(".json"):
            with open(os.path.join(SAVE_DIR, file), "r", encoding="utf-8") as f:
                heroes.append(json.load(f))
    return heroes


def delete_hero(hero_id):
    path = os.path.join(SAVE_DIR, f"{hero_id}.json")
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
    for key, value in defaults.items():
        hero.setdefault(key, value)
    return hero


# ===================================
# GENERATE SCENE
# ===================================

def generate_scene(hero, previous_choice=None):

    system_prompt = """
Ты — мастер подземелий в стиле Baldur’s Gate 3.

СТРОГИЕ ПРАВИЛА:
- Мир полностью последовательный.
- Никаких случайных изменений характеристик.
- Эффекты ТОЛЬКО как следствие описанных событий.
- Если нет боя/награды — эффекты = 0.
- 120–160 слов.
- 2–3 варианта действий.
- Строго JSON.
"""

    user_prompt = f"""
Имя: {hero['name']}
Класс: {hero['class']}
HP: {hero['hp']}
Статы: {hero['stats']}
Инвентарь: {hero['inventory']}
Локация: {hero['location']}
Последние события: {hero['history'][-5:]}
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

        return parsed

    except:
        return None


# ===================================
# SESSION STATE INIT
# ===================================

if "active_hero_id" not in st.session_state:
    st.session_state.active_hero_id = None

heroes = load_heroes()
alive_heroes = [h for h in heroes if h.get("is_alive", True)]

hero_dict = {h["name"]: h for h in alive_heroes}
hero_names = list(hero_dict.keys())

if not hero_names:
    hero_names = []

hero_names.append("➕ Создать нового героя")

selected = st.selectbox("Выберите героя", hero_names)

# ===================================
# CREATE HERO
# ===================================

if selected == "➕ Создать нового героя":

    with st.form("create_hero"):
        name = st.text_input("Имя героя")
        hero_class = st.selectbox("Класс", ["Воин", "Маг", "Вор"])
        submitted = st.form_submit_button("Создать")

        if submitted and name:

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
                "hp": stats["constitution"] * 5,
                "inventory": [],
                "location": "Таверна у дороги",
                "known_npcs": [],
                "active_threads": [],
                "history": [],
                "turn_count": 0,
                "is_alive": True,
                "current_scene": None,
                "effects_applied": False
            }

            save_hero(hero)
            st.session_state.active_hero_id = hero["hero_id"]
            st.rerun()

    st.stop()

# ===================================
# LOAD HERO SAFE
# ===================================

if selected not in hero_dict:
    st.stop()

hero = migrate_hero(hero_dict[selected])
st.session_state.active_hero_id = hero["hero_id"]
save_hero(hero)

# ===================================
# DELETE HERO
# ===================================

st.sidebar.markdown("---")
if st.sidebar.button("🗑 Удалить героя"):
    delete_hero(hero["hero_id"])
    st.session_state.active_hero_id = None
    st.rerun()

# ===================================
# SIDEBAR
# ===================================

st.sidebar.header(hero["name"])
st.sidebar.write(f"Класс: {hero['class']}")
st.sidebar.write(f"HP: {hero['hp']}")
st.sidebar.write(f"Локация: {hero['location']}")

st.sidebar.subheader("Статы")
for s, v in hero["stats"].items():
    st.sidebar.write(f"{s.capitalize()}: {v}")

st.sidebar.subheader("Инвентарь")
st.sidebar.write(hero["inventory"] if hero["inventory"] else "Пусто")

# ===================================
# GENERATE SCENE SAFE
# ===================================

if hero.get("current_scene") is None:
    hero["current_scene"] = generate_scene(hero)
    hero["effects_applied"] = False
    save_hero(hero)

scene = hero.get("current_scene")

if not scene:
    st.error("Ошибка генерации сцены. Попробуйте обновить.")
    st.stop()

# ===================================
# DISPLAY SCENE
# ===================================

st.markdown("### Сцена")
st.write(scene.get("scene_text", ""))

# ===================================
# APPLY EFFECTS
# ===================================

if not hero["effects_applied"]:

    effects = scene.get("effects", {})

    hero["hp"] = clamp(hero["hp"] + effects.get("hp", 0), 0, 200)

    for stat in hero["stats"]:
        hero["stats"][stat] = clamp(
            hero["stats"][stat] + effects.get(stat, 0),
            1,
            20
        )

    if effects.get("add_item"):
        hero["inventory"].append(effects["add_item"])

    if effects.get("remove_item") in hero["inventory"]:
        hero["inventory"].remove(effects["remove_item"])

    if effects.get("new_location"):
        hero["location"] = effects["new_location"]

    hero["turn_count"] += 1
    hero["history"].append(scene.get("scene_text", ""))

    if hero["hp"] <= 0:
        hero["is_alive"] = False
        save_hero(hero)
        st.error("Персонаж погиб.")
        st.stop()

    hero["effects_applied"] = True
    save_hero(hero)

# ===================================
# CHOICES
# ===================================

st.markdown("### Ваш выбор")

choices = scene.get("choices", [])

for choice in choices:
    key = f"{hero['hero_id']}_{hero['turn_count']}_{choice.get('id')}"

    if st.button(choice.get("text", "Выбрать"), key=key):
        hero["history"].append(f"Игрок выбрал: {choice.get('text')}")
        hero["current_scene"] = generate_scene(hero, previous_choice=choice.get("text"))
        hero["effects_applied"] = False
        save_hero(hero)
        st.rerun()