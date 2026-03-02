import streamlit as st
import json
import random
import os
import uuid
from openai import OpenAI

# ==============================
# CONFIG
# ==============================

MODEL = "gpt-4o-mini"
client = OpenAI()

SAVE_DIR = "saves"
os.makedirs(SAVE_DIR, exist_ok=True)

# ==============================
# UTILS
# ==============================

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

# ==============================
# INIT SESSION
# ==============================

if "hero" not in st.session_state:
    st.session_state.hero = None

if "current_event" not in st.session_state:
    st.session_state.current_event = None

if "last_result_text" not in st.session_state:
    st.session_state.last_result_text = None

# ==============================
# HERO SELECTION
# ==============================

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
                "history": [],
                "location": "Таверна у дороги",
                "known_npcs": [],
                "active_threads": [],
                "is_alive": True,
                "turn_count": 0
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

# ==============================
# SIDEBAR
# ==============================

st.sidebar.header(hero["name"])
st.sidebar.write(f"Класс: {hero['class']}")
st.sidebar.write(f"HP: {hero['hp']}")
st.sidebar.write(f"Локация: {hero['location']}")

st.sidebar.subheader("Характеристики")
for stat, value in hero["stats"].items():
    st.sidebar.write(f"{stat.capitalize()}: {value}")

st.sidebar.subheader("Инвентарь")
st.sidebar.write(hero["inventory"] if hero["inventory"] else "Пусто")

# ==============================
# DEATH CHECK
# ==============================

if not hero["is_alive"]:
    st.error(f"{hero['name']} погиб после {hero['turn_count']} ходов.")
    st.write(hero.get("epitaph", ""))
    st.stop()

# ==============================
# SHOW LAST RESULT (НЕ ПРОПАДАЕТ)
# ==============================

if st.session_state.last_result_text:
    st.markdown("### Итог прошлого действия")
    st.write(st.session_state.last_result_text)

# ==============================
# GENERATE EVENT
# ==============================

if st.session_state.current_event is None:

    system_prompt = """
Ты — мастер подземелий в стиле Baldur’s Gate 3.
Ты создаёшь связную кампанию, а не отдельные случайные сцены.

Главные правила:
- Событие должно логически продолжать предыдущую сцену.
- Мир последователен: локации и NPC не исчезают без причины.
- Если появляется новый персонаж, он должен иметь имя, характер и мотив.
- Каждое событие должно нести выбор с последствиями.
- Выборы должны быть морально неоднозначными.
- Иногда решения должны иметь долгосрочные последствия.
- Не телепортируй героя без объяснения.
- Избегай случайных несвязанных событий.

Стиль:
- Атмосферный, кинематографичный.
- 120–160 слов.
- 2–3 значимых варианта.

Отвечай строго JSON:
{
  "event_text": "...",
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
Характеристики: {hero['stats']}
Инвентарь: {hero['inventory']}

Текущая локация: {hero['location']}
Известные NPC: {hero['known_npcs']}
Активные сюжетные линии: {hero['active_threads']}

Последние события:
{hero['history'][-3:]}

Продолжи историю логично.
"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.8,
        max_tokens=500
    )

    event_data = safe_json_parse(response.choices[0].message.content)

    if not event_data:
        st.error("Ошибка генерации события.")
        st.stop()

    st.session_state.current_event = event_data

event = st.session_state.current_event

st.markdown("### Событие")
st.write(event["event_text"])

st.markdown("### Выберите действие")

# ==============================
# HANDLE CHOICE
# ==============================

for choice in event["choices"]:
    if st.button(choice["text"], key=choice["id"]):

        consequence_prompt = """
Ты рассчитываешь последствия действия в фэнтези RPG.

Отвечай строго JSON:
{
  "result_text": "...",
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
  }
}
"""

        consequence_user = f"""
Герой: {hero['name']}
Локация: {hero['location']}
Выбор: {choice['text']}
Определи логичные последствия.
"""

        result_response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": consequence_prompt},
                {"role": "user", "content": consequence_user}
            ],
            temperature=0.8,
            max_tokens=400
        )

        result_data = safe_json_parse(result_response.choices[0].message.content)

        if not result_data:
            st.error("Ошибка генерации последствий.")
            st.stop()

        effects = result_data["effects"]

        # Apply effects
        hero["hp"] = clamp(hero["hp"] + effects.get("hp", 0), 0, 200)

        for stat in hero["stats"]:
            hero["stats"][stat] = clamp(
                hero["stats"][stat] + effects.get(stat, 0), 1, 20
            )

        if effects.get("add_item"):
            hero["inventory"].append(effects["add_item"])

        if effects.get("remove_item") in hero["inventory"]:
            hero["inventory"].remove(effects["remove_item"])

        if effects.get("new_location"):
            hero["location"] = effects["new_location"]

        if effects.get("new_npc"):
            hero["known_npcs"].append(effects["new_npc"])

        if effects.get("new_thread"):
            hero["active_threads"].append(effects["new_thread"])

        hero["turn_count"] += 1

        hero["history"].append({
            "event": event["event_text"],
            "choice": choice["text"],
            "result": result_data["result_text"]
        })

        st.session_state.last_result_text = result_data["result_text"]

        if hero["hp"] <= 0:
            hero["is_alive"] = False
            hero["epitaph"] = f"{hero['name']} пал в {hero['location']}."

        save_hero(hero)

        st.session_state.current_event = None
        st.rerun()

# ==============================
# HISTORY VIEW
# ==============================

st.markdown("### Последние события")
for h in hero["history"][-5:]:
    st.write(f"- {h['choice']} → {h['result']}")