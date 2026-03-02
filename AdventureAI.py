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

# OpenAI client (expects OPENAI_API_KEY in env)
client = OpenAI()

SAVE_DIR = "saves"
os.makedirs(SAVE_DIR, exist_ok=True)

# ==============================
# UTILS
# ==============================

def clamp(value, min_v, max_v):
    return max(min_v, min(value, max_v))

def safe_json_parse(text: str):
    """
    Robust JSON parser:
    - strips code fences ```json ... ```
    - tries plain json.loads
    """
    try:
        if not isinstance(text, str):
            return None
        t = text.strip()

        # Remove markdown code fences if present
        if t.startswith("```"):
            # common formats: ```json\n{...}\n``` or ```\n{...}\n```
            parts = t.split("```")
            # parts could be ["", "json\n{...}\n", ""]
            if len(parts) >= 2:
                t = parts[1].strip()
                if t.lower().startswith("json"):
                    t = t[4:].strip()

        return json.loads(t)
    except Exception:
        return None

def hero_max_hp(hero: dict) -> int:
    # Simple rule: max HP scales with constitution
    return int(hero["stats"]["constitution"] * 5)

def save_hero(hero: dict):
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
                "turn_count": 0,
                "epitaph": ""
            }

            save_hero(hero)
            st.session_state.hero = hero
            st.session_state.current_event = None
            st.session_state.last_result_text = None
            st.rerun()

else:
    # If no alive heroes exist except "create"
    if len(alive_heroes) == 0:
        st.info("Пока нет живых героев. Создайте нового героя.")
        st.stop()

    # Switch hero if needed
    if st.session_state.hero is None or st.session_state.hero.get("name") != selected:
        hero = next(h for h in alive_heroes if h["name"] == selected)
        st.session_state.hero = hero
        # Reset event/result when switching hero
        st.session_state.current_event = None
        st.session_state.last_result_text = None

hero = st.session_state.hero
if hero is None:
    st.stop()

# Ensure max hp consistency (optional normalization)
max_hp = hero_max_hp(hero)
hero["hp"] = clamp(int(hero.get("hp", max_hp)), 0, max_hp)

# ==============================
# SIDEBAR
# ==============================

st.sidebar.header(hero["name"])
st.sidebar.write(f"Класс: {hero['class']}")
st.sidebar.write(f"HP: {hero['hp']} / {max_hp}")
st.sidebar.write(f"Локация: {hero['location']}")

st.sidebar.subheader("Характеристики")
for stat, value in hero["stats"].items():
    st.sidebar.write(f"{stat.capitalize()}: {value}")

st.sidebar.subheader("Инвентарь")
st.sidebar.write(hero["inventory"] if hero["inventory"] else "Пусто")

# ==============================
# DEATH CHECK
# ==============================

if not hero.get("is_alive", True):
    st.error(f"{hero['name']} погиб после {hero.get('turn_count', 0)} ходов.")
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
""".strip()

    last_events = hero.get("history", [])[-3:]
    user_prompt = f"""
Герой: {hero['name']}
Класс: {hero['class']}
HP: {hero['hp']} / {hero_max_hp(hero)}
Характеристики: {hero['stats']}
Инвентарь: {hero['inventory']}

Текущая локация: {hero['location']}
Известные NPC: {hero['known_npcs']}
Активные сюжетные линии: {hero['active_threads']}

Последние события (3 последних):
{last_events}

