import streamlit as st
import json
import os
import uuid
from datetime import datetime

# -----------------------------
# Настройки
# -----------------------------
MONSTER_DB_FILE = "monsters.json"
ENCOUNTER_DIR = "encounters"

CONDITIONS = [
    "Ослеплён","Очарован","Оглох","Испуган","Схвачен",
    "Недееспособен","Невидим","Парализован","Окаменел",
    "Отравлен","Сбит с ног","Скован","Оглушён",
    "Без сознания","Истощение"
]

HP_ADJUST = [-5, -1, +1, +5]  # кнопки изменения HP

# -----------------------------
# Инициализация сессии
# -----------------------------
def init_session():
    if "creatures" not in st.session_state:
        st.session_state.creatures=[]
    if "round" not in st.session_state:
        st.session_state.round=1
    if "turn" not in st.session_state:
        st.session_state.turn=0
    if "combat_started" not in st.session_state:
        st.session_state.combat_started=False
    if "selected_statblock" not in st.session_state:
        st.session_state.selected_statblock=None

# -----------------------------
# Загрузка / создание базы монстров
# -----------------------------
def create_sample_monsters():
    sample=[
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
            "bonus_actions":[],"reactions":[],"legendary_actions":[],"lair_actions":[],"regional_effects":[],"spellcasting":""
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
            "bonus_actions":[],"reactions":[],"legendary_actions":[],"lair_actions":[],"regional_effects":[],"spellcasting":""
        }
    ]
    with open(MONSTER_DB_FILE,"w",encoding="utf-8") as f:
        json.dump(sample,f,ensure_ascii=False,indent=2)

def load_monsters():
    if not os.path.exists(MONSTER_DB_FILE):
        create_sample_monsters()
    with open(MONSTER_DB_FILE,"r",encoding="utf-8") as f:
        return json.load(f)

# -----------------------------
# Добавление существ
# -----------------------------
def add_player(name,ac,hp):
    if not name.strip():
        st.warning("Имя игрока не может быть пустым")
        return
    st.session_state.creatures.append({
        "id":str(uuid.uuid4()),
        "name":name,
        "type":"player",
        "initiative":0,
        "ac":ac,
        "hp":hp,
        "max_hp":hp,
        "conditions":[],
        "dead":False,
        "statblock":None
    })

def add_monsters(monster,count):
    for i in range(count):
        st.session_state.creatures.append({
            "id":str(uuid.uuid4()),
            "name":f"{monster['name_ru']} {i+1}",
            "type":"monster",
            "initiative":0,
            "ac":monster["ac"],
            "hp":monster["hp"],
            "max_hp":monster["hp"],
            "conditions":[],
            "dead":False,
            "statblock":monster
        })

# -----------------------------
# Combat
# -----------------------------
def start_combat():
    st.session_state.creatures.sort(key=lambda x: x["initiative"],reverse=True)
    st.session_state.turn=0
    st.session_state.round=1
    st.session_state.combat_started=True

def next_turn():
    if not st.session_state.creatures:
        return
    st.session_state.turn+=1
    if st.session_state.turn>=len(st.session_state.creatures):
        st.session_state.turn=0
        st.session_state.round+=1

# -----------------------------
# HP управление
# -----------------------------
def change_hp(creature,value):
    try:
        creature["hp"]+=value
    except:
        return
    if creature["hp"]>creature["max_hp"]:
        creature["hp"]=creature["max_hp"]
    if creature["hp"]<=0:
        creature["hp"]=0
        if creature["type"]=="monster":
            creature["dead"]=True

# -----------------------------
# Statblock Sidebar
# -----------------------------
def show_statblock():
    sb=st.session_state.selected_statblock
    if not sb:
        return
    md=""
    md+=f"### {sb['name_ru']}\n"
    md+=f"**AC**: {sb['ac']}  \n"
    md+=f"**HP**: {sb['hp']}  \n"
    md+=f"**Speed**: {sb['speed']}  \n"
    md+=f"**CR**: {sb['cr']}  \n\n"
    md+="**Stats**  \n"
    stats_line=" | ".join([f"{k.upper()} {v}" for k,v in sb["stats"].items()])
    md+=stats_line+"\n\n"
    if sb.get("traits"):
        md+="**Traits**  \n"
        for t in sb["traits"]:
            md+="- "+t+"  \n"
    if sb.get("actions"):
        md+="**Actions**  \n"
        for a in sb["actions"]:
            md+="- "+a+"  \n"
    if sb.get("bonus_actions"):
        md+="**Bonus Actions**  \n"
        for a in sb["bonus_actions"]:
            md+="- "+a+"  \n"
    if sb.get("reactions"):
        md+="**Reactions**  \n"
        for a in sb["reactions"]:
            md+="- "+a+"  \n"
    if sb.get("legendary_actions"):
        md+="**Legendary Actions**  \n"
        for a in sb["legendary_actions"]:
            md+="- "+a+"  \n"
    if sb.get("spellcasting"):
        md+="**Spellcasting**  \n"+sb["spellcasting"]+"  \n"
    st.sidebar.markdown(md)

