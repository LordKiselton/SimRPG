from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple

import pandas as pd
import streamlit as st


st.set_page_config(page_title="Football AI Balance Sandbox", layout="wide")


# -----------------------------
# Helpers
# -----------------------------

def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


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
# Preset dictionaries
# -----------------------------
PRESET_DESCRIPTIONS = {
    "Balanced": "Среднестатистическая команда без ярко выраженного стиля. Аналог: «крепкий середняк АПЛ». Умеренный темп, сбалансированные атака и оборона.",
    "Possession": "Команда, контролирующая мяч 60%+. Низкий directness, высокая точность пасов, терпеливое развитие атак. Аналог: Барселона Гвардиолы, Манчестер Сити.",
    "Direct Vertical": "Быстрая вертикальная игра, много длинных передач и ударов из-за пределов штрафной. Аналог: Ливерпуль Клоппа ранних сезонов, Лестер 2015/16.",
    "Pressing Chaos": "Высокий прессинг по всему полю, много transition-моментов, команда «душит» соперника. Аналог: Ред Булл Лейпциг, Аталанта Гасперини.",
}

ROLE_DESCRIPTIONS = {
    "ST": "**Форвард (Striker).** Главный завершающий. Финальный штрих атаки. Ключевые статы: Finishing, Composure, Positioning.",
    "AM": "**Атакующий полузащитник (Attacking Midfielder).** Под форвардом. Главный креативщик, связка между обороной и атакой. Ключевые статы: Passing, Vision, Dribbling.",
    "CM": "**Центральный полузащитник (Central Midfielder).** Центр поля. Держит мяч, контролирует темп, отбирает. Ключевые статы: Passing, Vision, Press Resistance, Stamina.",
    "WG": "**Крайний нападающий (Winger).** Фланги атаки. Доставка мяча в штрафную, обыгрыш 1-в-1, прострелы. Ключевые статы: Dribbling, Pace, Passing.",
    "FB": "**Крайний защитник (Fullback).** Фланги обороны + подключения в атаку. Ключевые статы: Pace, Stamina, Marking, Passing.",
    "CB": "**Центральный защитник (Centre-Back).** Последняя линия. Опека форвардов соперника, игра на перехват. Ключевые статы: Marking, Aggression, Positioning, Pace.",
}

METRIC_BENCHMARKS = {
    "goals": "Реальный футбол: топ-лиги 2.5–2.9 (АПЛ 24/25 ≈ 2.85), скучные 1.8–2.1.",
    "shots": "Реальный футбол: 20–26 за матч на две команды в топ-лигах. <16 — очень закрытый матч, >30 — аркада.",
    "conversion": "Реальный футбол: 9–13% (средний конверт удар→гол в топ-лигах ≈ 11%).",
    "pass_success": "Реальный футбол: 78–88%. Possession-команды: 87%+. Прямолинейные/длинный пас: 72–78%.",
    "risk_share": "Реальный футбол: 12–22%. Possession ≈ 12–15%, Direct/контратака ≈ 22–28%.",
    "press_regain": "Реальный футбол: 5–10%. High-press (Клопп, Лейпциг): 10–14%. Низкий блок: 3–5%.",
    "dribble_share": "Реальный футбол: 8–16%. Техничные команды: 18–22%. Физические: 5–10%.",
    "forward_share": "Реальный футбол: 35–50%. ST-centric (9.5-форвард): 50%+. False-9 / без чистого форварда: 25–35%.",
}

METRIC_STYLE_HINT = {
    "goals": "→ высокие значения (2.8+): аркадный стиль или суперклуб. Низкие (<2.0): оборонительная лига.",
    "shots": "→ 25+ с низкой конверсией: команда стреляет из мусорных позиций. <15: слишком закрытая игра.",
    "conversion": "→ >15% стабильно: либо суперфорвард, либо баг. <7%: моменты создаются, но бракуются.",
    "pass_success": "→ 90%+: стерильное владение (possession without threat). <75%: игра «на отбой».",
    "risk_share": "→ 25%+: вертикальная игра в стиле Клоппа / Бильсы. <10%: pass-to-pass без риска, как La Masia-clone.",
    "press_regain": "→ 12%+: high-press identity. <4%: low-block, команда ждёт соперника.",
    "dribble_share": "→ 20%+: звезда-обыгрыватель в составе (Месси, Неймар-архетип). <6%: коллективный футбол без индивидуалов.",
    "forward_share": "→ 55%+: классическая «девятка» (Левандовски, Холанд). <25%: false-9 или игра через фланги.",
}


