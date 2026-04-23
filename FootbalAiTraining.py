import math
from dataclasses import dataclass, asdict, replace
from typing import Dict, Tuple

import pandas as pd
import streamlit as st


st.set_page_config(page_title="Football AI Balance Sandbox", layout="wide")


# -----------------------------
# Helpers
# -----------------------------

def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def normalize_100(value: float) -> float:
    return clamp(value / 100.0, 0.0, 1.0)


def range_hint(value: float, good: Tuple[float, float], caution: Tuple[float, float]) -> Tuple[str, str]:
    if good[0] <= value <= good[1]:
        return "OK: в рабочем диапазоне", "#15803d"
    if caution[0] <= value <= caution[1]:
        return "Погранично", "#b45309"
    return "Рискованно / вероятен перекос", "#b91c1c"


@dataclass
class RoleProfile:
    finishing: float
    passing: float
    vision: float
    dribbling: float
    composure: float
    press_resist: float
    marking: float
    pace: float
    stamina: float
    aggression: float
    positioning: float


TERM_HELP: Dict[str, str] = {
    "Finishing": "Насколько хорошо игрок завершает момент ударом. Влияет на шанс превратить хороший шанс в гол.",
    "Passing": "Качество исполнения передачи. Влияет на точность и стабильность пасов, особенно под давлением.",
    "Vision": "Насколько хорошо игрок замечает варианты развития атаки. Помогает выбирать лучшие передачи и видеть открывания.",
    "Dribbling": "Насколько уверенно игрок ведёт мяч и обыгрывает 1-в-1.",
    "Composure": "Спокойствие под давлением. Важно в штрафной, при завершении и в сложных ситуациях.",
    "Press Resistance": "Способность не терять мяч под прессингом.",
    "Marking": "Качество опеки и контроля соперника без мяча.",
    "Pace": "Скорость. Влияет на рывки, контратаки, возврат в оборону и создание отрыва.",
    "Stamina": "Выносливость. Влияет на то, насколько игрок сохраняет интенсивность по ходу матча.",
    "Aggression": "Готовность активно вступать в борьбу, прессинговать, атаковать пространство без мяча.",
    "Positioning": "Насколько хорошо игрок занимает полезные позиции. Важно и в атаке, и в защите.",
    "Tempo": "Темп атак. Более высокий темп ведёт к более быстрым решениям и выше частоте событий.",
    "Directness": "Насколько вертикально играет команда. Чем выше значение, тем чаще выбираются более прямые решения вперёд.",
    "Width": "Ширина игры. Влияет на использование флангов и растяжение обороны.",
    "Pressing": "Интенсивность коллективного давления на соперника.",
    "Defensive Line": "Высота линии обороны. Чем выше, тем проще душить соперника, но больше риск за спина.",
    "Support Runs": "Насколько активно партнёры открываются и поддерживают игрока с мячом.",
    "Shot Bias": "Системная склонность ИИ выбирать удар чаще относительно других действий.",
    "Dribble Bias": "Системная склонность ИИ чаще идти в обыгрыш.",
    "Distance Penalty": "Насколько сильно система штрафует решения об ударе с дальней дистанции.",
    "Pressure Penalty": "Насколько сильно давление ухудшает решение и успех действия.",
    "Openness Reward": "Насколько сильно ИИ ценит открытого адресата для передачи.",
    "Risk Appetite": "Склонность выбирать рискованные, но потенциально более полезные решения.",
    "Role Specialty Impact": "Насколько сильно роль и профиль игрока влияют на выбор действия.",
    "Style Impact": "Насколько сильно стиль команды влияет на решения ИИ.",
    "Skill Impact": "Насколько сильно чистые статы влияют на итог действий.",
    "Average Shot Distance": "Средняя дистанция удара. Чем дальше, тем ниже качество шанса.",
    "Shot Angle Quality": "Качество угла для удара. Хороший угол повышает вероятность гола.",
    "Pressure": "Среднее давление соперника на мяч. Снижает качество решений и успешность.",
    "Pass Openness": "Насколько часто у пасующего есть реально открытый адресат.",
    "Pass Risk": "Насколько сложные передачи обычно выбирает система.",
    "Transition Frequency": "Как часто матч переходит в быстрые фазы и обмен атаками.",
}


GOOD_RANGES = {
    "goals": (1.8, 3.2),
    "shots": (16.0, 26.0),
    "conversion": (0.08, 0.18),
    "pass_success": (0.78, 0.90),
    "risk_share": (0.08, 0.24),
    "press_regain": (0.06, 0.18),
    "dribble_share": (0.08, 0.22),
    "forward_share": (0.28, 0.52),
}

