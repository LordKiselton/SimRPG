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


def init_session():

    if "creatures" not in st.session_state:
        st.session_state.creatures = []

    if "round" not in st.session_state:
        st.session_state.round = 1

    if "turn" not in st.session_state:
        st.session_state.turn = 0

    if "combat_started" not in st.session_state:
        st.session_state.combat_started = False

    if "selected_statblock" not in st.session_state:
        st.session_state.selected_statblock = None


def ensure_dirs():
    if not os.path.exists(ENCOUNTER_DIR):
        os.makedirs(ENCOUNTER_DIR)


def load_monsters():

    if not os.path.exists(MONSTER_DB_FILE):
        create_sample_monsters()

    with open(MONSTER_DB_FILE,"r",encoding="utf-8") as f:
        return json.load(f)


def create_sample_monsters():

    sample = [
        {
            "name_ru":"Гоблин",
            "name_en":"Goblin",
            "ac":15,
            "hp":7,
            "speed":"30 ft",
            "cr":"1/4",
            "stats":{"str":8,"dex":14,"con":10,"int":10,"wis":8,"cha":8},
            "traits":["Проворство гоблина"],
            "actions":["Ятаган: +4 к попаданию, 1d6+2 рубящий"],
        },
        {
            "name_ru":"Орк",
            "name_en":"Orc",
            "ac":13,
            "hp":15,
            "speed":"30 ft",
            "cr":"1/2",
            "stats":{"str":16,"dex":12,"con":16,"int":7,"wis":11,"cha":10},
            "traits":["Агрессивность"],
            "actions":["Топор: +5 к попаданию, 1d12+3 рубящий"],
        }
    ]

    with open(MONSTER_DB_FILE,"w",encoding="utf-8") as f:
        json.dump(sample,f,ensure_ascii=False,indent=2)


def add_player(name,ac,hp):

    creature = {
        "id":random.random(),
        "name":name,
        "type":"player",
        "initiative":0,
        "ac":ac,
        "hp":hp,
        "max_hp":hp,
        "conditions":[],
        "dead":False,
        "statblock":None
    }

    st.session_state.creatures.append(creature)


def add_monsters(monster,count):

    for i in range(count):

        creature = {
            "id":random.random(),
            "name":f"{monster['name_ru']} {i+1}",
            "type":"monster",
            "initiative":0,
            "ac":monster["ac"],
            "hp":monster["hp"],
            "max_hp":monster["hp"],
            "conditions":[],
            "dead":False,
            "statblock":monster
        }

        st.session_state.creatures.append(creature)


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


def show_statblock():

    sb = st.session_state.selected_statblock

    if not sb:
        return

    st.sidebar.title(sb["name_ru"])

    st.sidebar.write(f"AC: {sb['ac']}")
    st.sidebar.write(f"HP: {sb['hp']}")
    st.sidebar.write(f"Speed: {sb['speed']}")
    st.sidebar.write(f"CR: {sb['cr']}")

    st.sidebar.subheader("Stats")

    for k,v in sb["stats"].items():
        st.sidebar.write(f"{k.upper()} : {v}")

    if sb.get("traits"):
        st.sidebar.subheader("Traits")
        for t in sb["traits"]:
            st.sidebar.write("-",t)

    if sb.get("actions"):
        st.sidebar.subheader("Actions")
        for a in sb["actions"]:
            st.sidebar.write("-",a)


def main():

    st.title("DM Assistant")

    init_session()

    monsters = load_monsters()

    show_statblock()

    col1,col2 = st.columns(2)

    with col1:

        st.subheader("Add Player")

        name = st.text_input("Name")
        ac = st.number_input("AC",0,30,10)
        hp = st.number_input("HP",1,300,10)

        if st.button("Add Player"):
            add_player(name,ac,hp)

    with col2:

        st.subheader("Add Monster")

        names = [m["name_ru"] for m in monsters]

        choice = st.selectbox("Monster",names)

        count = st.number_input("Count",1,20,1)

        if st.button("Add Monster"):

            m = next(x for x in monsters if x["name_ru"]==choice)

            add_monsters(m,count)

    st.divider()

    if not st.session_state.combat_started:

        if st.button("START COMBAT"):
            start_combat()

    else:

        st.write(f"Round: {st.session_state.round}")

        if st.button("Next Turn"):
            next_turn()

    st.divider()

    for i,c in enumerate(st.session_state.creatures):

        col1,col2,col3,col4 = st.columns([3,2,2,3])

        active = (i == st.session_state.turn)

        if active:
            col1.markdown(f"➡ **{c['name']}**")
        else:
            col1.write(c["name"])

        c["initiative"] = col2.number_input(
            "Init",
            value=c["initiative"],
            key=f"init{i}"
        )

        col3.write(f"HP: {c['hp']} / {c['max_hp']}")

        if col4.button("Info",key=f"info{i}"):

            if c["statblock"]:
                st.session_state.selected_statblock = c["statblock"]

        c["conditions"] = st.multiselect(
            "Conditions",
            CONDITIONS,
            default=c["conditions"],
            key=f"cond{i}"
        )

    st.divider()

    if st.button("SAVE ENCOUNTER"):
        save_encounter()


if __name__ == "__main__":
    main()