PRESETS = {
    "Balanced": dict(
        team=dict(tempo=55, directness=50, width=54, pressing=56, defensive_line=52, support_runs=57, shot_bias=50, dribble_bias=48),
        ai=dict(distance_penalty=58, pressure_penalty=60, openness_reward=62, risk_appetite=48, role_specialty=62, style_impact=56, skill_impact=64),
        scenario=dict(avg_shot_distance=19.0, shot_angle_quality=58, pressure=56, pass_openness=61, pass_risk=42, transition_freq=52),
    ),
    "Possession": dict(
        team=dict(tempo=48, directness=38, width=58, pressing=54, defensive_line=55, support_runs=63, shot_bias=44, dribble_bias=46),
        ai=dict(distance_penalty=62, pressure_penalty=58, openness_reward=70, risk_appetite=40, role_specialty=60, style_impact=62, skill_impact=64),
        scenario=dict(avg_shot_distance=17.0, shot_angle_quality=63, pressure=53, pass_openness=68, pass_risk=34, transition_freq=44),
    ),
    "Direct Vertical": dict(
        team=dict(tempo=67, directness=72, width=50, pressing=58, defensive_line=50, support_runs=55, shot_bias=58, dribble_bias=47),
        ai=dict(distance_penalty=52, pressure_penalty=60, openness_reward=54, risk_appetite=62, role_specialty=61, style_impact=64, skill_impact=63),
        scenario=dict(avg_shot_distance=20.0, shot_angle_quality=54, pressure=58, pass_openness=55, pass_risk=54, transition_freq=64),
    ),
    "Pressing Chaos": dict(
        team=dict(tempo=71, directness=60, width=56, pressing=76, defensive_line=71, support_runs=58, shot_bias=54, dribble_bias=52),
        ai=dict(distance_penalty=49, pressure_penalty=67, openness_reward=58, risk_appetite=58, role_specialty=59, style_impact=68, skill_impact=61),
        scenario=dict(avg_shot_distance=21.0, shot_angle_quality=51, pressure=67, pass_openness=52, pass_risk=57, transition_freq=73),
    ),
}

TEAM_KEYS = ["tempo", "directness", "width", "pressing", "defensive_line", "support_runs", "shot_bias", "dribble_bias"]
AI_KEYS = ["distance_penalty", "pressure_penalty", "openness_reward", "risk_appetite", "role_specialty", "style_impact", "skill_impact"]
SCENARIO_KEYS = ["avg_shot_distance", "shot_angle_quality", "pressure", "pass_openness", "pass_risk", "transition_freq"]
ROLE_STAT_KEYS = ["fin", "pas", "vis", "dri", "com", "pr", "mar", "pac", "sta", "agg", "pos"]
PLAYER_SLIDER_KEYS = [f"{role}_{stat}" for role in ["ST", "AM", "CM", "WG", "FB", "CB"] for stat in ROLE_STAT_KEYS]
TUNABLE_KEYS = TEAM_KEYS + AI_KEYS + SCENARIO_KEYS + PLAYER_SLIDER_KEYS


def reset_tunables():
    for k in TUNABLE_KEYS:
        st.session_state.pop(k, None)
    st.session_state["baseline"] = None


# -----------------------------
# Sidebar
# -----------------------------
with st.sidebar:
    st.title("Football AI Balance Sandbox")
    st.caption("Учебный симулятор для начинающего balance / AI game designer.")

    preset = st.selectbox(
        "Стартовый пресет",
        list(PRESETS.keys()),
        help="Быстрый способ начать с разных игровых идентичностей. Меняет и статы игроков.",
    )
    st.caption(PRESET_DESCRIPTIONS[preset])

    if st.session_state.get("active_preset") != preset:
        for k in TUNABLE_KEYS:
            st.session_state.pop(k, None)
        st.session_state["active_preset"] = preset
        st.session_state["baseline"] = None

    st.button("🔄 К дефолтам пресета", on_click=reset_tunables, width='stretch')

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


defaults = PRESETS[preset]
roles = apply_player_preset(base_roles(), preset)


# -----------------------------
# Title + mental model
# -----------------------------
st.title("Football AI Balance Sandbox")
st.write(
    "Меняй **статы игроков**, **командный стиль**, **веса принятия решений** и **контекст матча**, "
    "чтобы привести систему к целевым метрикам. Это тренажёр логики, а не реалистичная матч-симуляция."
)

with st.expander("⚽ Футбол за 5 минут (раскрой, если слабо знаком с игрой)", expanded=False):
    st.markdown(
        """
**Базовая рамка:**
- 11 vs 11 на поле ~100×65 м. Матч = 90 минут. Забил больше — победил.
- В обычном матче забивается **2–3 гола**, делается **~22 удара** на две команды, совершается **~900 передач**.
- Игра циклична: атака → потеря → оборона → перехват → атака. Этот цикл называют **transition** (переход).

**Три фазы игры (команда с мячом / команда без мяча):**
- **Атака (attacking)** — позиционное развитие: передачи, движение, поиск момента.
- **Оборона (defending)** — отбор: либо «закрыться» низким блоком, либо давить высоко (**pressing**).
- **Переход (transition)** — первые 5 секунд после потери/перехвата. Часто решают исход момента.

**Ключевые концепты (они внутри тренажёра):**
- **xG (expected goals)** — «качество момента». Удар из 6-метровой зоны ≈ 0.3 xG, удар с 30 метров ≈ 0.03 xG. В модели это `Shot Angle Quality` + `Avg Shot Distance`.
- **Pressing** — коллективное давление высоко по полю. Цель: отобрать мяч ближе к чужим воротам. Метрика `Press regain rate` — как часто получается.
- **Directness** — насколько вертикально играет команда. Высокий directness = длинные передачи вперёд (Клопп, Бильса). Низкий = короткий пас, контроль (Гвардиола).
- **Possession vs Counter** — два полюса идентичности: держать мяч или быстро бить в переходе.

**Роли (тактические позиции):** ST (форвард) · AM (под форвардом, креатив) · CM (центр поля) · WG (фланги атаки) · FB (фланги обороны) · CB (центр обороны).

**Для трансфера из геймдизайна:** можешь думать о футболе как о team-based экшене с ограниченным ростером. Статы — это «характеристики юнитов», decision weights — «AI behaviour tree priorities», context — «арена/условия боя», а target-метрики — это «KPI матча», который ты балансишь, как winrate в PvE.
"""
    )