CAUTION_RANGES = {
    "goals": (1.2, 3.8),
    "shots": (12.0, 30.0),
    "conversion": (0.05, 0.22),
    "pass_success": (0.72, 0.93),
    "risk_share": (0.04, 0.30),
    "press_regain": (0.03, 0.22),
    "dribble_share": (0.04, 0.28),
    "forward_share": (0.20, 0.60),
}


def base_roles() -> Dict[str, RoleProfile]:
    return {
        "ST": RoleProfile(84, 66, 64, 72, 80, 61, 35, 78, 73, 71, 86),
        "AM": RoleProfile(72, 81, 84, 79, 77, 72, 45, 74, 75, 58, 81),
        "CM": RoleProfile(66, 82, 79, 70, 74, 76, 64, 68, 82, 63, 75),
        "WG": RoleProfile(74, 72, 70, 84, 73, 68, 40, 86, 78, 61, 79),
        "FB": RoleProfile(52, 72, 66, 68, 69, 71, 72, 80, 84, 67, 71),
        "CB": RoleProfile(40, 61, 55, 48, 66, 64, 84, 68, 79, 74, 78),
    }


# Player overrides per preset: relative shifts (added to base stats, clamped to [20,99]).
PLAYER_PRESETS = {
    "Balanced": {},
    "Possession": {
        "ST": {"finishing": -3, "composure": +2},
        "AM": {"passing": +4, "vision": +4, "press_resist": +3},
        "CM": {"passing": +4, "vision": +3, "press_resist": +4},
        "WG": {"dribbling": +2, "passing": +3},
        "FB": {"passing": +3, "press_resist": +2},
        "CB": {"passing": +4, "press_resist": +3},
    },
    "Direct Vertical": {
        "ST": {"finishing": +5, "pace": +3, "positioning": +3},
        "AM": {"vision": +2},
        "CM": {"vision": +2, "stamina": +2},
        "WG": {"pace": +5, "dribbling": +3},
        "FB": {"pace": +4, "stamina": +2},
        "CB": {"pace": +3, "marking": +2},
    },
    "Pressing Chaos": {
        "ST": {"aggression": +6, "stamina": +4},
        "AM": {"aggression": +5, "stamina": +5, "press_resist": +3},
        "CM": {"aggression": +6, "stamina": +5},
        "WG": {"aggression": +5, "stamina": +4},
        "FB": {"aggression": +6, "stamina": +5, "marking": +3},
        "CB": {"aggression": +5, "marking": +3, "stamina": +3},
    },
}


def apply_player_preset(roles: Dict[str, RoleProfile], preset_name: str) -> Dict[str, RoleProfile]:
    deltas = PLAYER_PRESETS.get(preset_name, {})
    out = {}
    for role_name, profile in roles.items():
        shift = deltas.get(role_name, {})
        new_vals = asdict(profile)
        for k, d in shift.items():
            new_vals[k] = clamp(new_vals[k] + d, 20, 99)
        out[role_name] = RoleProfile(**new_vals)
    return out


# -----------------------------
# Sidebar
# -----------------------------
with st.sidebar:
    st.title("Football AI Balance Sandbox")
    st.caption("Учебный симулятор для начинающего balance / AI game designer.")

    preset = st.selectbox(
        "Стартовый пресет",
        ["Balanced", "Possession", "Direct Vertical", "Pressing Chaos"],
        help="Быстрый способ начать с разных игровых идентичностей. Теперь меняет и статы игроков.",
    )

    st.markdown("---")
    st.subheader("Как читать модель")
    st.markdown(
        """
- **Target** — желаемый результат.
- **Actual** — что сейчас даёт система.
- **Gap** — насколько ты не попал в цель.
- **Зелёный** — метрика в рабочей зоне.
- **Жёлтый** — на грани.
- **Красный** — вероятен перекос или нереалистичность.
        """
    )


if preset == "Balanced":
    team_defaults = dict(tempo=55, directness=50, width=54, pressing=56, defensive_line=52, support_runs=57, shot_bias=50, dribble_bias=48)
    ai_defaults = dict(distance_penalty=58, pressure_penalty=60, openness_reward=62, risk_appetite=48, role_specialty=62, style_impact=56, skill_impact=64)
    scenario_defaults = dict(avg_shot_distance=19.0, shot_angle_quality=58, pressure=56, pass_openness=61, pass_risk=42, transition_freq=52)
