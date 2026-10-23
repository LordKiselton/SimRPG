import streamlit as st
import json
import random
import os
from openai import OpenAI
import uuid

client = OpenAI()
MODEL = "gpt-4o-mini"

SAVE_DIR = "saves"
os.makedirs(SAVE_DIR, exist_ok=True)

# ----------------------------
# УТИЛИТЫ
# ----------------------------
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

def get_recent_history(hero):
    return hero.get("history", [])[-5:]

# ----------------------------
# СТАРТ / ВЫБОР ГЕРОЯ
# ----------------------------
heroes = load_heroes()
hero_names = [h["name"] for h in heroes if h["is_alive"]]
hero_names.append("Создать нового героя")
selected_hero_name = st.selectbox("Выберите героя", hero_names)

if selected_hero_name == "Создать нового героя":
    with st.form("new_hero_form"):
        name = st.text_input("Имя героя")
        hero_class = st.selectbox("Класс", ["Воин", "Маг", "Вор"])
        submitted = st.form_submit_button("Создать")
        if submitted and name:
            # D&D-подобные статы: Сила, Ловкость, Интеллект, Выносливость, Харизма
            base_stats = {
                "strength": random.randint(8,15),
                "dexterity": random.randint(8,15),
                "intelligence": random.randint(8,15),
                "constitution": random.randint(8,15),
                "charisma": random.randint(8,15)
            }
            hero = {
                "hero_id": str(uuid.uuid4()),
                "name": name,
                "class": hero_class,
                "stats": base_stats,
                "hp": base_stats["constitution"]*5,
                "inventory": [],
                "history": [],
                "is_alive": True,
                "turn_count": 0
            }
            save_hero(hero)
            st.session_state.hero = hero
            st.experimental_rerun()
else:
    hero = next(h for h in heroes if h["name"]==selected_hero_name)
    st.session_state.hero = hero

hero = st.session_state.hero

# ----------------------------
# ПОКАЗ СТАТОВ
# ----------------------------
st.sidebar.header(f"Герой: {hero['name']}")
st.sidebar.write(f"❤️ HP: {hero['hp']}")
for stat, val in hero["stats"].items():
    st.sidebar.write(f"{stat.capitalize()}: {val}")
st.sidebar.write(f"🎒 Инвентарь: {hero['inventory']}")

# ----------------------------
# ПРОВЕРКА СМЕРТИ
# ----------------------------
if not hero["is_alive"]:
    st.error(f"☠️ {hero['name']} погиб после {hero['turn_count']} ходов.")
    st.write("Эпитафия:")
    st.write(hero.get("epitaph", "Здесь будет история героя."))
    if st.button("Начать нового героя"):
        st.session_state.hero = None
        st.experimental_rerun()
    st.stop()

# ----------------------------
# ГЕНЕРАЦИЯ СОБЫТИЯ
# ----------------------------
if "current_event" not in st.session_state or st.session_state.current_event is None:
    system_prompt = """
Ты генератор событий для текстовой фэнтези RPG.
Отвечай строго JSON:
{
  "event_text": "описание события",
  "choices": [
    {"id": "short_id", "text": "текст кнопки"},
    {"id": "short_id2", "text": "текст кнопки"}
  ]
}
Правила:
- 2–3 варианта
- без лишнего текста
- длина описания 80–120 слов
"""
    user_prompt = f"""
Герой:
HP: {hero['hp']}
Stats: {hero['stats']}
Inventory: {hero['inventory']}
Последние события: {get_recent_history(hero)}
Сгенерируй новое событие с вариантами выбора.
"""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role":"system", "content": system_prompt},
            {"role":"user", "content": user_prompt}
        ],
        temperature=0.8,
        max_tokens=400
    )
    event_data = safe_json_parse(response.choices[0].message.content)
    if not event_data:
        st.error("Ошибка генерации события")
        st.stop()
    st.session_state.current_event = event_data

event = st.session_state.current_event
st.write("### 📜 Событие")
st.write(event["event_text"])

st.write("### ⚔️ Выберите действие")
for choice in event["choices"]:
    if st.button(choice["text"], key=choice["id"]):
        system_prompt = """
Ты рассчитываешь последствия действия в фэнтези RPG.
Отвечай строго JSON:
{
  "result_text": "что произошло",
  "effects": {
    "hp": -10,
    "strength": 0,
    "dexterity":0,
    "intelligence":0,
    "constitution":0,
    "charisma":0,
    "gold": 5,
    "add_item": "название предмета или null",
    "remove_item": "название предмета или null"
  }
}
"""
        user_prompt = f"""
Герой:
HP: {hero['hp']}
Stats: {hero['stats']}
Inventory: {hero['inventory']}
Выбранное действие: {choice['text']}
Определи последствия.
"""
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role":"system", "content": system_prompt},
                {"role":"user", "content": user_prompt}
            ],
            temperature=0.8,
            max_tokens=300
        )
        result = safe_json_parse(resp.choices[0].message.content)
        if not result:
            st.error("Ошибка генерации последствий")
            st.stop()
        # Применение эффектов
        effects = result["effects"]
        hero["hp"] = clamp(hero["hp"] + effects.get("hp",0), 0, 100)
        for stat in ["strength","dexterity","intelligence","constitution","charisma"]:
            hero["stats"][stat] = clamp(hero["stats"][stat] + effects.get(stat,0),1,20)
        if effects.get("add_item"):
            hero["inventory"].append(effects["add_item"])
        if effects.get("remove_item") and effects["remove_item"] in hero["inventory"]:
            hero["inventory"].remove(effects["remove_item"])
        hero["turn_count"] += 1
        hero.setdefault("history", []).append({
            "event": event["event_text"],
            "choice": choice["text"],
            "result": result["result_text"]
        })
        # Проверка смерти
        if hero["hp"] <= 0:
            hero["is_alive"] = False
            hero["epitaph"] = f"{hero['name']} прожил {hero['turn_count']} ходов. {result['result_text']}"
        save_hero(hero)
        st.session_state.current_event = None
        st.experimental_rerun()

# ----------------------------
# ПОКАЗ ИСТОРИИ
# ----------------------------
st.write("### 📖 Последние события")
for h in hero.get("history", [])[-5:]:
    st.write(f"- {h['choice']}: {h['result']}")