with st.expander("📋 Как мыслить ГД по балансу AI (раскрой перед работой)", expanded=False):
    st.markdown(
        """
1. **Читай gap, а не actual.** Актуальное число само по себе ничего не значит без цели.
2. **Трогай один слой за раз.** Сначала только статы. Потом только decision weights. Потом только контекст. Иначе не поймёшь, что именно сработало.
3. **Следи за соседними метриками.** Починил одну — проверь, не сломал ли две другие. Баланс — это компромисс, не оптимизация одной цифры.
4. **Минимальное изменение > максимальное.** Если цель достигается движением ползунка на 3 пункта — не крути на 30.
5. **Сохраняй снапшот ПЕРЕД крупным изменением, не после.** Тогда у тебя всегда есть точка возврата, если всё развалится.
"""
    )


target_col, output_col = st.columns([1, 1.25])

with target_col:
    st.subheader("1) Целевые метрики")
    t_goals = st.slider("Goals per match", 0.5, 5.0, 2.4, 0.1, key="t_goals", help="Среднее число голов за матч.")
    st.caption(METRIC_BENCHMARKS["goals"])
    t_shots = st.slider("Shots per match", 6.0, 35.0, 21.0, 0.5, key="t_shots", help="Среднее количество ударов за матч.")
    st.caption(METRIC_BENCHMARKS["shots"])
    t_conv = st.slider("Shot conversion", 0.03, 0.35, 0.11, 0.01, key="t_conv", help="Доля ударов, которые превращаются в голы.")
    st.caption(METRIC_BENCHMARKS["conversion"])
    t_pass = st.slider("Pass success", 0.60, 0.96, 0.84, 0.01, key="t_pass", help="Доля успешных передач.")
    st.caption(METRIC_BENCHMARKS["pass_success"])
    t_risk = st.slider("High-risk pass share", 0.00, 0.50, 0.18, 0.01, key="t_risk", help="Доля рискованных передач от всех передач.")
    st.caption(METRIC_BENCHMARKS["risk_share"])
    t_press = st.slider("Press regain rate", 0.00, 0.30, 0.09, 0.01, key="t_press", help="Как часто команда возвращает мяч за счёт прессинга.")
    st.caption(METRIC_BENCHMARKS["press_regain"])
    t_dribble = st.slider("Dribble attempt share", 0.00, 0.40, 0.14, 0.01, key="t_dribble", help="Какую долю решений с мячом составляют попытки дриблинга.")
    st.caption(METRIC_BENCHMARKS["dribble_share"])
    t_forward = st.slider("Forward shot share", 0.00, 0.80, 0.42, 0.01, key="t_forward", help="Какая доля ударов команды приходится на форварда.")
    st.caption(METRIC_BENCHMARKS["forward_share"])

with output_col:
    st.subheader("2) Рабочий процесс")
    st.info(
        "Сначала попробуй попасть в target только статами. Потом повтори то же самое, но трогай только decision weights. "
        "Так ты почувствуешь разницу между балансом качеств и балансом решений.",
        icon="🧠",
    )
    st.caption("Снапшоты конфигурации сохраняются в «8) История попыток» ниже. Δ baseline рядом с каждой метрикой — это разница с моментом, когда ты выбрал пресет.")


# -----------------------------
# Player stats (collapsed)
# -----------------------------
with st.expander("Статы игроков (6 ролей × 11 параметров) — раскрой чтобы крутить", expanded=False):
    role_tabs = st.tabs(list(roles.keys()))
    for tab, role_name in zip(role_tabs, roles.keys()):
        role = roles[role_name]
        with tab:
            st.caption(ROLE_DESCRIPTIONS[role_name])
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
    tempo = st.slider("Tempo", 0, 100, defaults["team"]["tempo"], key="tempo", help=TERM_HELP["Tempo"])
    directness = st.slider("Directness", 0, 100, defaults["team"]["directness"], key="directness", help=TERM_HELP["Directness"])
    width = st.slider("Width", 0, 100, defaults["team"]["width"], key="width", help=TERM_HELP["Width"])
    pressing = st.slider("Pressing", 0, 100, defaults["team"]["pressing"], key="pressing", help=TERM_HELP["Pressing"])
    defensive_line = st.slider("Defensive Line", 0, 100, defaults["team"]["defensive_line"], key="defensive_line", help=TERM_HELP["Defensive Line"])
    support_runs = st.slider("Support Runs", 0, 100, defaults["team"]["support_runs"], key="support_runs", help=TERM_HELP["Support Runs"])
    shot_bias = st.slider("Shot Bias", 0, 100, defaults["team"]["shot_bias"], key="shot_bias", help=TERM_HELP["Shot Bias"])
    dribble_bias = st.slider("Dribble Bias", 0, 100, defaults["team"]["dribble_bias"], key="dribble_bias", help=TERM_HELP["Dribble Bias"])