elif preset == "Possession":
    team_defaults = dict(tempo=48, directness=38, width=58, pressing=54, defensive_line=55, support_runs=63, shot_bias=44, dribble_bias=46)
    ai_defaults = dict(distance_penalty=62, pressure_penalty=58, openness_reward=70, risk_appetite=40, role_specialty=60, style_impact=62, skill_impact=64)
    scenario_defaults = dict(avg_shot_distance=17.0, shot_angle_quality=63, pressure=53, pass_openness=68, pass_risk=34, transition_freq=44)
elif preset == "Direct Vertical":
    team_defaults = dict(tempo=67, directness=72, width=50, pressing=58, defensive_line=50, support_runs=55, shot_bias=58, dribble_bias=47)
    ai_defaults = dict(distance_penalty=52, pressure_penalty=60, openness_reward=54, risk_appetite=62, role_specialty=61, style_impact=64, skill_impact=63)
    scenario_defaults = dict(avg_shot_distance=20.0, shot_angle_quality=54, pressure=58, pass_openness=55, pass_risk=54, transition_freq=64)
else:
    team_defaults = dict(tempo=71, directness=60, width=56, pressing=76, defensive_line=71, support_runs=58, shot_bias=54, dribble_bias=52)
    ai_defaults = dict(distance_penalty=49, pressure_penalty=67, openness_reward=58, risk_appetite=58, role_specialty=59, style_impact=68, skill_impact=61)
    scenario_defaults = dict(avg_shot_distance=21.0, shot_angle_quality=51, pressure=67, pass_openness=52, pass_risk=57, transition_freq=73)

roles = apply_player_preset(base_roles(), preset)


# -----------------------------
# Layout
# -----------------------------
st.title("Football AI Balance Sandbox")
st.write(
    "Меняй **статы игроков**, **командный стиль**, **веса принятия решений** и **контекст матча**, "
    "чтобы привести систему к целевым метрикам. Это тренажёр логики, а не реалистичная матч-симуляция."
)


target_col, output_col = st.columns([1, 1.25])

with target_col:
    st.subheader("1) Целевые метрики")
    t_goals = st.slider("Goals per match", 0.5, 5.0, 2.4, 0.1, help="Среднее число голов за матч. Один из главных итоговых outputs.")
    t_shots = st.slider("Shots per match", 6.0, 35.0, 21.0, 0.5, help="Среднее количество ударов за матч.")
    t_conv = st.slider("Shot conversion", 0.03, 0.35, 0.11, 0.01, help="Доля ударов, которые превращаются в голы.")
    t_pass = st.slider("Pass success", 0.60, 0.96, 0.84, 0.01, help="Доля успешных передач.")
    t_risk = st.slider("High-risk pass share", 0.00, 0.50, 0.18, 0.01, help="Доля рискованных передач от всех передач.")
    t_press = st.slider("Press regain rate", 0.00, 0.30, 0.09, 0.01, help="Как часто команда возвращает мяч за счёт прессинга.")
    t_dribble = st.slider("Dribble attempt share", 0.00, 0.40, 0.14, 0.01, help="Какую долю решений с мячом составляют попытки дриблинга.")
    t_forward = st.slider("Forward shot share", 0.00, 0.80, 0.42, 0.01, help="Какая доля ударов команды приходится на форварда.")

with output_col:
    st.subheader("2) Как работать со sandbox")
    st.info(
        "Сначала попробуй попасть в target только статами. Потом повтори то же самое, но трогай только decision weights. "
        "Так ты почувствуешь разницу между балансом качеств и балансом решений.",
        icon="🧠",
    )
    st.caption("Снапшоты текущей конфигурации с результатами сохраняются в «7) История попыток» ниже.")


