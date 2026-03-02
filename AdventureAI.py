import os
import json
import streamlit as st
from openai import OpenAI

# ----------------------------
# НАСТРОЙКИ
# ----------------------------

# Убедись, что ключ задан:
# export OPENAI_API_KEY="..."
client = OpenAI()

MODEL = "gpt-4o-mini"  # можно поменять

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

def clamp(value: int, min_v: int, max_v: int) -> int:
    return max(min_v, min(value, max_v))


def safe_json_parse(text: str):
    """
    Иногда модель может вернуть JSON в ``` ``` или с пробелами.
    Пытаемся аккуратно извлечь первый JSON-объект.
    """
    if not text:
        return None

    t = text.strip()

    # Убираем возможные code fences
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()

    # Пробуем как есть
    try:
        return json.loads(t)
    except Exception:
        pass

    # Пытаемся найти первый {...}
    m = re.search(r"\{.*\}", t, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None

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
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": user_prompt.strip()},
        ],
        temperature=0.9,
    )

    data = safe_json_parse(response.choices[0].message.content)

    if not data or "event_text" not in data or "choices" not in data:
        return None

    # Небольшая валидация choices
    choices = []
    for c in data.get("choices", []):
        if isinstance(c, dict) and c.get("id") and c.get("text"):
            choices.append({"id": str(c["id"])[:40], "text": str(c["text"])})
    if len(choices) < 2:
        return None

    data["choices"] = choices[:4]
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
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": user_prompt.strip()},
        ],
        temperature=0.8,
    )

    data = safe_json_parse(response.choices[0].message.content)

    if not data or "effects" not in data or "result_text" not in data:
        return None

    return data


# ----------------------------
# ПРИМЕНЕНИЕ ЭФФЕКТОВ
# ----------------------------

def apply_effects(data):
    hero = st.session_state.hero
    effects = data.get("effects", {}) if isinstance(data, dict) else {}

    # Дефолты, чтобы не падать от KeyError
    dhp = int(effects.get("hp", 0) or 0)
    dstr = int(effects.get("strength", 0) or 0)
    dcha = int(effects.get("charisma", 0) or 0)
    dgold = int(effects.get("gold", 0) or 0)
    add_item = effects.get("add_item", None)
    remove_item = effects.get("remove_item", None)

    hero["hp"] = clamp(hero["hp"] + dhp, 0, 100)
    hero["strength"] = clamp(hero["strength"] + dstr, 1, 20)
    hero["charisma"] = clamp(hero["charisma"] + dcha, 1, 20)
    hero["gold"] = clamp(hero["gold"] + dgold, 0, 999)

    if add_item:
        hero["inventory"].append(str(add_item))

    if remove_item:
        ri = str(remove_item)
        if ri in hero["inventory"]:
            hero["inventory"].remove(ri)

    # ЛОГ В ИСТОРИЮ (исправлена ошибка отступов и переменной data)
    current = st.session_state.get("current_event")
    if current and isinstance(current, dict) and current.get("event_text"):
        st.session_state.history.append({
            "event": current.get("event_text"),
            "result": data.get("result_text", "")
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
        st.rerun()
    st.stop()

# Генерация события
if not st.session_state.current_event:
    with st.spinner("Генерируем событие..."):
        event = generate_event()
        st.session_state.current_event = event

event = st.session_state.current_event

if not event:
    st.error("Ошибка генерации события (модель вернула невалидный JSON). Попробуй обновить страницу.")
    st.stop()

st.write("### 📜 Событие")
st.write(event.get("event_text", ""))

st.write("### ⚔️ Выбери действие")

# Чтобы ключи кнопок были уникальны даже при повторяющихся id от модели
event_key_prefix = str(len(st.session_state.history))

for i, choice in enumerate(event.get("choices", [])):
    btn_key = f"{event_key_prefix}:{choice.get('id','')[:40]}:{i}"
    if st.button(choice.get("text", "???"), key=btn_key):
        with st.spinner("Рассчитываем последствия..."):
            result = generate_consequences(choice.get("id", ""), choice.get("text", ""))

        if not result:
            st.error("Ошибка генерации последствий (модель вернула невалидный JSON).")
            st.stop()

        apply_effects(result)

        st.success(result.get("result_text", ""))
        st.session_state.current_event = None
        st.rerun()

# История (опционально)
if st.session_state.history:
    with st.expander("📚 История (последние 10)"):
        for h in st.session_state.history[-10:][::-1]:
            st.markdown(f"**Событие:** {h.get('event','')}")
            st.markdown(f"**Итог:** {h.get('result','')}")
            st.markdown("---")