with middle:
    st.subheader("4) AI weights")
    distance_penalty = st.slider("Distance Penalty", 0, 100, defaults["ai"]["distance_penalty"], key="distance_penalty", help=TERM_HELP["Distance Penalty"])
    pressure_penalty = st.slider("Pressure Penalty", 0, 100, defaults["ai"]["pressure_penalty"], key="pressure_penalty", help=TERM_HELP["Pressure Penalty"])
    openness_reward = st.slider("Openness Reward", 0, 100, defaults["ai"]["openness_reward"], key="openness_reward", help=TERM_HELP["Openness Reward"])
    risk_appetite = st.slider("Risk Appetite", 0, 100, defaults["ai"]["risk_appetite"], key="risk_appetite", help=TERM_HELP["Risk Appetite"])
    role_specialty = st.slider("Role Specialty Impact", 0, 100, defaults["ai"]["role_specialty"], key="role_specialty", help=TERM_HELP["Role Specialty Impact"])
    style_impact = st.slider("Style Impact", 0, 100, defaults["ai"]["style_impact"], key="style_impact", help=TERM_HELP["Style Impact"])
    skill_impact = st.slider("Skill Impact", 0, 100, defaults["ai"]["skill_impact"], key="skill_impact", help=TERM_HELP["Skill Impact"])

with right:
    st.subheader("5) Match context")
    avg_shot_distance = st.slider("Average Shot Distance", 8.0, 30.0, defaults["scenario"]["avg_shot_distance"], 0.5, key="avg_shot_distance", help=TERM_HELP["Average Shot Distance"])
    shot_angle_quality = st.slider("Shot Angle Quality", 0, 100, defaults["scenario"]["shot_angle_quality"], key="shot_angle_quality", help=TERM_HELP["Shot Angle Quality"])
    pressure = st.slider("Pressure", 0, 100, defaults["scenario"]["pressure"], key="pressure", help=TERM_HELP["Pressure"])
    pass_openness = st.slider("Pass Openness", 0, 100, defaults["scenario"]["pass_openness"], key="pass_openness", help=TERM_HELP["Pass Openness"])
    pass_risk = st.slider("Pass Risk", 0, 100, defaults["scenario"]["pass_risk"], key="pass_risk", help=TERM_HELP["Pass Risk"])
    transition_freq = st.slider("Transition Frequency", 0, 100, defaults["scenario"]["transition_freq"], key="transition_freq", help=TERM_HELP["Transition Frequency"])


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
# Metric formatters
# -----------------------------
def fmt_value(key: str, v: float) -> str:
    if key in ("goals",):
        return f"{v:.2f}"
    if key == "shots":
        return f"{v:.1f}"
    return f"{v * 100:.0f}%"


def fmt_delta(key: str, v: float) -> str:
    sign = "+" if v >= 0 else "−"
    absv = abs(v)
    if key == "goals":
        return f"{sign}{absv:.2f}"
    if key == "shots":
        return f"{sign}{absv:.1f}"
    return f"{sign}{absv * 100:.1f} п.п."