# -----------------------------
# Player stats (collapsed by default) + team aggregates preview
# -----------------------------
with st.expander("Статы игроков (6 ролей × 11 параметров) — раскрой чтобы крутить", expanded=False):
    role_tabs = st.tabs(list(roles.keys()))
    for tab, role_name in zip(role_tabs, roles.keys()):
        role = roles[role_name]
        with tab:
            c1, c2, c3 = st.columns(3)
            with c1:
                role.finishing = st.slider(f"{role_name} Finishing", 20, 99, int(role.finishing), key=f"{role_name}_fin", help=TERM_HELP["Finishing"])
                role.passing = st.slider(f"{role_name} Passing", 20, 99, int(role.passing), key=f"{role_name}_pas", help=TERM_HELP["Passing"])
                role.vision = st.slider(f"{role_name} Vision", 20, 99, int(role.vision), key=f"{role_name}_vis", help=TERM_HELP["Vision"])
                role.dribbling = st.slider(f"{role_name} Dribbling", 20, 99, int(role.dribbling), key=f"{role_name}_dri", help=TERM_HELP["Dribbling"])
            with c2:
                role.composure = st.slider(f"{role_name} Composure", 20, 99, int(role.composure), key=f"{role_name}_com", help=TERM_HELP["Composure"])
                role.press_resist = st.slider(f"{role_name} Press Resistance", 20, 99, int(role.press_resist), key=f"{role_name}_pr", help=TERM_HELP["Press Resistance"])
                role.marking = st.slider(f"{role_name} Marking", 20, 99, int(role.marking), key=f"{role_name}_mar", help=TERM_HELP["Marking"])
                role.pace = st.slider(f"{role_name} Pace", 20, 99, int(role.pace), key=f"{role_name}_pac", help=TERM_HELP["Pace"])
            with c3:
                role.stamina = st.slider(f"{role_name} Stamina", 20, 99, int(role.stamina), key=f"{role_name}_sta", help=TERM_HELP["Stamina"])
                role.aggression = st.slider(f"{role_name} Aggression", 20, 99, int(role.aggression), key=f"{role_name}_agg", help=TERM_HELP["Aggression"])
                role.positioning = st.slider(f"{role_name} Positioning", 20, 99, int(role.positioning), key=f"{role_name}_pos", help=TERM_HELP["Positioning"])


left, middle, right = st.columns(3)
with left:
    st.subheader("3) Team tuning")
    tempo = st.slider("Tempo", 0, 100, team_defaults["tempo"], help=TERM_HELP["Tempo"])
    directness = st.slider("Directness", 0, 100, team_defaults["directness"], help=TERM_HELP["Directness"])
    width = st.slider("Width", 0, 100, team_defaults["width"], help=TERM_HELP["Width"])
    pressing = st.slider("Pressing", 0, 100, team_defaults["pressing"], help=TERM_HELP["Pressing"])
    defensive_line = st.slider("Defensive Line", 0, 100, team_defaults["defensive_line"], help=TERM_HELP["Defensive Line"])
    support_runs = st.slider("Support Runs", 0, 100, team_defaults["support_runs"], help=TERM_HELP["Support Runs"])
    shot_bias = st.slider("Shot Bias", 0, 100, team_defaults["shot_bias"], help=TERM_HELP["Shot Bias"])
    dribble_bias = st.slider("Dribble Bias", 0, 100, team_defaults["dribble_bias"], help=TERM_HELP["Dribble Bias"])

with middle:
    st.subheader("4) AI weights")
    distance_penalty = st.slider("Distance Penalty", 0, 100, ai_defaults["distance_penalty"], help=TERM_HELP["Distance Penalty"])
    pressure_penalty = st.slider("Pressure Penalty", 0, 100, ai_defaults["pressure_penalty"], help=TERM_HELP["Pressure Penalty"])
    openness_reward = st.slider("Openness Reward", 0, 100, ai_defaults["openness_reward"], help=TERM_HELP["Openness Reward"])
    risk_appetite = st.slider("Risk Appetite", 0, 100, ai_defaults["risk_appetite"], help=TERM_HELP["Risk Appetite"])
    role_specialty = st.slider("Role Specialty Impact", 0, 100, ai_defaults["role_specialty"], help=TERM_HELP["Role Specialty Impact"])
    style_impact = st.slider("Style Impact", 0, 100, ai_defaults["style_impact"], help=TERM_HELP["Style Impact"])
    skill_impact = st.slider("Skill Impact", 0, 100, ai_defaults["skill_impact"], help=TERM_HELP["Skill Impact"])

with right:
    st.subheader("5) Match context")
    avg_shot_distance = st.slider("Average Shot Distance", 8.0, 30.0, scenario_defaults["avg_shot_distance"], 0.5, help=TERM_HELP["Average Shot Distance"])
    shot_angle_quality = st.slider("Shot Angle Quality", 0, 100, scenario_defaults["shot_angle_quality"], help=TERM_HELP["Shot Angle Quality"])
    pressure = st.slider("Pressure", 0, 100, scenario_defaults["pressure"], help=TERM_HELP["Pressure"])
    pass_openness = st.slider("Pass Openness", 0, 100, scenario_defaults["pass_openness"], help=TERM_HELP["Pass Openness"])
    pass_risk = st.slider("Pass Risk", 0, 100, scenario_defaults["pass_risk"], help=TERM_HELP["Pass Risk"])
    transition_freq = st.slider("Transition Frequency", 0, 100, scenario_defaults["transition_freq"], help=TERM_HELP["Transition Frequency"])


