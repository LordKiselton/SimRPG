import streamlit as st
import json
import random
import os
import uuid
from openai import OpenAI

# =========================
# CONFIG
# =========================

MODEL = "gpt-4o-mini"
client = OpenAI()

SAVE_DIR = "saves"
os.makedirs(SAVE_DIR, exist_ok=True)

# =========================
# UTILS
# =========================

def clamp(value, min_v, max_v):
    return max(min_v, min(value, max_v))

def safe_json_parse(text):
    try:
        return json.loads(text)
    except:
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

# =========================
# SESSION INIT
# =========================

if "hero" not in st.session_state:
    st.session_state.hero = None

if "scene_data" not in st.session_state:
    st.session_state.scene_data = None

# =========================
# HERO SELECTION
# =========================

heroes = load_heroes()
alive_heroes = [h for h in heroes if h.get("is_alive", True)]
hero_names = [h["name"] for h in alive_heroes]
hero_names.append("Создать нового героя")

selected = st.selectbox("Выберите героя", hero_names)

if selected == "Создать нового героя":
    with st.form("new_hero"):
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
                "is_alive": True
            }

            save_hero(hero)
            st.session_state.hero = hero
            st.rerun()

elif st.session_state.hero is None or st.session_state.hero["name"] != selected:
    hero = next(h for h in alive_heroes if h["name"] == selected)
    st.session_state.hero = hero

hero = st.session_state.hero

if hero is None:
    st.stop()

# =========================
# SIDEBAR
# =========================

st.sidebar.header(hero["name"])
st.sidebar.write(f"Класс: {hero['class']}")
st.sidebar.write(f"HP: {hero['hp']}")
st.sidebar.write(f"Локация: {hero['location']}")

st.sidebar.subheader("Статы")
for s, v in hero["stats"].items():
    st.sidebar.write(f"{s.capitalize()}: {v}")

st.sidebar.subheader("Инвентарь")
st.sidebar.write(hero["inventory"] if hero["inventory"] else "Пусто")

# =========================
# GENERATE SCENE
# =========================

def generate_scene(hero, previous_choice=None):

    system_prompt = """
Ты — мастер подземелий в стиле Baldur’s Gate 3.
Ты создаёшь связную кампанию, а не отдельные сцены.

Правила:
- Сцена должна логично продолжать предыдущую.
- Мир последователен.
- Если герой умирает, опиши его смерть.
- Текст 120–160 слов.
- 2–3 осмысленных варианта действий.
- Без повторов предыдущего текста.

Отвечай строго JSON:

{
  "scene_text": "...",
  "effects": {
    "hp": -5,
    "strength": 0,
    "dexterity": 0,
    "intelligence": 0,
    "constitution": 0,
    "charisma": 0,
    "add_item": null,
    "remove_item": null,
    "new_location": null,
    "new_npc": null,
    "new_thread": null
  },
  "choices": [
    {"id": "a", "text": "..."},
    {"id": "b", "text": "..."}
  ]
}
"""

    user_prompt = f"""
Герой: {hero['name']}
Класс: {hero['class']}
HP: {hero['hp']}
Статы: {hero['stats']}
Инвентарь: {hero['inventory']}
Локация: {hero['location']}
NPC: {hero['known_npcs']}
Активные линии: {hero['active_threads']}
Последние события: {hero['history'][-3:]}

Предыдущий выбор: {previous_choice}

Продолжи историю.
"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.8,
        max_tokens=600
    )

    return safe_json_parse(response.choices[0].message.content)

# =========================
# FIRST LOAD
# =========================

if st.session_state.scene_data is None:
    st.session_state.scene_data = generate_scene(hero)

scene = st.session_state.scene_data

if not scene:
    st.error("Ошибка генерации сцены.")
    st.stop()

# =========================
# DISPLAY SCENE
# =========================

st.markdown("### Сцена")
st.write(scene["scene_text"])

# =========================
# APPLY EFFECTS IF FIRST LOAD OF SCENE
# =========================

if "effects_applied" not in st.session_state:
    st.session_state.effects_applied = False

if not st.session_state.effects_applied:

    effects = scene["effects"]
    changes_log = []

    # HP
    old_hp = hero["hp"]
    hero["hp"] = clamp(hero["hp"] + effects.get("hp", 0), 0, 200)
    if hero["hp"] != old_hp:
        changes_log.append(f"HP: {old_hp} → {hero['hp']}")

    # Stats
    for stat in hero["stats"]:
        old_val = hero["stats"][stat]
        hero["stats"][stat] = clamp(
            hero["stats"][stat] + effects.get(stat, 0), 1, 20
        )
        if hero["stats"][stat] != old_val:
            changes_log.append(f"{stat.capitalize()}: {old_val} → {hero['stats'][stat]}")

    # Inventory
    if effects.get("add_item"):
        hero["inventory"].append(effects["add_item"])
        changes_log.append(f"Получен предмет: {effects['add_item']}")

    if effects.get("remove_item") in hero["inventory"]:
        hero["inventory"].remove(effects["remove_item"])
        changes_log.append(f"Потерян предмет: {effects['remove_item']}")

    # Location
    if effects.get("new_location"):
        hero["location"] = effects["new_location"]

    # NPC
    if effects.get("new_npc"):
        hero["known_npcs"].append(effects["new_npc"])

    # Thread
    if effects.get("new_thread"):
        hero["active_threads"].append(effects["new_thread"])

    hero["turn_count"] += 1
    hero["history"].append(scene["scene_text"])

    if changes_log:
        st.markdown("### Изменения")
        for c in changes_log:
            st.write("- " + c)

    # Death
    if hero["hp"] <= 0:
        hero["is_alive"] = False
        save_hero(hero)
        st.error("Персонаж погиб.")
        st.stop()

    save_hero(hero)
    st.session_state.effects_applied = True

# =========================
# CHOICES
# =========================

st.markdown("### Ваш выбор")

for choice in scene["choices"]:
    if st.button(choice["text"], key=choice["id"]):

        st.session_state.effects_applied = False
        st.session_state.scene_data = generate_scene(hero, previous_choice=choice["text"])
        st.rerun()