# -----------------------------
# Metric explainer — breakdown of each output formula
# -----------------------------
def explain(metric_key: str) -> List[Dict]:
    """Return list of {factor, value, weight, contrib, sign} for a metric, sorted by |contrib| desc."""
    n = normalize_100
    if metric_key == "goals":
        # goals = shots × conversion — driven indirectly. Show shots and conversion as "factors".
        rows = [
            {"factor": "Shots per match", "value": shots_per_match, "weight": shot_conversion, "contrib": shots_per_match * shot_conversion},
            {"factor": "Shot conversion", "value": shot_conversion, "weight": shots_per_match, "contrib": shots_per_match * shot_conversion},
        ]
    elif metric_key == "shots":
        rows = [
            {"factor": "Tempo", "value": tempo, "weight": 9.0, "contrib": 9.0 * n(tempo)},
            {"factor": "Transition Frequency", "value": transition_freq, "weight": 5.0, "contrib": 5.0 * n(transition_freq)},
            {"factor": "Shoot intent (derived)", "value": clamp(shoot_intent, 0.0, 1.0), "weight": 4.0, "contrib": 4.0 * clamp(shoot_intent, 0.0, 1.0)},
            {"factor": "Directness", "value": directness, "weight": 2.5, "contrib": 2.5 * n(directness)},
            {"factor": "Distance Penalty", "value": distance_penalty, "weight": -2.5, "contrib": -2.5 * n(distance_penalty)},
            {"factor": "База", "value": 8.0, "weight": 1.0, "contrib": 8.0},
        ]
    elif metric_key == "conversion":
        pp_press = n(pressure_penalty) * n(pressure)
        rows = [
            {"factor": "Finishing (team)", "value": finishing_team, "weight": 0.08, "contrib": 0.08 * n(finishing_team)},
            {"factor": "Composure (team)", "value": composure_team, "weight": 0.06, "contrib": 0.06 * n(composure_team)},
            {"factor": "Shot Angle Quality", "value": shot_angle_quality, "weight": 0.05, "contrib": 0.05 * n(shot_angle_quality)},
            {"factor": "Positioning (team)", "value": positioning_team, "weight": 0.02, "contrib": 0.02 * n(positioning_team)},
            {"factor": "Avg Shot Distance", "value": avg_shot_distance, "weight": -0.06, "contrib": -0.06 * n(avg_shot_distance * 3.0)},
            {"factor": "Pressure × Pressure Penalty", "value": pp_press * 100, "weight": -0.05, "contrib": -0.05 * pp_press},
            {"factor": "Skill Impact", "value": skill_impact, "weight": 0.02, "contrib": 0.02 * n(skill_impact)},
            {"factor": "База", "value": 0.04, "weight": 1.0, "contrib": 0.04},
        ]
    elif metric_key == "pass_success":
        rows = [
            {"factor": "Passing (team)", "value": passing_team, "weight": 0.10, "contrib": 0.10 * n(passing_team)},
            {"factor": "Vision (team)", "value": vision_team, "weight": 0.08, "contrib": 0.08 * n(vision_team)},
            {"factor": "Press Resist (team)", "value": press_resist_team, "weight": 0.05, "contrib": 0.05 * n(press_resist_team)},
            {"factor": "Pass Openness", "value": pass_openness, "weight": 0.04, "contrib": 0.04 * n(pass_openness)},
            {"factor": "Pass Risk", "value": pass_risk, "weight": -0.07, "contrib": -0.07 * n(pass_risk)},
            {"factor": "Pressure", "value": pressure, "weight": -0.05, "contrib": -0.05 * n(pressure)},
            {"factor": "Openness Reward", "value": openness_reward, "weight": 0.02, "contrib": 0.02 * n(openness_reward)},
            {"factor": "База", "value": 0.62, "weight": 1.0, "contrib": 0.62},
        ]
    elif metric_key == "risk_share":
        rows = [
            {"factor": "Directness", "value": directness, "weight": 0.24, "contrib": 0.24 * n(directness)},
            {"factor": "Risk Appetite", "value": risk_appetite, "weight": 0.20, "contrib": 0.20 * n(risk_appetite)},
            {"factor": "Pass Risk", "value": pass_risk, "weight": 0.18, "contrib": 0.18 * n(pass_risk)},
            {"factor": "Openness Reward", "value": openness_reward, "weight": -0.12, "contrib": -0.12 * n(openness_reward)},
            {"factor": "База", "value": 0.06, "weight": 1.0, "contrib": 0.06},
        ]
    elif metric_key == "press_regain":
        rows = [
            {"factor": "Pressing", "value": pressing, "weight": 0.08, "contrib": 0.08 * n(pressing)},
            {"factor": "Defensive Line", "value": defensive_line, "weight": 0.05, "contrib": 0.05 * n(defensive_line)},
            {"factor": "Aggression (team)", "value": aggression_team, "weight": 0.05, "contrib": 0.05 * n(aggression_team)},
            {"factor": "Stamina (team)", "value": stamina_team, "weight": 0.03, "contrib": 0.03 * n(stamina_team)},
            {"factor": "Pass Openness", "value": pass_openness, "weight": -0.02, "contrib": -0.02 * n(pass_openness)},
            {"factor": "База", "value": 0.02, "weight": 1.0, "contrib": 0.02},
        ]
    elif metric_key == "dribble_share":
        rows = [
            {"factor": "Dribble Bias", "value": dribble_bias, "weight": 0.20, "contrib": 0.20 * n(dribble_bias)},
            {"factor": "Dribbling (team)", "value": dribbling_team, "weight": 0.18, "contrib": 0.18 * n(dribbling_team)},
            {"factor": "WG Dribbling", "value": WG.dribbling, "weight": 0.06, "contrib": 0.06 * n(WG.dribbling)},
            {"factor": "ST Dribbling", "value": ST.dribbling, "weight": 0.05, "contrib": 0.05 * n(ST.dribbling)},
            {"factor": "Pass Openness", "value": pass_openness, "weight": -0.10, "contrib": -0.10 * n(pass_openness)},
            {"factor": "База", "value": 0.04, "weight": 1.0, "contrib": 0.04},
        ]
    elif metric_key == "forward_share":
        rows = [
            {"factor": "ST Finishing", "value": ST.finishing, "weight": 0.18, "contrib": 0.18 * n(ST.finishing)},
            {"factor": "ST Positioning", "value": ST.positioning, "weight": 0.14, "contrib": 0.14 * n(ST.positioning)},
            {"factor": "Role Specialty Impact", "value": role_specialty, "weight": 0.08, "contrib": 0.08 * n(role_specialty)},
            {"factor": "Shot Bias", "value": shot_bias, "weight": 0.06, "contrib": 0.06 * n(shot_bias)},
            {"factor": "WG Finishing", "value": WG.finishing, "weight": -0.08, "contrib": -0.08 * n(WG.finishing)},
            {"factor": "AM Finishing", "value": AM.finishing, "weight": -0.05, "contrib": -0.05 * n(AM.finishing)},
            {"factor": "База", "value": 0.18, "weight": 1.0, "contrib": 0.18},
        ]
    else:
        rows = []
    # Sort by absolute contribution, keep база last
    base_row = next((r for r in rows if r["factor"] == "База"), None)
    rows = [r for r in rows if r["factor"] != "База"]
    rows.sort(key=lambda r: abs(r["contrib"]), reverse=True)
    if base_row:
        rows.append(base_row)
    return rows