# -----------------------------
# Aggregates
# -----------------------------
ST = roles["ST"]
AM = roles["AM"]
CM = roles["CM"]
WG = roles["WG"]
FB = roles["FB"]
CB = roles["CB"]

finishing_team = (ST.finishing * 0.34 + AM.finishing * 0.16 + WG.finishing * 0.22 + CM.finishing * 0.14 + FB.finishing * 0.08 + CB.finishing * 0.06)
passing_team = (ST.passing * 0.10 + AM.passing * 0.24 + WG.passing * 0.16 + CM.passing * 0.28 + FB.passing * 0.14 + CB.passing * 0.08)
vision_team = (ST.vision * 0.08 + AM.vision * 0.28 + WG.vision * 0.14 + CM.vision * 0.26 + FB.vision * 0.12 + CB.vision * 0.12)
dribbling_team = (ST.dribbling * 0.16 + AM.dribbling * 0.20 + WG.dribbling * 0.28 + CM.dribbling * 0.14 + FB.dribbling * 0.12 + CB.dribbling * 0.10)
composure_team = (ST.composure * 0.25 + AM.composure * 0.18 + WG.composure * 0.14 + CM.composure * 0.18 + FB.composure * 0.12 + CB.composure * 0.13)
press_resist_team = (ST.press_resist * 0.10 + AM.press_resist * 0.18 + WG.press_resist * 0.12 + CM.press_resist * 0.28 + FB.press_resist * 0.17 + CB.press_resist * 0.15)
marking_team = (ST.marking * 0.03 + AM.marking * 0.08 + WG.marking * 0.09 + CM.marking * 0.20 + FB.marking * 0.24 + CB.marking * 0.36)
pace_team = (ST.pace * 0.16 + AM.pace * 0.13 + WG.pace * 0.22 + CM.pace * 0.14 + FB.pace * 0.18 + CB.pace * 0.17)
stamina_team = (ST.stamina * 0.12 + AM.stamina * 0.14 + WG.stamina * 0.16 + CM.stamina * 0.22 + FB.stamina * 0.18 + CB.stamina * 0.18)
aggression_team = (ST.aggression * 0.08 + AM.aggression * 0.11 + WG.aggression * 0.10 + CM.aggression * 0.21 + FB.aggression * 0.20 + CB.aggression * 0.30)
positioning_team = (ST.positioning * 0.22 + AM.positioning * 0.18 + WG.positioning * 0.14 + CM.positioning * 0.18 + FB.positioning * 0.12 + CB.positioning * 0.16)

team_style = normalize_100((tempo + directness + width + pressing + defensive_line + support_runs + shot_bias + dribble_bias) / 8)
team_skill = normalize_100((finishing_team + passing_team + vision_team + dribbling_team + composure_team + press_resist_team + pace_team + stamina_team + aggression_team + positioning_team) / 10)


# -----------------------------
# Decision layer
# -----------------------------
shoot_intent = (
    0.28 * normalize_100(shot_bias)
    + 0.22 * normalize_100(ST.finishing)
    + 0.12 * normalize_100(ST.positioning)
    + 0.10 * normalize_100(style_impact)
    + 0.08 * normalize_100(skill_impact)
    + 0.07 * normalize_100(transition_freq)
    + 0.10 * normalize_100(shot_angle_quality)
    - 0.15 * normalize_100(distance_penalty) * normalize_100(avg_shot_distance * 3.0)
    - 0.12 * normalize_100(pressure_penalty) * normalize_100(pressure)
)

pass_intent = (
    0.20 * normalize_100(openness_reward)
    + 0.16 * normalize_100(pass_openness)
    + 0.16 * normalize_100(passing_team)
    + 0.14 * normalize_100(vision_team)
    + 0.08 * normalize_100(support_runs)
    + 0.10 * (1 - normalize_100(directness))
    + 0.06 * normalize_100(style_impact)
    - 0.12 * normalize_100(pass_risk) * (1 - normalize_100(risk_appetite))
)

pass_risk_share = clamp(
    0.06
    + 0.24 * normalize_100(directness)
    + 0.20 * normalize_100(risk_appetite)
    + 0.18 * normalize_100(pass_risk)
    - 0.12 * normalize_100(openness_reward),
    0.0,
    0.5,
)

dribble_share = clamp(
    0.04
    + 0.20 * normalize_100(dribble_bias)
    + 0.18 * normalize_100(dribbling_team)
    + 0.06 * normalize_100(WG.dribbling)
    + 0.05 * normalize_100(ST.dribbling)
    - 0.10 * normalize_100(pass_openness),
    0.0,
    0.4,
)