# -----------------------------
# Save / Load
# -----------------------------
def ensure_dirs():
    if not os.path.exists(ENCOUNTER_DIR):
        os.makedirs(ENCOUNTER_DIR)

def save_encounter():
    ensure_dirs()
    name=datetime.now().strftime("battle_%Y%m%d_%H%M%S.json")
    data={"creatures":st.session_state.creatures,"round":st.session_state.round,"turn":st.session_state.turn}
    path=os.path.join(ENCOUNTER_DIR,name)
    with open(path,"w",encoding="utf-8") as f:
        json.dump(data,f,ensure_ascii=False,indent=2)

def load_encounter(file):
    with open(file,"r",encoding="utf-8") as f:
        data=json.load(f)
    st.session_state.creatures=data["creatures"]
    st.session_state.round=data["round"]
    st.session_state.turn=data["turn"]
    st.session_state.combat_started=True

# -----------------------------
# MAIN UI
# -----------------------------
def main():
    st.title("DM Assistant - Compact Battle Table")
    init_session()
    monsters=load_monsters()
    show_statblock()

    col1,col2=st.columns(2)
    with col1:
        st.subheader("Add Player")
        name=st.text_input("Name")
        ac=st.number_input("AC",0,30,10)
        hp=st.number_input("HP",1,300,10)
        if st.button("Add Player"):
            add_player(name,ac,hp)
    with col2:
        st.subheader("Add Monster")
        names=[m["name_ru"] for m in monsters]
        choice=st.selectbox("Monster",names)
        count=st.number_input("Count",1,20,1)
        if st.button("Add Monster"):
            m=next(x for x in monsters if x["name_ru"]==choice)
            add_monsters(m,int(count))

    st.divider()

    if not st.session_state.combat_started:
        if st.button("START COMBAT"):
            start_combat()
    else:
        st.write(f"**Round:** {st.session_state.round}")
        if st.button("Next Turn"):
            next_turn()

    st.divider()
    # -------- Battle Table --------
    for i,c in enumerate(st.session_state.creatures):
        bg_color = "#d3f9d8" if i==st.session_state.turn else None
        col_name,col_init,col_ac,col_hp,col_cond,col_info=st.columns([3,1,1,3,3,1])
        if bg_color:
            col_name.markdown(f"<div style='background-color:{bg_color}'>{c['name']}</div>",unsafe_allow_html=True)
        else:
            col_name.write(c["name"])
        c["initiative"]=col_init.number_input("",value=c["initiative"],key=f"init{i}",label_visibility="collapsed")
        col_ac.write(f"{c['ac']}")
        # HP кнопки
        hp_col1,hp_col2,hp_col3,hp_col4,hp_display=col_hp.columns([1,1,1,1,2])
        for j,val in enumerate(HP_ADJUST):
            if hp_col1.button(f"{val}",key=f"hpbtn{i}_{j}"):
                change_hp(c,val)
        hp_display.write(f"{c['hp']} / {c['max_hp']}")
        # Conditions
        c["conditions"]=col_cond.multiselect("",CONDITIONS,default=c["conditions"],key=f"cond{i}",label_visibility="collapsed")
        # Info
        if col_info.button("Info",key=f"info{i}"):
            if c["statblock"]:
                st.session_state.selected_statblock=c["statblock"]

    st.divider()
    # Save / Load
    st.subheader("Save / Load Encounter")
    if st.button("Save Encounter"):
        save_encounter()
    ensure_dirs()
    files=os.listdir(ENCOUNTER_DIR)
    for f in files:
        if st.button(f"Load {f}"):
            load_encounter(os.path.join(ENCOUNTER_DIR,f))

if __name__=="__main__":
    main()