# -----------------------------
# Baseline tracking
# -----------------------------
metrics = [
    ("Goals per match", goals_per_match, t_goals, "goals", 0.15),
    ("Shots per match", shots_per_match, t_shots, "shots", 1.0),
    ("Shot conversion", shot_conversion, t_conv, "conversion", 0.015),
    ("Pass success", pass_success, t_pass, "pass_success", 0.015),
    ("High-risk pass share", pass_risk_share, t_risk, "risk_share", 0.015),
    ("Press regain rate", press_regain, t_press, "press_regain", 0.015),
    ("Dribble attempt share", dribble_share, t_dribble, "dribble_share", 0.015),
    ("Forward shot share", forward_shot_share, t_forward, "forward_share", 0.02),
]

if st.session_state.get("baseline") is None:
    st.session_state["baseline"] = {key: actual for _name, actual, _t, key, _tol in metrics}
baseline = st.session_state["baseline"]


# -----------------------------
# Output cards
# -----------------------------
st.markdown("---")
st.subheader("6) Итоговые метрики")

row1 = st.columns(4)
row2 = st.columns(4)
for idx, (name, actual, target, key, _tol) in enumerate(metrics):
    hint, color = range_hint(actual, GOOD_RANGES[key], CAUTION_RANGES[key])
    gap = actual - target
    delta_base = actual - baseline.get(key, actual)
    card = (
        f"<div style='padding:12px;border-radius:14px;border:1px solid #e5e7eb;height:210px;'>"
        f"<div style='font-weight:700;font-size:16px;margin-bottom:6px;'>{name}</div>"
        f"<div style='font-size:28px;font-weight:800;margin-bottom:4px;'>{fmt_value(key, actual)}</div>"
        f"<div style='color:{color};font-weight:700;margin-bottom:6px;font-size:13px;'>{hint}</div>"
        f"<div style='font-size:12px;color:#374151;'>Target: <b>{fmt_value(key, target)}</b></div>"
        f"<div style='font-size:12px;color:#374151;'>Gap: <b>{fmt_delta(key, gap)}</b></div>"
        f"<div style='font-size:12px;color:#6b7280;'>Δ baseline: <b>{fmt_delta(key, delta_base)}</b></div>"
        f"</div>"
    )
    (row1 if idx < 4 else row2)[idx % 4].markdown(card, unsafe_allow_html=True)


# -----------------------------
# Metric explainer (one expander with inner tabs)
# -----------------------------
with st.expander("🔎 Почему получилась именно такая цифра (разложение формул)", expanded=False):
    ex_tabs = st.tabs([name for name, *_ in metrics])
    for tab, (name, actual, target, key, _tol) in zip(ex_tabs, metrics):
        with tab:
            rows = explain(key)
            if not rows:
                st.write("Нет разложения для этой метрики.")
                continue
            df = pd.DataFrame(rows)
            df["Знак"] = df["weight"].apply(lambda w: "↑" if w > 0 else ("↓" if w < 0 else "·"))
            df = df.rename(columns={"factor": "Фактор", "value": "Значение", "weight": "Вес", "contrib": "Вклад"})
            df = df[["Фактор", "Знак", "Значение", "Вес", "Вклад"]]
            st.dataframe(
                df.style.format({"Значение": "{:.1f}", "Вес": "{:+.3f}", "Вклад": "{:+.4f}"}),
                hide_index=True,
                width='stretch',
            )
            st.caption(f"Текущее: **{fmt_value(key, actual)}** · Target: {fmt_value(key, target)} · "
                       f"Сортировка по |Вклад|. «База» — свободный член формулы.")
            st.caption(f"*Тактический смысл:* {METRIC_STYLE_HINT.get(key, '')}")


# -----------------------------
# Gap chart
# -----------------------------
st.markdown("#### Визуализация gap")
st.caption("Нормализованный |actual − target| / target. Чем выше столбик, тем дальше от цели. Красный = выше target, синий = ниже.")

gap_rows = []
for name, actual, target, _key, _tol in metrics:
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
    st.altair_chart(chart, width='stretch')
except ImportError:
    st.bar_chart(gap_df.set_index("Метрика")["|Relative gap|"])


# -----------------------------
# Diagnostics (two-sided)
# -----------------------------
st.markdown("---")
st.subheader("7) Диагностика: что крутить")

advice = []
if goals_per_match < t_goals - 0.15:
    if shot_conversion < t_conv:
        advice.append("**Не хватает реализации**: подними ST Finishing, ST Composure, Shot Angle Quality или ослабь Pressure Penalty / Pressure. *Модель:* `goals = shots × conversion`. Если shots ок, а голов мало — проблема в качестве моментов или в завершителе.")
    if shots_per_match < t_shots:
        advice.append("**Не хватает объёма атак**: подними Tempo, Shot Bias, Transition Frequency или снизь Distance Penalty. *Модель:* объём ударов = быстрые атаки (Tempo) + склонность бить (Shot Bias) + частые перехваты (Transition).")