shots_per_match = clamp(
    8
    + 9.0 * normalize_100(tempo)
    + 5.0 * normalize_100(transition_freq)
    + 4.0 * clamp(shoot_intent, 0.0, 1.0)
    + 2.5 * normalize_100(directness)
    - 2.5 * normalize_100(distance_penalty),
    5.0,
    35.0,
)

shot_conversion = clamp(
    0.04
    + 0.08 * normalize_100(finishing_team)
    + 0.06 * normalize_100(composure_team)
    + 0.05 * normalize_100(shot_angle_quality)
    + 0.02 * normalize_100(positioning_team)
    - 0.06 * normalize_100(avg_shot_distance * 3.0)
    - 0.05 * normalize_100(pressure_penalty) * normalize_100(pressure)
    + 0.02 * normalize_100(skill_impact),
    0.02,
    0.35,
)

goals_per_match = clamp(shots_per_match * shot_conversion, 0.4, 5.0)

pass_success = clamp(
    0.62
    + 0.10 * normalize_100(passing_team)
    + 0.08 * normalize_100(vision_team)
    + 0.05 * normalize_100(press_resist_team)
    + 0.04 * normalize_100(pass_openness)
    - 0.07 * normalize_100(pass_risk)
    - 0.05 * normalize_100(pressure)
    + 0.02 * normalize_100(openness_reward),
    0.55,
    0.96,
)

press_regain = clamp(
    0.02
    + 0.08 * normalize_100(pressing)
    + 0.05 * normalize_100(defensive_line)
    + 0.05 * normalize_100(aggression_team)
    + 0.03 * normalize_100(stamina_team)
    - 0.02 * normalize_100(pass_openness),
    0.0,
    0.30,
)

forward_shot_share = clamp(
    0.18
    + 0.18 * normalize_100(ST.finishing)
    + 0.14 * normalize_100(ST.positioning)
    + 0.08 * normalize_100(role_specialty)
    + 0.06 * normalize_100(shot_bias)
    - 0.08 * normalize_100(WG.finishing)
    - 0.05 * normalize_100(AM.finishing),
    0.0,
    0.8,
)


# -----------------------------
# Team aggregates preview (above output cards)
# -----------------------------
st.markdown("---")
st.subheader("6) Итоговые метрики")

agg_df = pd.DataFrame({
    "Параметр": ["Finishing", "Passing", "Vision", "Dribbling", "Composure", "Press Resist", "Marking", "Pace", "Stamina", "Aggression", "Positioning"],
    "Team aggregate": [finishing_team, passing_team, vision_team, dribbling_team, composure_team, press_resist_team, marking_team, pace_team, stamina_team, aggression_team, positioning_team],
})
with st.expander("Team aggregates (как статы ролей сворачиваются в командные)", expanded=False):
    st.dataframe(agg_df.style.format({"Team aggregate": "{:.1f}"}), hide_index=True, use_container_width=True)


metrics = [
    ("Goals per match", goals_per_match, t_goals, 0.15, "goals", "{:.2f}"),
    ("Shots per match", shots_per_match, t_shots, 1.0, "shots", "{:.1f}"),
    ("Shot conversion", shot_conversion, t_conv, 0.015, "conversion", "{:.2f}"),
    ("Pass success", pass_success, t_pass, 0.015, "pass_success", "{:.2f}"),
    ("High-risk pass share", pass_risk_share, t_risk, 0.015, "risk_share", "{:.2f}"),
    ("Press regain rate", press_regain, t_press, 0.015, "press_regain", "{:.2f}"),
    ("Dribble attempt share", dribble_share, t_dribble, 0.015, "dribble_share", "{:.2f}"),
    ("Forward shot share", forward_shot_share, t_forward, 0.02, "forward_share", "{:.2f}"),
]

row1 = st.columns(4)
row2 = st.columns(4)
for idx, (name, actual, target, tol, key, fmt) in enumerate(metrics):
    hint, color = range_hint(actual, GOOD_RANGES[key], CAUTION_RANGES[key])
    card = (
        f"<div style='padding:12px;border-radius:14px;border:1px solid #e5e7eb;height:180px;'>"
        f"<div style='font-weight:700;font-size:16px;margin-bottom:8px;'>{name}</div>"
        f"<div style='font-size:28px;font-weight:800;margin-bottom:6px;'>{fmt.format(actual)}</div>"
        f"<div style='color:{color};font-weight:700;margin-bottom:8px;'>{hint}</div>"
        f"<div style='font-size:13px;color:#374151;'>Target: <b>{fmt.format(target)}</b></div>"
        f"<div style='font-size:13px;color:#374151;'>Gap: <b>{fmt.format(actual - target)}</b></div>"
        f"</div>"
    )
    if idx < 4:
        row1[idx].markdown(card, unsafe_allow_html=True)
    else:
        row2[idx - 4].markdown(card, unsafe_allow_html=True)


