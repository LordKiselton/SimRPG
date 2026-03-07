import streamlit as st
import json
import pandas as pd
import uuid

st.set_page_config(layout="wide")

# ---------- LOAD MONSTER DB ----------

@st.cache_data
def load_monsters():
    with open("DnD.json", "r", encoding="utf-8") as f:
        return json.load(f)

monster_db = load_monsters()

monster_names = [m["name"] for m in monster_db]


# ---------- SESSION STATE ----------

if "combatants" not in st.session_state:
    st.session_state.combatants = []

if "encounter_started" not in st.session_state:
    st.session_state.encounter_started = False

if "turn_index" not in st.session_state:
    st.session_state.turn_index = 0


# ---------- CONDITIONS ----------

conditions = [
"Ослеплён",
"Очарован",
"Оглушён",
"Испуган",
"Схвачен",
"Недееспособен",
"Невидим",
"Парализован",
"Окаменел",
"Отравлен",
"Сбит с ног",
"Опутан",
"Ошеломлён"
]


# ---------- FUNCTIONS ----------

def add_combatant(name, hp, ac, type_, monster_data=None):

    st.session_state.combatants.append({
        "id": str(uuid.uuid4()),
        "name": name,
        "hp": hp,
        "max_hp": hp,
        "ac": ac,
        "initiative": 0,
        "type": type_,
        "conditions": [],
        "alive": True,
        "monster_data": monster_data
    })


def sort_initiative():
    st.session_state.combatants = sorted(
        st.session_state.combatants,
        key=lambda x: x["initiative"],
        reverse=True
    )


def next_turn():
    st.session_state.turn_index += 1
    if st.session_state.turn_index >= len(st.session_state.combatants):
        st.session_state.turn_index = 0


# ---------- ENCOUNTER SETUP ----------

if not st.session_state.encounter_started:

    st.title("DnD Encounter Builder")

    col1, col2, col3 = st.columns(3)

    # HERO
    with col1:

        st.header("Герой")

        name = st.text_input("Имя героя")

        hp = st.number_input("HP", 1, 999, 10)

        ac = st.number_input("AC", 1, 30, 10)

        if st.button("Добавить героя"):
            add_combatant(name, hp, ac, "hero")

    # NPC
    with col2:

        st.header("NPC")

        name = st.text_input("Имя NPC")

        hp = st.number_input("HP NPC", 1, 999, 10)

        ac = st.number_input("AC NPC", 1, 30, 10)

        if st.button("Добавить NPC"):
            add_combatant(name, hp, ac, "npc")

    # MONSTER
    with col3:

        st.header("Монстр")

        monster_name = st.selectbox("Монстр", monster_names)

        monster = next(m for m in monster_db if m["name"] == monster_name)

        st.write("AC:", monster["Armor Class"])
        st.write("HP:", monster["Hit Points"])

        if st.button("Добавить монстра"):
            add_combatant(
                monster["name"],
                int(monster["Hit Points"].split()[0]),
                monster["Armor Class"],
                "monster",
                monster
            )

    st.divider()

    if st.session_state.combatants:

        st.subheader("Участники")

        df = pd.DataFrame(st.session_state.combatants)
        st.dataframe(df[["name","type","hp","ac"]])

        if st.button("Начать бой"):
            st.session_state.encounter_started = True
            st.rerun()


# ---------- COMBAT SCREEN ----------

else:

    st.title("⚔ Encounter")

    if st.button("End Encounter"):
        st.session_state.combatants = []
        st.session_state.turn_index = 0
        st.session_state.encounter_started = False
        st.rerun()

    if st.button("Sort Initiative"):
        sort_initiative()

    if st.button("Next Turn"):
        next_turn()

    st.divider()

    for i, c in enumerate(st.session_state.combatants):

        highlight = i == st.session_state.turn_index

        box = st.container(border=True)

        with box:

            if highlight:
                st.markdown(f"### ▶ {c['name']}")
            else:
                st.markdown(f"### {c['name']}")

            col1, col2, col3, col4 = st.columns(4)

            with col1:
                c["initiative"] = st.number_input(
                    "Init",
                    key=f"init_{c['id']}",
                    value=c["initiative"]
                )

            with col2:

                hp_change = st.number_input(
                    "HP change",
                    key=f"hp_{c['id']}",
                    value=0
                )

                if st.button("Apply", key=f"apply_{c['id']}"):

                    c["hp"] += hp_change

                    if c["hp"] <= 0:
                        c["alive"] = False
                        c["hp"] = 0

            with col3:

                c["conditions"] = st.multiselect(
                    "Conditions",
                    conditions,
                    default=c["conditions"],
                    key=f"cond_{c['id']}"
                )

            with col4:

                st.write("AC:", c["ac"])
                st.write("HP:", f"{c['hp']} / {c['max_hp']}")

                if not c["alive"]:
                    st.error("DEAD")

            # MONSTER STATBLOCK

            if c["type"] == "monster":

                with st.expander("Статблок"):

                    m = c["monster_data"]

                    st.write("AC:", m["Armor Class"])
                    st.write("HP:", m["Hit Points"])
                    st.write("Speed:", m["Speed"])

                    st.subheader("Traits")
                    st.write(m["Traits"])

                    st.subheader("Actions")
                    st.write(m["Actions"])

                    if m["Legendary Actions"]:
                        st.subheader("Legendary Actions")
                        st.write(m["Legendary Actions"])