elif goals_per_match > t_goals + 0.15:
    advice.append("**Результативность выше target**: снизь ST Finishing/Composure, подними Pressure/Distance Penalty или снизь Tempo/Shot Bias.")

if pass_success < t_pass - 0.015:
    advice.append("**Передачи нестабильны**: подними Passing, Vision, Pass Openness или снизь Pass Risk / Pressure. *Модель:* точность паса = качество исполнителя (Passing) × видение варианта (Vision) × свобода выбора (Openness) ÷ сложность передачи (Pass Risk + Pressure).")
elif pass_success > t_pass + 0.015:
    advice.append("**Пас слишком стерильный**: подними Pass Risk, Directness, Risk Appetite — команда играет в «безопасный» перекат. *Модель:* 92%+ pass success без высокого risk share = «tiki-taka без угрозы». Красиво, но голов не будет.")

if pass_risk_share < t_risk - 0.015:
    advice.append("**Система слишком осторожна**: подними Directness, Risk Appetite или Pass Risk.")
elif pass_risk_share > t_risk + 0.015:
    advice.append("**Слишком много рискованных передач**: снизь Directness, Risk Appetite или компенсируй ростом Openness Reward.")

if press_regain < t_press - 0.015:
    advice.append("**Прессинг не возвращает мяч**: подними Pressing, Defensive Line, Aggression, Stamina. *Модель:* высокий прессинг работает только тройкой — команда (а) **стоит выше** (defensive line), (б) **давит интенсивнее** (pressing + aggression), (в) **выдерживает 90 минут** (stamina). Без одного ингредиента схема разваливается.")
elif press_regain > t_press + 0.015:
    advice.append("**Прессинг возвращает слишком много** — выглядит нереалистично для PvE. Снизь Pressing/Defensive Line или подними соперниковый Pass Openness.")

if dribble_share < t_dribble - 0.015:
    advice.append("**Мало обыгрыша**: увеличь Dribble Bias, WG Dribbling, ST Dribbling или снизь Pass Openness.")
elif dribble_share > t_dribble + 0.015:
    advice.append("**Слишком много дриблинга**: снизь Dribble Bias или Dribbling ключевых ролей; подними Pass Openness / Openness Reward.")

if forward_shot_share < t_forward - 0.02:
    advice.append("**Форвард завершает слишком мало**: подними ST Positioning, ST Finishing, Role Specialty Impact, Shot Bias.")
elif forward_shot_share > t_forward + 0.02:
    advice.append("**Слишком много игры через форварда**: слегка снизь ST dominance или усили завершение WG / AM.")

if shots_per_match < t_shots - 1.0:
    advice.append("**Мало ударов**: подними Tempo, Shot Bias, Transition Frequency.")
elif shots_per_match > t_shots + 1.0:
    advice.append("**Слишком много ударов — команда стреляет без отбора**: снизь Tempo/Shot Bias, подними Distance Penalty.")

if shot_conversion < t_conv - 0.015:
    advice.append("**Низкая реализация**: подними Finishing/Composure/Shot Angle Quality; уменьши Avg Shot Distance и Pressure Penalty.")
elif shot_conversion > t_conv + 0.015:
    advice.append("**Слишком высокая реализация**: снизь Finishing/Composure, подними Avg Shot Distance, Pressure, Distance Penalty.")

if not advice:
    advice.append("**Ты близко к цели по всем основным метрикам.** Теперь добейся того же меньшим числом изменений или другой игровой идентичностью.")

for item in advice:
    st.markdown(f"- {item}")


# -----------------------------
# History of attempts + best
# -----------------------------
st.markdown("---")
st.subheader("8) История попыток")
st.caption("Сохраняй снапшоты после каждого осмысленного изменения. Лучший результат (минимальная суммарная |gap|) подсвечивается зелёным.")

if "history" not in st.session_state:
    st.session_state["history"] = []

col_a, col_b, col_c = st.columns([1, 1, 1])
with col_a:
    note = st.text_input("Заметка к попытке", value="", placeholder="напр. «+Tempo 10, −Distance Penalty 5»")
with col_b:
    if st.button("💾 Сохранить попытку", width='stretch'):
        score = sum(
            abs((actual - target) / target)
            for _n, actual, target, _k, _tol in metrics
            if target
        )
        snapshot = {
            "note": note or preset,
            "preset": preset,
            "_score": score,
            **{f"{name} (actual)": actual for name, actual, _t, _k, _tol in metrics},
            **{f"{name} (gap)": actual - target for name, actual, target, _k, _tol in metrics},
            "Tempo": tempo, "Directness": directness, "Pressing": pressing,
            "Distance Penalty": distance_penalty, "Risk Appetite": risk_appetite,
            "Shot Bias": shot_bias, "Dribble Bias": dribble_bias,
        }
        st.session_state["history"].append(snapshot)
with col_c:
    if st.button("🗑 Очистить историю", width='stretch'):
        st.session_state["history"] = []

