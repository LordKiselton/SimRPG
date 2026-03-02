import streamlit as st
import json
import random
from openai import OpenAI

client = OpenAI()

MODEL = "gpt-4o-mini"  # можешь поменять

# ----------------------------
# ИНИЦИАЛИЗАЦИЯ STATE
# ----------------------------

def init_game():
    st.session_state.hero = {
        "hp": 100,
        "strength": 5,
        "charisma": 5,
        "gold": 10,
        "inventory": []
    }
    st.session_state.history = []
    st.session_state.current_event = None
    st.session_state.game_over = False


if "hero" not in st.session_state:
    init_game()

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


def get_recent_history():
    return st.session_state.history[-5:]


# ----------------------------
# ЭТАП 1 — ГЕНЕРАЦИЯ СОБЫТИЯ
# ----------------------------

def generate_event():

    hero = st.session_state.hero
    history = get_recent_history()

    system_prompt = """
Ты генератор событий для текстовой фэнтези RPG.
Ты ОБЯЗАН отвечать строго JSON без лишнего текста.

Формат ответа:

{
  "event_text": "описание события",
  "choices": [
    {"id": "short_id", "text": "текст кнопки"},
    {"id": "short_id2", "text": "текст кнопки"}
  ]
}

Правила:
- 2–4 варианта
- варианты должны быть логичны
- никаких объяснений вне JSON
"""

    user_prompt = f"""
Герой:
HP: {hero['hp']}
Сила: {hero['strength']}
Харизма: {hero['charisma']}
Золото: {hero['gold']}
Инвентарь: {hero['inventory']}

Последние события:
{history}

Сгенерируй новое событие.
"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.9,
    )

    data = safe_json_parse(response.choices[0].message.content)

    if not data or "event_text" not in data:
        return None

    return data


# ----------------------------
# ЭТАП 2 — ГЕНЕРАЦИЯ ПОСЛЕДСТВИЙ
# ----------------------------

def generate_consequences(choice_id, choice_text):

    hero = st.session_state.hero

    system_prompt = """
Ты рассчитываешь последствия действия в фэнтези RPG.
Отвечай строго JSON.

Формат:

{
  "result_text": "что произошло",
  "effects": {
    "hp": -10,
    "strength": 1,
    "charisma": 0,
    "gold": 5,
    "add_item": "название предмета или null",
    "remove_item": "название предмета или null"
  }
}

Правила:
- hp изменения в диапазоне -30 до +20
- strength / charisma от -1 до +1
- gold от -20 до +20
- если нет предмета — null
- никаких объяснений вне JSON
"""

    user_prompt = f"""
Герой:
HP: {hero['hp']}
Сила: {hero['strength']}
Харизма: {hero['charisma']}
Золото: {hero['gold']}
Инвентарь: {hero['inventory']}

Игрок выбрал действие:
ID: {choice_id}
Текст: {choice_text}

Определи последствия.
"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.8,
    )

    data = safe_json_parse(response.choices[0].message.content)

    if not data or "effects" not in data:
        return None

    return data


# ----------------------------
# ПРИМЕНЕНИЕ ЭФФЕКТОВ
# ----------------------------

def apply_effects(data):

    hero = st.session_state.hero
    effects = data["effects"]

    hero["hp"] = clamp(hero["hp"] + effects["hp"], 0, 100)
    hero["strength"] = clamp(hero["strength"] + effects["strength"], 1, 20)
    hero["charisma"] = clamp(hero["charisma"] + effects["charisma"], 1, 20)
    hero["gold"] = clamp(hero["gold"] + effects["gold"], 0, 999)

    if effects["add_item"]:
        hero["inventory"].append(effects["add_item"])

    if effects["remove_item"] and effects["remove_item"] in hero["inventory"]:
        hero["inventory"].remove(effects["remove_item"])

st.session_state.history.append({
        "event": st.session_state.current_event["event_text"],
        "result": data["result_text"]
    })

    if hero["hp"] <= 0:
        st.session_state.game_over = True


# ----------------------------
# UI
# ----------------------------

st.title("🧙 AI Fantasy Roguelike MVP")

hero = st.session_state.hero

st.sidebar.header("Герой")
st.sidebar.write(f"❤️ HP: {hero['hp']}")
st.sidebar.write(f"💪 Сила: {hero['strength']}")
st.sidebar.write(f"🗣 Харизма: {hero['charisma']}")
st.sidebar.write(f"💰 Золото: {hero['gold']}")
st.sidebar.write(f"🎒 Инвентарь: {hero['inventory']}")

if st.session_state.game_over:
    st.error("☠️ Ты погиб. Игра окончена.")
    if st.button("Начать заново"):
        init_game()
    st.stop()

# Генерация события
if not st.session_state.current_event:
    with st.spinner("Генерируем событие..."):
        event = generate_event()
        st.session_state.current_event = event

event = st.session_state.current_event

if not event:
    st.error("Ошибка генерации события")
    st.stop()

st.write("### 📜 Событие")
st.write(event["event_text"])

st.write("### ⚔️ Выбери действие")

for choice in event["choices"]:
    if st.button(choice["text"], key=choice["id"]):
        with st.spinner("Рассчитываем последствия..."):
            result = generate_consequences(choice["id"], choice["text"])

        if not result:
            st.error("Ошибка генерации последствий")
            st.stop()

        apply_effects(result)

        st.success(result["result_text"])
        st.session_state.current_event = None
        st.rerun()