Продолжи историю логично.
""".strip()

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.8,
            max_tokens=500
        )
    except Exception as e:
        st.error("Ошибка вызова OpenAI API. Проверь OPENAI_API_KEY и сеть.")
        st.exception(e)
        st.stop()

    event_data = safe_json_parse(response.choices[0].message.content)

    if not event_data or "event_text" not in event_data or "choices" not in event_data:
        st.error("Ошибка генерации события: модель вернула невалидный JSON.")
        st.write("Сырой ответ модели:")
        st.code(response.choices[0].message.content)
        st.stop()

    # Basic validation: ensure 2-3 choices, and ids are unique strings
    choices = event_data.get("choices", [])
    if not isinstance(choices, list) or len(choices) < 2:
        st.error("Ошибка генерации события: недостаточно вариантов выбора.")
        st.write(event_data)
        st.stop()

    # normalize choice ids if needed
    seen = set()
    for i, ch in enumerate(choices):
        if not isinstance(ch, dict):
            continue
        cid = str(ch.get("id", chr(ord("a") + i)))
        if cid in seen:
            cid = f"{cid}_{i}"
        seen.add(cid)
        ch["id"] = cid
        ch["text"] = str(ch.get("text", f"Вариант {i+1}"))

    st.session_state.current_event = event_data

event = st.session_state.current_event

st.markdown("### Событие")
st.write(event["event_text"])

st.markdown("### Выберите действие")

# ==============================
# HANDLE CHOICE
# ==============================

for choice in event["choices"]:
    if st.button(choice["text"], key=f"choice_{hero['hero_id']}_{choice['id']}"):
        consequence_prompt = """
Ты рассчитываешь последствия действия в фэнтези RPG.

Требования:
- Последствия должны быть логичными и опираться на ситуацию.
- Можно добавлять/убирать предметы, вводить NPC или сюжетную ветку, менять локацию.
- HP может уменьшаться или увеличиваться, но избегай абсурда.
- Статы меняй редко и небольшими шагами.

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
""".strip()

        consequence_user = f"""
Герой: {hero['name']}
Класс: {hero['class']}
Локация: {hero['location']}
Текущее событие: {event['event_text']}
Выбор игрока: {choice['text']}

Определи логичные последствия.
""".strip()

        try:
            result_response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": consequence_prompt},
                    {"role": "user", "content": consequence_user}
                ],
                temperature=0.8,
                max_tokens=400
            )
        except Exception as e:
            st.error("Ошибка вызова OpenAI API при расчёте последствий.")
            st.exception(e)
            st.stop()

        result_data = safe_json_parse(result_response.choices[0].message.content)

        if not result_data or "result_text" not in result_data or "effects" not in result_data:
            st.error("Ошибка генерации последствий: модель вернула невалидный JSON.")
            st.write("Сырой ответ модели:")
            st.code(result_response.choices[0].message.content)
            st.stop()

        effects = result_data.get("effects", {})
        if not isinstance(effects, dict):
            st.error("Ошибка: поле effects должно быть объектом.")
            st.write(result_data)
            st.stop()

        # Apply effects
        # 1) Stats first (so max_hp is correct if constitution changes)
        for stat in hero["stats"]:
            hero["stats"][stat] = clamp(
                int(hero["stats"][stat]) + int(effects.get(stat, 0) or 0),
                1,
                20
            )

        # 2) HP with dynamic max based on constitution
        max_hp = hero_max_hp(hero)
        hero["hp"] = clamp(int(hero["hp"]) + int(effects.get("hp", 0) or 0), 0, max_hp)

        # Inventory
        add_item = effects.get("add_item")
        if add_item:
            hero["inventory"].append(add_item)

        remove_item = effects.get("remove_item")
        if remove_item and remove_item in hero["inventory"]:
            hero["inventory"].remove(remove_item)

        # World state updates (avoid duplicates)
        new_location = effects.get("new_location")
        if new_location:
            hero["location"] = new_location

        new_npc = effects.get("new_npc")
        if new_npc and new_npc not in hero["known_npcs"]:
            hero["known_npcs"].append(new_npc)

        new_thread = effects.get("new_thread")
        if new_thread and new_thread not in hero["active_threads"]:
            hero["active_threads"].append(new_thread)

        hero["turn_count"] = int(hero.get("turn_count", 0)) + 1

        hero.setdefault("history", [])
        hero["history"].append({
            "event": event["event_text"],
            "choice": choice["text"],
            "result": result_data["result_text"]
        })

        # Death handling
        if hero["hp"] <= 0:
            hero["is_alive"] = False
            hero["epitaph"] = result_data.get("result_text", "Герой погиб.")

        # Persist + move to next turn
        st.session_state.last_result_text = result_data["result_text"]
        st.session_state.hero = hero

        save_hero(hero)

        # Important: clear current event so next one is generated
        st.session_state.current_event = None

        st.rerun()
