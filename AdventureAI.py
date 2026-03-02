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
# UTILS
# ===================================

def clamp(v, min_v, max_v):
    return max(min_v, min(v, max_v))

def d20():
    return random.randint(1, 20)

def safe_json_parse(text):
    try:
        return json.loads(text)
    except:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except:
                return None
    return None

def hero_path(hero_id):
    return os.path.join(SAVE_DIR, f"{hero_id}.json")

def save(hero):
    with open(hero_path(hero["hero_id"]), "w", encoding="utf-8") as f:
        json.dump(hero, f, ensure_ascii=False, indent=2)

def load(hero_id):
    try:
        with open(hero_path(hero_id), "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return None

def load_all():
    heroes = []
    for f in os.listdir(SAVE_DIR):
        if f.endswith(".json"):
            try:
                with open(os.path.join(SAVE_DIR, f), "r", encoding="utf-8") as file:
                    heroes.append(json.load(file))
            except:
                pass
    return heroes

# ===================================
# HERO DEFAULTS
# ===================================

def migrate(hero):
    defaults = {
        "history": [],
        "current_scene": None,
        "turn": 0,
        "is_alive": True,
        "wounds": 0,
        "inventory": ["Зелье лечения"],
        "max_hp": hero.get("hp", 100)
    }
    for k, v in defaults.items():
        hero.setdefault(k, v)
    return hero

# ===================================
# GPT SCENE
# ===================================

def generate_scene(hero, previous_choice=None):

    system = """
Ты мастер подземелий.
Строго JSON.
Никаких эффектов hp.
Формат:
{
 "scene_text": "...",
 "scene_type": "safe" | "danger" | "combat",
 "enemy": {"name": "...", "threat": 1-3} или null,
 "choices": [{"id":1,"text":"..."}]
}
Бои редкие.
"""

    user = f"""
Имя: {hero['name']}
Класс: {hero['class']}
HP: {hero['hp']}
Раны: {hero['wounds']}
История: {hero['history'][-5:]}
Предыдущий выбор: {previous_choice}
"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role":"system","content":system},
                      {"role":"user","content":user}],
            temperature=0.7,
            max_tokens=800
        )

        parsed = safe_json_parse(response.choices[0].message.content)
        if not parsed:
            return None
        return parsed
    except:
        return None

# ===================================
# COMBAT SYSTEM (D20)
# ===================================

def get_modifier(hero):
    stats = hero["stats"]
    if hero["class"] == "Воин":
        return stats["strength"] // 2
    if hero["class"] == "Маг":
        return stats["intelligence"] // 2
    return stats["dexterity"] // 2

def resolve_combat(hero, enemy):

    log = []
    threat = enemy["threat"]

    attack_roll = d20() + get_modifier(hero)
    difficulty = 10 + threat * 2

    log.append(f"Бросок атаки: {attack_roll} против {difficulty}")

    if attack_roll >= difficulty:
        damage = random.randint(5, 10) + threat
        max_allowed = int(hero["max_hp"] * 0.15)
        damage = min(damage, max_allowed)
        hero["hp"] -= damage
        log.append(f"Вы получили {damage} урона.")
    else:
        log.append("Вы увернулись и не получили урона.")

    # Проверка падения
    if hero["hp"] <= 0:
        hero["wounds"] += 1
        if hero["wounds"] >= 3:
            hero["is_alive"] = False
            hero["hp"] = 0
            log.append("Вы погибли.")
        else:
            hero["hp"] = int(hero["max_hp"] * 0.3)
            log.append("Вы получили тяжёлую рану, но выжили.")

    return hero, log

# ===================================
# STREAMLIT UI
# ===================================

st.title("Narrative RPG")

heroes = load_all()
alive = [h for h in heroes if h.get("is_alive", True)]

hero_map = {h["name"]: h["hero_id"] for h in alive}
options = list(hero_map.keys()) + ["➕ Новый герой"]

selected = st.selectbox("Выберите героя", options)

# CREATE HERO
if selected == "➕ Новый герой":

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

            max_hp = stats["constitution"] * 6 + 40

            hero = {
                "hero_id": str(uuid.uuid4()),
                "name": name,
                "class": hero_class,
                "stats": stats,
                "hp": max_hp,
                "max_hp": max_hp
            }

            hero = migrate(hero)
            save(hero)
            st.rerun()

    st.stop()

# LOAD HERO
if selected not in hero_map:
    st.stop()

hero = migrate(load(hero_map[selected]))

# SIDEBAR
st.sidebar.header(hero["name"])
st.sidebar.write(f"HP: {hero['hp']} / {hero['max_hp']}")
st.sidebar.write(f"Раны: {hero['wounds']} / 3")

# REST
if st.sidebar.button("🛏 Отдохнуть"):
    heal = int(hero["max_hp"] * 0.2)
    hero["hp"] = clamp(hero["hp"] + heal, 0, hero["max_hp"])
    save(hero)
    st.sidebar.success(f"Восстановлено {heal} HP")

# POTION
if "Зелье лечения" in hero["inventory"]:
    if st.sidebar.button("🧪 Выпить зелье"):
        heal = int(hero["max_hp"] * 0.3)
        hero["hp"] = clamp(hero["hp"] + heal, 0, hero["max_hp"])
        hero["inventory"].remove("Зелье лечения")
        save(hero)
        st.sidebar.success(f"Восстановлено {heal} HP")

# GENERATE SCENE
if hero["current_scene"] is None:
    hero["current_scene"] = generate_scene(hero)
    save(hero)

scene = hero["current_scene"]

if not scene:
    st.error("Ошибка сцены")
    st.stop()

st.markdown("### Сцена")
st.write(scene["scene_text"])

# COMBAT
if scene["scene_type"] == "combat" and scene.get("enemy"):
    hero, log = resolve_combat(hero, scene["enemy"])
    for line in log:
        st.write(line)
    save(hero)

    if not hero["is_alive"]:
        st.error("Герой погиб.")
        st.stop()

# CHOICES
for choice in scene["choices"]:
    if st.button(choice["text"]):
        hero["history"].append(choice["text"])
        hero["turn"] += 1
        hero["current_scene"] = generate_scene(hero, choice["text"])
        save(hero)
        st.rerun()