# -----------------------------
# Gap chart
# -----------------------------
st.markdown("#### Визуализация gap")
st.caption("Нормализованный |actual − target| / target. Чем выше столбик, тем дальше от цели. Красный = выше target, синий = ниже.")

gap_rows = []
for name, actual, target, _tol, _key, _fmt in metrics:
    rel_gap = (actual - target) / target if target != 0 else 0.0
    gap_rows.append({
        "Метрика": name,
        "Relative gap": rel_gap,
        "|Relative gap|": abs(rel_gap),
        "Направление": "выше target" if actual >= target else "ниже target",
    })
gap_df = pd.DataFrame(gap_rows).sort_values("|Relative gap|", ascending=False)

try:
    import altair as alt

    chart = (
        alt.Chart(gap_df)
        .mark_bar()
        .encode(
            x=alt.X("|Relative gap|:Q", axis=alt.Axis(format="%"), title="|actual − target| / target"),
            y=alt.Y("Метрика:N", sort="-x"),
            color=alt.Color(
                "Направление:N",
                scale=alt.Scale(domain=["выше target", "ниже target"], range=["#b91c1c", "#2563eb"]),
            ),
            tooltip=["Метрика", alt.Tooltip("Relative gap:Q", format=".1%"), "Направление"],
        )
        .properties(height=280)
    )
    st.altair_chart(chart, use_container_width=True)
except ImportError:
    st.bar_chart(gap_df.set_index("Метрика")["|Relative gap|"])


# -----------------------------
# Diagnostics (two-sided)
# -----------------------------
st.markdown("---")
st.subheader("7) Диагностика: что крутить")

advice = []

# Goals
if goals_per_match < t_goals - 0.15:
    if shot_conversion < t_conv:
        advice.append("**Не хватает реализации**: подними ST Finishing, ST Composure, Shot Angle Quality или ослабь Pressure Penalty / Pressure.")
    if shots_per_match < t_shots:
        advice.append("**Не хватает объёма атак**: подними Tempo, Shot Bias, Transition Frequency или снизь Distance Penalty.")
elif goals_per_match > t_goals + 0.15:
    advice.append("**Результативность выше target**: снизь ST Finishing/Composure, подними Pressure/Distance Penalty или снизь Tempo/Shot Bias.")

# Pass success
if pass_success < t_pass - 0.015:
    advice.append("**Передачи нестабильны**: подними Passing, Vision, Pass Openness или снизь Pass Risk / Pressure.")
elif pass_success > t_pass + 0.015:
    advice.append("**Пас слишком стерильный**: подними Pass Risk, Directness, Risk Appetite — команда играет в «безопасный» перекат.")

# Risk share
if pass_risk_share < t_risk - 0.015:
    advice.append("**Система слишком осторожна**: подними Directness, Risk Appetite или Pass Risk.")
elif pass_risk_share > t_risk + 0.015:
    advice.append("**Слишком много рискованных передач**: снизь Directness, Risk Appetite или компенсируй ростом Openness Reward.")

# Press regain
if press_regain < t_press - 0.015:
    advice.append("**Прессинг не возвращает мяч**: подними Pressing, Defensive Line, Aggression, Stamina.")
elif press_regain > t_press + 0.015:
    advice.append("**Прессинг возвращает слишком много** — выглядит нереалистично для PvE. Снизь Pressing/Defensive Line или подними соперниковый Pass Openness.")

# Dribble share
if dribble_share < t_dribble - 0.015:
    advice.append("**Мало обыгрыша**: увеличь Dribble Bias, WG Dribbling, ST Dribbling или снизь Pass Openness.")
elif dribble_share > t_dribble + 0.015:
    advice.append("**Слишком много дриблинга**: снизь Dribble Bias или Dribbling ключевых ролей; подними Pass Openness / Openness Reward.")

# Forward shot share
if forward_shot_share < t_forward - 0.02:
    advice.append("**Форвард завершает слишком мало**: подними ST Positioning, ST Finishing, Role Specialty Impact, Shot Bias.")
elif forward_shot_share > t_forward + 0.02:
    advice.append("**Слишком много игры через форварда**: слегка снизь ST dominance или усили завершение WG / AM.")

# Shots
if shots_per_match < t_shots - 1.0:
    advice.append("**Мало ударов**: подними Tempo, Shot Bias, Transition Frequency.")