if st.session_state["history"]:
    hist_df = pd.DataFrame(st.session_state["history"])
    actual_cols = [c for c in hist_df.columns if c.endswith("(actual)")]
    gap_cols = [c for c in hist_df.columns if c.endswith("(gap)")]
    rest = [c for c in hist_df.columns if c not in actual_cols + gap_cols + ["note", "preset", "_score"]]
    ordered = ["note", "preset"] + actual_cols + gap_cols + rest
    hist_df_ordered = hist_df[ordered]

    best_idx = hist_df["_score"].idxmin()
    kept = hist_df.tail(10).iloc[::-1].index.tolist()
    best_position = kept.index(best_idx) if best_idx in kept else -1
    display_df = hist_df_ordered.tail(10).iloc[::-1].reset_index(drop=True)

    fmt_map = {c: "{:+.3f}" for c in gap_cols}
    fmt_map.update({c: "{:.3f}" for c in actual_cols})

    def highlight_best(row):
        if row.name == best_position:
            return ["background-color: #dcfce7"] * len(row)
        return [""] * len(row)

    st.dataframe(
        display_df.style.format(fmt_map).apply(highlight_best, axis=1),
        width='stretch',
        hide_index=True,
    )
    st.caption(f"🏆 Лучшая попытка: «{hist_df.loc[best_idx, 'note']}» — суммарный нормализованный |gap| = {hist_df.loc[best_idx, '_score']:.2f}")

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
            st.dataframe(pd.DataFrame(delta_rows).style.format({"Δ vs прошлая попытка": "{:+.3f}"}), hide_index=True, width='stretch')
else:
    st.info("Пока ни одной сохранённой попытки.")


# -----------------------------
# Knob impact matrix
# -----------------------------
with st.expander("🗺 Карта влияний: какой ползунок двигает какую метрику", expanded=False):
    st.caption("Качественная карта на основе коэффициентов формул. ↑↑ сильно повышает, ↑ повышает, — почти не влияет, ↓ понижает, ↓↓ сильно понижает.")
    matrix_rows = [
        {"Ползунок": "Tempo",            "Goals": "↑↑", "Shots": "↑↑", "Conv.": "—",  "PassS": "—",  "Risk":  "—",  "PressR":"—",  "Dribb":"—",  "Forw":"—"},
        {"Ползунок": "Directness",       "Goals": "↑",  "Shots": "↑",  "Conv.": "—",  "PassS": "↓",  "Risk":  "↑↑", "PressR":"—",  "Dribb":"—",  "Forw":"—"},
        {"Ползунок": "Pressing",         "Goals": "—",  "Shots": "—",  "Conv.": "—",  "PassS": "—",  "Risk":  "—",  "PressR":"↑↑", "Dribb":"—",  "Forw":"—"},
        {"Ползунок": "Distance Penalty", "Goals": "↓",  "Shots": "↓↓", "Conv.": "—",  "PassS": "—",  "Risk":  "—",  "PressR":"—",  "Dribb":"—",  "Forw":"—"},
        {"Ползунок": "Risk Appetite",    "Goals": "—",  "Shots": "—",  "Conv.": "—",  "PassS": "↓",  "Risk":  "↑↑", "PressR":"—",  "Dribb":"—",  "Forw":"—"},
        {"Ползунок": "Shot Bias",        "Goals": "↑",  "Shots": "↑↑", "Conv.": "—",  "PassS": "—",  "Risk":  "—",  "PressR":"—",  "Dribb":"—",  "Forw":"↑"},
        {"Ползунок": "Dribble Bias",     "Goals": "—",  "Shots": "—",  "Conv.": "—",  "PassS": "—",  "Risk":  "—",  "PressR":"—",  "Dribb":"↑↑", "Forw":"—"},
        {"Ползунок": "Pass Risk",        "Goals": "—",  "Shots": "—",  "Conv.": "—",  "PassS": "↓↓", "Risk":  "↑↑", "PressR":"—",  "Dribb":"—",  "Forw":"—"},
        {"Ползунок": "Openness Reward",  "Goals": "—",  "Shots": "—",  "Conv.": "—",  "PassS": "↑",  "Risk":  "↓",  "PressR":"—",  "Dribb":"—",  "Forw":"—"},
        {"Ползунок": "Avg Shot Distance","Goals": "↓",  "Shots": "—",  "Conv.": "↓↓", "PassS": "—",  "Risk":  "—",  "PressR":"—",  "Dribb":"—",  "Forw":"—"},
        {"Ползунок": "Shot Angle Quality","Goals": "↑", "Shots": "—",  "Conv.": "↑",  "PassS": "—",  "Risk":  "—",  "PressR":"—",  "Dribb":"—",  "Forw":"—"},
        {"Ползунок": "Pressure",         "Goals": "↓",  "Shots": "—",  "Conv.": "↓",  "PassS": "↓",  "Risk":  "—",  "PressR":"—",  "Dribb":"—",  "Forw":"—"},
        {"Ползунок": "Pass Openness",    "Goals": "—",  "Shots": "—",  "Conv.": "—",  "PassS": "↑",  "Risk":  "—",  "PressR":"↓",  "Dribb":"↓",  "Forw":"—"},
    ]
    st.dataframe(pd.DataFrame(matrix_rows), hide_index=True, width='stretch')


# -----------------------------
# Explanation footer
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
