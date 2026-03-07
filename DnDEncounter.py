import streamlit as st
import json
import os
import random
from datetime import datetime

MONSTER_DB_FILE = "monsters.json"
ENCOUNTER_DIR = "encounters"

CONDITIONS = [
    "Ослеплён","Очарован","Оглох","Испуган","Схвачен",
    "Недееспособен","Невидим","Парализован","Окаменел",
    "Отравлен","Сбит с ног","Скован","Оглушён",
    "Без сознания","Истощение"
]

# -------------------------
# Utility
# -------------------------

def roll_dice(sides):
    return random.randint(1, sides)

def ensure_dirs():
    if not os.path.exists(ENCOUNTER_DIR):
        os.makedirs(ENCOUNTER_DIR)

# -------------------------
# Monster DB
# -------------------------

def load_monsters():
    if not os.path.exists(MONSTER_DB_FILE):
        create_sample_monsters()

    with open(MONSTER_DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def create_sample_monsters():
    sample = [
        {
            "name_ru": "Гоблин",
            "name_en": "Goblin",
            "ac": 15,
            "hp": 7,
            "max_hp": 7,
            "cr": "1/4",
            "speed": "30 ft",
            "stats": {
                "str":8,"dex":14,"con":10,"int":10,"wis":8,"cha":8
            },
            "traits":[
                "Проворство гоблина: может выйти из боя бонусным действием."
            ],
            "actions":[
                "Ятаган: +4 к попаданию, 1d6+2 рубящий."
            ],
            "bonus_actions":[],
            "reactions":[],
            "legendary_actions":[],
            "spellcasting":""
        },
        {
            "name_ru": "Орк",
            "name_en": "Orc",
            "ac": 13,
            "hp": 15,
            "max_hp": 15,
            "cr": "1/2",
            "speed": "30 ft",
            "stats":{
                "str":16,"dex":12,"con":16,"int":7,"wis":11,"cha":10
            },
            "traits":[
                "Агрессивность: бонусным действием перемещается к врагу."
            ],
            "actions":[
                "Топор: +5 к попаданию, 1d12+3 рубящий."
            ],
            "bonus_actions":[],
            "reactions":[],
            "legendary_actions":[],
            "spellcasting":""
        }
    ]

    with open(MONSTER_DB_FILE,"w",encoding="utf-8") as f:
        json.dump(sample,f,ensure_ascii=False,indent=2)

# -------------------------
# Session State
# -------------------------

def init_session():
    if "creatures" not in st.session_state:
        st.session_state.creatures = []

    if "round" not in st.session_state:
        st.session_state.round = 1

    if "turn" not in st.session_state:
        st.session_state.turn = 0

    if "combat_started" not in st.session_state:
        st.session_state.combat_started = False

# -------------------------
# Creature creation
# -------------------------

def add_player(name, ac, hp, initiative):

    creature = {
        "id":random.random(),
        "name":name,
        "type":"player",
        "initiative":initiative,
        "ac":ac,
        "hp":hp,
        "max_hp":hp,
        "conditions":[],
        "dead":False,
        "death_success":0,
        "death_fail":0,
        "statblock":None
    }

    st.session_state.creatures.append(creature)

def add_monsters(monster,count,initiative):

    for i in range(count):

        c = {
            "id":random.random(),
            "name":f"{monster['name_ru']} {i+1}",
            "type":"monster",
            "initiative":initiative,
            "ac":monster["ac"],
            "hp":monster["hp"],
            "max_hp":monster["max_hp"],
            "conditions":[],
            "dead":False,
            "death_success":0,
            "death_fail":0,
            "statblock":monster
        }

        st.session_state.creatures.append(c)

# -------------------------
# Combat logic
# -------------------------

def start_combat():

    st.session_state.creatures.sort(
        key=lambda x: x["initiative"], reverse=True
    )

    st.session_state.turn = 0
    st.session_state.round = 1
    st.session_state.combat_started = True


def next_turn():

    st.session_state.turn += 1

    if st.session_state.turn >= len(st.session_state.creatures):
        st.session_state.turn = 0
        st.session_state.round += 1


# -------------------------
# Save / Load
# -------------------------

def save_encounter():

    ensure_dirs()

    name = datetime.now().strftime("battle_%Y%m%d_%H%M%S.json")

    data = {
        "creatures":st.session_state.creatures,
        "round":st.session_state.round,
        "turn":st.session_state.turn
    }

    path = os.path.join(ENCOUNTER_DIR,name)

    with open(path,"w",encoding="utf-8") as f:
        json.dump(data,f,ensure_ascii=False,indent=2)

def load_encounter(file):

    with open(file,"r",encoding="utf-8") as f:
        data = json.load(f)

    st.session_state.creatures = data["creatures"]
    st.session_state.round = data["round"]
    st.session_state.turn = data["turn"]
    st.session_state.combat_started = True

# -------------------------
# Sidebar
# -------------------------

def sidebar(monsters):

    st.sidebar.title("🎲 Dice Roller")

    for s in [20,12,10,8,6,4]:
        if st.sidebar.button(f"Roll d{s}"):
            st.sidebar.write("Result:", roll_dice(s))

    st.sidebar.divider()

    st.sidebar.title("📂 Load Encounter")

    ensure_dirs()

    files = os.listdir(ENCOUNTER_DIR)

    for f in files:

        if st.sidebar.button(f):
            load_encounter(os.path.join(ENCOUNTER_DIR,f))

# -------------------------
# Statblock
# -------------------------

def show_statblock(creature):

    sb = creature["statblock"]

    if not sb:
        return

    st.sidebar.title(creature["name"])

    st.sidebar.write("AC:", sb["ac"])
    st.sidebar.write("HP:", sb["hp"])
    st.sidebar.write("Speed:", sb["speed"])
    st.sidebar.write("CR:", sb["cr"])

    st.sidebar.subheader("Stats")

    for k,v in sb["stats"].items():
        st.sidebar.write(k.upper(),v)

    if sb["traits"]:
        st.sidebar.subheader("Traits")
        for t in sb["traits"]:
            st.sidebar.write("-",t)

    if sb["actions"]:
        st.sidebar.subheader("Actions")
        for a in sb["actions"]:
            st.sidebar.write("-",a)

# -------------------------
# UI
# -------------------------

def main():

    st.title("🐉 DM Assistant")

    init_session()

    monsters = load_monsters()

    sidebar(monsters)

    col1,col2 = st.columns(2)

    with col1:

        st.subheader("Add Player")

        name = st.text_input("Name")
        ac = st.number_input("AC",0,30,10)
        hp = st.number_input("HP",1,300,10)
        init = st.number_input("Initiative",-5,40,10)

        if st.button("Add Player"):
            add_player(name,ac,hp,init)

    with col2:

        st.subheader("Add Monster")

        names = [m["name_ru"] for m in monsters]

        choice = st.selectbox("Monster",names)

        count = st.number_input("Count",1,20,1)
        init = st.number_input("Monster Initiative",-5,40,10)

        if st.button("Add Monster"):

            m = next(x for x in monsters if x["name_ru"]==choice)

            add_monsters(m,count,init)

    st.divider()

    if not st.session_state.combat_started:

        if st.button("START COMBAT"):
            start_combat()

    else:

        st.write("Round:",st.session_state.round)

        if st.button("Next Turn"):
            next_turn()

    st.divider()

    for i,c in enumerate(st.session_state.creatures):

        col1,col2,col3,col4,col5 = st.columns([2,1,2,2,2])

        active = (i == st.session_state.turn)

        if active:
            col1.markdown(f"**➡ {c['name']}**")
        else:
            col1.write(c["name"])

        col2.write("Init:",c["initiative"])

        hp_change = col3.text_input(
            f"hp{i}",
            value=f"{c['hp']}/{c['max_hp']}"
        )

        if col4.button("Select",key=f"s{i}"):
            show_statblock(c)

        cond = col5.multiselect(
            "Conditions",
            CONDITIONS,
            default=c["conditions"],
            key=f"cond{i}"
        )

        c["conditions"] = cond

        if c["type"]=="player" and c["hp"]<=0:

            s1,s2 = st.columns(2)

            if s1.button("Success",key=f"succ{i}"):

                c["death_success"]+=1

                if c["death_success"]>=3:
                    c["hp"]=1

            if s2.button("Fail",key=f"fail{i}"):

                c["death_fail"]+=1

                if c["death_fail"]>=3:
                    c["dead"]=True

    st.divider()

    if st.button("SAVE ENCOUNTER"):
        save_encounter()


if __name__ == "__main__":
    main()