elif shots_per_match > t_shots + 1.0:
    advice.append("**Слишком много ударов — команда стреляет без отбора**: снизь Tempo/Shot Bias, подними Distance Penalty.")

# Shot conversion
if shot_conversion < t_conv - 0.015:
    advice.append("**Низкая реализация**: подними Finishing/Composure/Shot Angle Quality; уменьши Avg Shot Distance и Pressure Penalty.")
elif shot_conversion > t_conv + 0.015:
    advice.append("**Слишком высокая реализация**: снизь Finishing/Composure, подними Avg Shot Distance, Pressure, Distance Penalty.")

if not advice:
    advice.append("**Ты близко к цели по всем основным метрикам.** Теперь добейся того же меньшим числом изменений или другой игровой идентичностью.")

for item in advice:
    st.markdown(f"- {item}")


# -----------------------------
# History of attempts
# -----------------------------
st.markdown("---")
st.subheader("8) История попыток")
st.caption("Сохраняй снапшоты после каждого осмысленного изменения — будешь видеть, что и как двигает метрики.")

if "history" not in st.session_state:
    st.session_state["history"] = []

snapshot_metrics = {name: actual for name, actual, *_ in metrics}
snapshot_targets = {name: target for name, _actual, target, *_ in metrics}

col_a, col_b, col_c = st.columns([1, 1, 1])
with col_a:
    note = st.text_input("Заметка к попытке", value="", placeholder="напр. «+Tempo 10, −Distance Penalty 5»")
with col_b:
    if st.button("💾 Сохранить попытку", use_container_width=True):
        st.session_state["history"].append({
            "note": note or f"{preset}",
            "preset": preset,
            **{f"{k} (actual)": v for k, v in snapshot_metrics.items()},
            **{f"{k} (gap)": snapshot_metrics[k] - snapshot_targets[k] for k in snapshot_metrics},
            "Tempo": tempo, "Directness": directness, "Pressing": pressing,
            "Distance Penalty": distance_penalty, "Risk Appetite": risk_appetite,
            "Shot Bias": shot_bias, "Dribble Bias": dribble_bias,
        })
with col_c:
    if st.button("🗑 Очистить историю", use_container_width=True):
        st.session_state["history"] = []

if st.session_state["history"]:
    hist_df = pd.DataFrame(st.session_state["history"])
    # Reorder columns: note/preset first, then actuals, then gaps, then knobs
    actual_cols = [c for c in hist_df.columns if c.endswith("(actual)")]
    gap_cols = [c for c in hist_df.columns if c.endswith("(gap)")]
    rest = [c for c in hist_df.columns if c not in actual_cols + gap_cols + ["note", "preset"]]
    ordered = ["note", "preset"] + actual_cols + gap_cols + rest
    hist_df = hist_df[ordered]

    fmt_map = {c: "{:+.2f}" for c in gap_cols}
    fmt_map.update({c: "{:.2f}" for c in actual_cols})

    # Last 10 attempts, newest on top
    display_df = hist_df.tail(10).iloc[::-1].reset_index(drop=True)
    st.dataframe(display_df.style.format(fmt_map), use_container_width=True, hide_index=True)

    # Delta vs previous attempt
    if len(hist_df) >= 2:
        prev = hist_df.iloc[-2]
        curr = hist_df.iloc[-1]
        delta_rows = []
        for c in actual_cols:
            d = curr[c] - prev[c]
            if abs(d) > 1e-4:
                delta_rows.append({"Метрика": c.replace(" (actual)", ""), "Δ vs прошлая попытка": d})
        if delta_rows:
            st.markdown("**Что изменилось между двумя последними попытками:**")
            st.dataframe(pd.DataFrame(delta_rows).style.format({"Δ vs прошлая попытка": "{:+.3f}"}), hide_index=True, use_container_width=True)
else:
    st.info("Пока ни одной сохранённой попытки.")


# -----------------------------
# Explanation
# -----------------------------
st.markdown("---")
st.subheader("9) Объяснение логики симулятора")
st.markdown(
    """
Этот sandbox учит трём слоям баланса:

1. **Статы игроков** — определяют качество действий.
2. **Decision weights** — определяют, что ИИ выбирает делать чаще.
3. **Контекст матча** — определяет, насколько вообще легко создать хорошие условия.

Главная мысль: проблема может быть не только в том, что игрок **слабый**, но и в том, что система **редко выбирает правильное действие**.
    """
)

st.caption("Версия учебная: формулы упрощены специально, чтобы причинно-следственные связи было легче понять.")
