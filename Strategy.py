
import json
import math
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt


# -----------------------------
# 🧩 Модель
# -----------------------------

FACTIONS = ["🔵 Blue", "🔴 Red"]
STRATEGIC_TYPES = ["🪙 Gold", "💎 Crystal"]


@dataclass
class NodeConfig:
    name: str
    resource_type: str  # "🪙 Gold" or "💎 Crystal"
    capacity: float     # max запас
    regen: float        # regen/day
    base_yield: float   # добыча на 1 добытчика (в день) при полном запасе
    danger: float       # 0..1 влияет на риск перевозки и шанс боя


@dataclass
class SimConfig:
    # 👥 Популяция
    players_total: int = 100
    days: int = 60

    # 🍞 Гарантированный минимум снабжения (безопасные источники)
    safe_supply_per_player: float = 1.0
    losing_safe_multiplier: float = 0.2  # проигрывающие получают 20%

    # ⚙️ Конверсия ресурсов в "снабжение"
    supply_from_gold: float = 0.05      # 1 gold -> supply
    supply_from_crystal: float = 0.12   # 1 crystal -> supply

    # 🧰 Расход снабжения
    supply_upkeep_per_player: float = 0.10  # ежедневное "содержание"
    supply_cost_per_fighter: float = 0.20   # расход снабжения на 1 бойца в день (если участвует в стычке)

    # ⚔️ PvP механика
    skirmish_base_prob: float = 0.25         # базовая вероятность стычки на узле в день
    hot_phase_multiplier: float = 1.6        # множитель вероятности в горячей фазе
    hot_phase_threshold_total_stock_ratio: float = 0.35  # горячая фаза если суммарный запас < X от суммарной емкости
    contest_fraction: float = 0.60           # какая доля добытчиков "вступает в бой" когда стычка случилась
    randomness: float = 0.20                 # случайность результата (0..1)
    casualty_rate: float = 0.08              # доля бойцов, теряемых (выведенных из строя) у проигравшего
    loot_share_on_win: float = 0.35          # доля добычи/груза, перехваченная победителем

    # 🚚 Риск перевозки
    transport_base_loss: float = 0.02        # минимальный риск потери груза
    transport_danger_loss: float = 0.20      # добавка от danger (0..1)
    transport_hot_multiplier: float = 1.3    # множитель риска в горячей фазе

    # 🧠 Поведение фракций (простая стратегия)
    miners_share: float = 0.55  # доля игроков, которых фракция пытается держать "на добыче"
    focus_weight_crystal: float = 1.0  # предпочтение кристаллов (если >1, будут сильнее фокусить кристалл)


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def softcap_supply_factor(supply_per_player: float) -> float:
    """
    Преобразует снабжение/игрока в множитель силы.
      0.0 -> ~0.6
      1.0 -> ~1.0
      2.0 -> ~1.15
    """
    return 0.6 + 0.65 * (1 - math.exp(-1.2 * supply_per_player))


def choose_winner(strength_a: float, strength_b: float, randomness: float, rng: np.random.Generator) -> int:
    noise_a = rng.normal(0, randomness * strength_a)
    noise_b = rng.normal(0, randomness * strength_b)
    sa = max(1e-6, strength_a + noise_a)
    sb = max(1e-6, strength_b + noise_b)
    p_a = sa / (sa + sb)
    return 0 if rng.random() < p_a else 1


def is_hot_phase(total_stock: float, total_capacity: float, threshold_ratio: float) -> bool:
    if total_capacity <= 0:
        return False
    return (total_stock / total_capacity) < threshold_ratio


def node_value_weight(node: NodeConfig, cfg: SimConfig) -> float:
    base = 1.0
    if node.resource_type == "💎 Crystal":
        base *= cfg.focus_weight_crystal
    base *= (1.0 - 0.25 * node.danger)
    return max(0.1, base)


def simulate(cfg: SimConfig, nodes: List[NodeConfig], seed: int = 42) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)

    players_per_faction = {FACTIONS[0]: cfg.players_total // 2, FACTIONS[1]: cfg.players_total - cfg.players_total // 2}
    control = {node.name: rng.choice(FACTIONS) for node in nodes}
    node_stock = {node.name: node.capacity for node in nodes}
    supply_stock = {FACTIONS[0]: cfg.players_total * 0.5, FACTIONS[1]: cfg.players_total * 0.5}
    wounded = {FACTIONS[0]: 0, FACTIONS[1]: 0}

    daily_rows = []
    node_rows = []
    control_rows = []

    total_capacity = sum(n.capacity for n in nodes)

    for day in range(1, cfg.days + 1):
        total_stock = sum(node_stock.values())
        hot = is_hot_phase(total_stock, total_capacity, cfg.hot_phase_threshold_total_stock_ratio)

        eff_players = {f: max(0, players_per_faction[f] - wounded[f]) for f in FACTIONS}

        # лидер/лузер по контролю узлов
        control_counts = {FACTIONS[0]: 0, FACTIONS[1]: 0}
        for node in nodes:
            control_counts[control[node.name]] += 1
        leader = FACTIONS[0] if control_counts[FACTIONS[0]] >= control_counts[FACTIONS[1]] else FACTIONS[1]
        loser = FACTIONS[1] if leader == FACTIONS[0] else FACTIONS[0]

        safe_income = {
            leader: cfg.safe_supply_per_player * eff_players[leader],
            loser: cfg.safe_supply_per_player * cfg.losing_safe_multiplier * eff_players[loser],
        }

        upkeep = {f: cfg.supply_upkeep_per_player * eff_players[f] for f in FACTIONS}

        miners = {f: int(round(cfg.miners_share * eff_players[f])) for f in FACTIONS}

        weights = []
        for node in nodes:
            stock_ratio = node_stock[node.name] / max(1e-6, node.capacity)
            w = node_value_weight(node, cfg) * (0.35 + 0.65 * stock_ratio)
            weights.append(w)
        weights = np.array(weights, dtype=float)
        weights = weights / weights.sum()

        allocation = {f: {node.name: 0 for node in nodes} for f in FACTIONS}
        for f in FACTIONS:
            counts = rng.multinomial(miners[f], weights)
            for i, node in enumerate(nodes):
                allocation[f][node.name] = int(counts[i])

        day_extracted = {FACTIONS[0]: 0.0, FACTIONS[1]: 0.0}
        day_lost_transport = {FACTIONS[0]: 0.0, FACTIONS[1]: 0.0}
        day_looted = {FACTIONS[0]: 0.0, FACTIONS[1]: 0.0}
        fights = 0
        casualties = {FACTIONS[0]: 0, FACTIONS[1]: 0}

        for node in nodes:
            nname = node.name
            node_stock[nname] = min(node.capacity, node_stock[nname] + node.regen)

            stock_ratio = node_stock[nname] / max(1e-6, node.capacity)
            yield_per_miner = node.base_yield * (0.25 + 0.75 * stock_ratio)

            want_a = allocation[FACTIONS[0]][nname]
            want_b = allocation[FACTIONS[1]][nname]
            total_want = want_a + want_b

            if total_want <= 0 or node_stock[nname] <= 0:
                node_rows.append({"day": day, "node": nname, "type": node.resource_type, "stock": node_stock[nname],
                                  "extracted_total": 0.0, "hot": hot})
                continue

            max_extractable = node_stock[nname]
            potential_total = total_want * yield_per_miner
            extracted_total = min(max_extractable, potential_total)

            extracted_a = extracted_total * (want_a / total_want) if total_want > 0 else 0.0
            extracted_b = extracted_total * (want_b / total_want) if total_want > 0 else 0.0

            p_fight = cfg.skirmish_base_prob * (cfg.hot_phase_multiplier if hot else 1.0)
            p_fight *= (0.65 + 0.70 * node.danger)
            p_fight = clamp01(p_fight)

            fight_happened = rng.random() < p_fight and (want_a > 0 and want_b > 0)

            if fight_happened:
                fights += 1
                fighters_a = max(1, int(round(cfg.contest_fraction * want_a)))
                fighters_b = max(1, int(round(cfg.contest_fraction * want_b)))

                supply_per_player_a = supply_stock[FACTIONS[0]] / max(1, eff_players[FACTIONS[0]])
                supply_per_player_b = supply_stock[FACTIONS[1]] / max(1, eff_players[FACTIONS[1]])

                strength_a = fighters_a * softcap_supply_factor(supply_per_player_a)
                strength_b = fighters_b * softcap_supply_factor(supply_per_player_b)

                winner_idx = choose_winner(strength_a, strength_b, cfg.randomness, rng)
                winner = FACTIONS[winner_idx]
                loser_f = FACTIONS[1 - winner_idx]

                loss = int(round(cfg.casualty_rate * (fighters_b if loser_f == FACTIONS[1] else fighters_a)))
                loss = max(0, loss)
                casualties[loser_f] += loss

                if winner == FACTIONS[0]:
                    loot = cfg.loot_share_on_win * extracted_b
                    extracted_b -= loot
                    extracted_a += loot
                    day_looted[FACTIONS[0]] += loot
                else:
                    loot = cfg.loot_share_on_win * extracted_a
                    extracted_a -= loot
                    extracted_b += loot
                    day_looted[FACTIONS[1]] += loot

                control[nname] = winner

                supply_stock[FACTIONS[0]] -= cfg.supply_cost_per_fighter * fighters_a
                supply_stock[FACTIONS[1]] -= cfg.supply_cost_per_fighter * fighters_b

            transport_loss_prob = cfg.transport_base_loss + cfg.transport_danger_loss * node.danger
            if hot:
                transport_loss_prob *= cfg.transport_hot_multiplier
            transport_loss_prob = clamp01(transport_loss_prob)

            lost_a = extracted_a * (transport_loss_prob * (0.6 + 0.8 * node.danger))
            lost_b = extracted_b * (transport_loss_prob * (0.6 + 0.8 * node.danger))
            extracted_a_after = max(0.0, extracted_a - lost_a)
            extracted_b_after = max(0.0, extracted_b - lost_b)

            day_lost_transport[FACTIONS[0]] += lost_a
            day_lost_transport[FACTIONS[1]] += lost_b

            node_stock[nname] = max(0.0, node_stock[nname] - extracted_total)

            if node.resource_type == "🪙 Gold":
                supply_gain_a = extracted_a_after * cfg.supply_from_gold
                supply_gain_b = extracted_b_after * cfg.supply_from_gold
            else:
                supply_gain_a = extracted_a_after * cfg.supply_from_crystal
                supply_gain_b = extracted_b_after * cfg.supply_from_crystal

            day_extracted[FACTIONS[0]] += extracted_a_after
            day_extracted[FACTIONS[1]] += extracted_b_after
            supply_stock[FACTIONS[0]] += supply_gain_a
            supply_stock[FACTIONS[1]] += supply_gain_b

            node_rows.append({"day": day, "node": nname, "type": node.resource_type, "stock": node_stock[nname],
                              "extracted_total": extracted_total, "hot": hot})

        for f in FACTIONS:
            supply_stock[f] += safe_income.get(f, 0.0)
            supply_stock[f] -= upkeep[f]
            supply_stock[f] = max(0.0, supply_stock[f])

        wounded = {f: casualties[f] for f in FACTIONS}

        control_counts = {FACTIONS[0]: 0, FACTIONS[1]: 0}
        for node in nodes:
            control_counts[control[node.name]] += 1
            control_rows.append({"day": day, "node": node.name, "controller": control[node.name]})

        daily_rows.append({
            "day": day,
            "hot": hot,
            "total_stock": sum(node_stock.values()),
            "total_capacity": total_capacity,
            "fights": fights,
            "blue_casualties": casualties[FACTIONS[0]],
            "red_casualties": casualties[FACTIONS[1]],
            "blue_extracted": day_extracted[FACTIONS[0]],
            "red_extracted": day_extracted[FACTIONS[1]],
            "blue_looted": day_looted[FACTIONS[0]],
            "red_looted": day_looted[FACTIONS[1]],
            "blue_lost_transport": day_lost_transport[FACTIONS[0]],
            "red_lost_transport": day_lost_transport[FACTIONS[1]],
            "blue_supply": supply_stock[FACTIONS[0]],
            "red_supply": supply_stock[FACTIONS[1]],
            "blue_nodes": control_counts[FACTIONS[0]],
            "red_nodes": control_counts[FACTIONS[1]],
        })

    return pd.DataFrame(daily_rows), pd.DataFrame(node_rows), pd.DataFrame(control_rows)


# -----------------------------
# 🎛️ Streamlit UI (фикс загрузки сценариев)
# -----------------------------

st.set_page_config(page_title="🧪 Sandbox Economy & PvP Simulator", layout="wide")
st.title("🧪 Sandbox симулятор: ресурсы → истощение → конфликт → снабжение")
st.caption("Загружай JSON-сценарии — все слайдеры и узлы обновятся сразу (через st.rerun()).")

DEFAULT_NODES = [
    NodeConfig("🏞️ Node A", "🪙 Gold", 20000, 600, 7.0, 0.35),
    NodeConfig("🏜️ Node B", "💎 Crystal", 14000, 450, 6.0, 0.55),
    NodeConfig("🌲 Node C", "🪙 Gold", 18000, 520, 6.5, 0.45),
    NodeConfig("⛰️ Node D", "💎 Crystal", 12000, 380, 5.5, 0.65),
    NodeConfig("🏝️ Node E", "🪙 Gold", 16000, 480, 6.2, 0.30),
]

DEFAULT_SIM = SimConfig(players_total=100, days=90)

# Ключи виджетов, чтобы их можно было обновлять из session_state при загрузке JSON
WIDGET_DEFAULTS = {
    "days": DEFAULT_SIM.days,
    "seed": 42,
    "scenario_name": "my_scenario",

    "safe_supply_per_player": DEFAULT_SIM.safe_supply_per_player,
    "losing_safe_multiplier": DEFAULT_SIM.losing_safe_multiplier,

    "supply_from_gold": DEFAULT_SIM.supply_from_gold,
    "supply_from_crystal": DEFAULT_SIM.supply_from_crystal,

    "supply_upkeep_per_player": DEFAULT_SIM.supply_upkeep_per_player,
    "supply_cost_per_fighter": DEFAULT_SIM.supply_cost_per_fighter,

    "skirmish_base_prob": DEFAULT_SIM.skirmish_base_prob,
    "hot_phase_multiplier": DEFAULT_SIM.hot_phase_multiplier,
    "hot_phase_threshold": DEFAULT_SIM.hot_phase_threshold_total_stock_ratio,
    "contest_fraction": DEFAULT_SIM.contest_fraction,
    "randomness": DEFAULT_SIM.randomness,
    "casualty_rate": DEFAULT_SIM.casualty_rate,
    "loot_share_on_win": DEFAULT_SIM.loot_share_on_win,

    "transport_base_loss": DEFAULT_SIM.transport_base_loss,
    "transport_danger_loss": DEFAULT_SIM.transport_danger_loss,
    "transport_hot_multiplier": DEFAULT_SIM.transport_hot_multiplier,

    "miners_share": DEFAULT_SIM.miners_share,
    "focus_weight_crystal": DEFAULT_SIM.focus_weight_crystal,
}

def ensure_defaults():
    for k, v in WIDGET_DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v
    if "nodes" not in st.session_state:
        st.session_state["nodes"] = [asdict(n) for n in DEFAULT_NODES]

ensure_defaults()

def apply_loaded_scenario(payload: Dict):
    """Обновляет session_state так, чтобы виджеты реально перерисовались."""
    if "name" in payload and isinstance(payload["name"], str):
        st.session_state["scenario_name"] = payload["name"]

    if "seed" in payload:
        try:
            st.session_state["seed"] = int(payload["seed"])
        except Exception:
            pass

    sim = payload.get("sim", {})
    if isinstance(sim, dict):
        mapping = {
            "days": "days",
            "safe_supply_per_player": "safe_supply_per_player",
            "losing_safe_multiplier": "losing_safe_multiplier",
            "supply_from_gold": "supply_from_gold",
            "supply_from_crystal": "supply_from_crystal",
            "supply_upkeep_per_player": "supply_upkeep_per_player",
            "supply_cost_per_fighter": "supply_cost_per_fighter",
            "skirmish_base_prob": "skirmish_base_prob",
            "hot_phase_multiplier": "hot_phase_multiplier",
            "hot_phase_threshold_total_stock_ratio": "hot_phase_threshold",
            "contest_fraction": "contest_fraction",
            "randomness": "randomness",
            "casualty_rate": "casualty_rate",
            "loot_share_on_win": "loot_share_on_win",
            "transport_base_loss": "transport_base_loss",
            "transport_danger_loss": "transport_danger_loss",
            "transport_hot_multiplier": "transport_hot_multiplier",
            "miners_share": "miners_share",
            "focus_weight_crystal": "focus_weight_crystal",
        }
        for src, dst in mapping.items():
            if src in sim:
                st.session_state[dst] = sim[src]

    nodes = payload.get("nodes")
    if isinstance(nodes, list) and len(nodes) == 5:
        # минимальная валидация полей
        cleaned = []
        for nd in nodes:
            if not isinstance(nd, dict):
                continue
            cleaned.append({
                "name": str(nd.get("name", "Node")),
                "resource_type": nd.get("resource_type", "🪙 Gold") if nd.get("resource_type") in STRATEGIC_TYPES else "🪙 Gold",
                "capacity": float(nd.get("capacity", 10000)),
                "regen": float(nd.get("regen", 300)),
                "base_yield": float(nd.get("base_yield", 6.0)),
                "danger": float(nd.get("danger", 0.4)),
            })
        if len(cleaned) == 5:
            st.session_state["nodes"] = cleaned


# --- Сценарии
st.sidebar.header("💾 Сценарии")
uploaded = st.sidebar.file_uploader("⬆️ Загрузить сценарий (JSON)", type=["json"],
                                    help="После загрузки все параметры и узлы обновятся автоматически.")

if uploaded is not None:
    try:
        loaded = json.loads(uploaded.read().decode("utf-8"))
        apply_loaded_scenario(loaded)
        st.sidebar.success("Сценарий применён ✅")
        st.rerun()
    except Exception as e:
        st.sidebar.error(f"Не удалось загрузить сценарий: {e}")

# --- Виджеты (ВАЖНО: у всех есть key=..., чтобы обновляться из session_state)
st.sidebar.subheader("🎛️ Симуляция")
st.sidebar.slider("📅 Дней симуляции", 10, 365, key="days",
                  help="Сколько дней симулируем (шаг = 1 день).")
st.sidebar.number_input("🎲 Seed (повторяемость)", min_value=0, max_value=10_000_000, step=1, key="seed",
                        help="Одинаковый seed даёт одинаковый результат при тех же параметрах.")
st.sidebar.text_input("🗂️ Имя сценария", key="scenario_name",
                      help="Имя для сохранения параметров в JSON.")

st.sidebar.subheader("🍞 Безопасное снабжение")
st.sidebar.slider("🍞 Safe supply / игрок / день", 0.0, 5.0, 0.05, key="safe_supply_per_player")
st.sidebar.slider("🛡️ Множитель для проигрывающих", 0.0, 1.0, 0.05, key="losing_safe_multiplier")

st.sidebar.subheader("⚙️ Конверсия в снабжение")
st.sidebar.slider("🪙 1 Gold -> supply", 0.0, 0.3, 0.005, key="supply_from_gold")
st.sidebar.slider("💎 1 Crystal -> supply", 0.0, 0.5, 0.01, key="supply_from_crystal")

st.sidebar.subheader("🧰 Расход снабжения")
st.sidebar.slider("🧰 Upkeep / игрок / день", 0.0, 0.5, 0.01, key="supply_upkeep_per_player")
st.sidebar.slider("⚔️ Cost / боец при стычке", 0.0, 1.0, 0.01, key="supply_cost_per_fighter")

st.sidebar.subheader("⚔️ PvP")
st.sidebar.slider("🎯 Базовая вероятность стычки/узел/день", 0.0, 1.0, 0.01, key="skirmish_base_prob")
st.sidebar.slider("🔥 Множитель вероятности в горячей фазе", 1.0, 5.0, 0.1, key="hot_phase_multiplier")
st.sidebar.slider("📉 Порог горячей фазы (доля запаса)", 0.05, 0.95, 0.02, key="hot_phase_threshold")
st.sidebar.slider("👊 Доля добытчиков, вступающих в бой", 0.1, 1.0, 0.05, key="contest_fraction")
st.sidebar.slider("🎲 Случайность исхода боя", 0.0, 0.8, 0.02, key="randomness")
st.sidebar.slider("🩸 Потери проигравшего (доля бойцов)", 0.0, 0.5, 0.01, key="casualty_rate")
st.sidebar.slider("🎒 Доля перехвата добычи победителем", 0.0, 0.9, 0.05, key="loot_share_on_win")

st.sidebar.subheader("🚚 Риск перевозки")
st.sidebar.slider("📦 Базовый риск потерь груза", 0.0, 0.2, 0.005, key="transport_base_loss")
st.sidebar.slider("☠️ Вклад опасности региона", 0.0, 0.8, 0.02, key="transport_danger_loss")
st.sidebar.slider("🔥 Множитель риска в горячей фазе", 1.0, 3.0, 0.05, key="transport_hot_multiplier")

st.sidebar.subheader("🧠 Поведение фракций")
st.sidebar.slider("⛏️ Доля игроков на добыче", 0.1, 0.9, 0.05, key="miners_share")
st.sidebar.slider("💎 Предпочтение кристаллов", 0.5, 3.0, 0.1, key="focus_weight_crystal")


def current_scenario_dict() -> Dict:
    return {
        "sim": {
            "players_total": 100,
            "days": int(st.session_state["days"]),
            "safe_supply_per_player": float(st.session_state["safe_supply_per_player"]),
            "losing_safe_multiplier": float(st.session_state["losing_safe_multiplier"]),
            "supply_from_gold": float(st.session_state["supply_from_gold"]),
            "supply_from_crystal": float(st.session_state["supply_from_crystal"]),
            "supply_upkeep_per_player": float(st.session_state["supply_upkeep_per_player"]),
            "supply_cost_per_fighter": float(st.session_state["supply_cost_per_fighter"]),
            "skirmish_base_prob": float(st.session_state["skirmish_base_prob"]),
            "hot_phase_multiplier": float(st.session_state["hot_phase_multiplier"]),
            "hot_phase_threshold_total_stock_ratio": float(st.session_state["hot_phase_threshold"]),
            "contest_fraction": float(st.session_state["contest_fraction"]),
            "randomness": float(st.session_state["randomness"]),
            "casualty_rate": float(st.session_state["casualty_rate"]),
            "loot_share_on_win": float(st.session_state["loot_share_on_win"]),
            "transport_base_loss": float(st.session_state["transport_base_loss"]),
            "transport_danger_loss": float(st.session_state["transport_danger_loss"]),
            "transport_hot_multiplier": float(st.session_state["transport_hot_multiplier"]),
            "miners_share": float(st.session_state["miners_share"]),
            "focus_weight_crystal": float(st.session_state["focus_weight_crystal"]),
        },
        "nodes": st.session_state["nodes"],
        "seed": int(st.session_state["seed"]),
        "name": st.session_state["scenario_name"],
    }


scenario_json = json.dumps(current_scenario_dict(), ensure_ascii=False, indent=2)
st.sidebar.download_button(
    "⬇️ Скачать сценарий (JSON)",
    data=scenario_json.encode("utf-8"),
    file_name=f"{st.session_state['scenario_name']}.json",
    mime="application/json",
    help="Скачай JSON, чтобы быстро переключаться между наборами параметров."
)

# --- Редактор узлов
st.subheader("🗺️ Ресурсные узлы (5 регионов)")
st.caption("После загрузки JSON узлы обновятся. Изменения в полях сохраняются в сценарий при скачивании.")

cols = st.columns(5)
new_nodes = []
for i, node_dict in enumerate(st.session_state["nodes"]):
    with cols[i]:
        st.markdown(f"### {node_dict.get('name', f'Node {i+1}')}")
        name = st.text_input("🏷️ Имя", value=node_dict.get("name", f"Node {i+1}"), key=f"node_name_{i}")
        rtype = st.selectbox("🧿 Тип", STRATEGIC_TYPES,
                             index=0 if node_dict.get("resource_type") == "🪙 Gold" else 1,
                             key=f"node_type_{i}")
        capacity = st.number_input("🧺 Ёмкость (max stock)", min_value=0.0,
                                   value=float(node_dict.get("capacity", 10000.0)),
                                   step=500.0, key=f"node_cap_{i}")
        regen = st.number_input("🌿 Реген/день", min_value=0.0,
                                value=float(node_dict.get("regen", 300.0)),
                                step=10.0, key=f"node_reg_{i}")
        base_yield = st.number_input("⛏️ Yield/добытчик/день", min_value=0.0,
                                     value=float(node_dict.get("base_yield", 6.0)),
                                     step=0.2, key=f"node_yield_{i}")
        danger = st.slider("☠️ Опасность", 0.0, 1.0,
                           float(node_dict.get("danger", 0.4)),
                           0.05, key=f"node_danger_{i}")

        new_nodes.append(asdict(NodeConfig(name, rtype, float(capacity), float(regen), float(base_yield), float(danger))))

st.session_state["nodes"] = new_nodes

st.divider()
run = st.button("▶️ Запустить симуляцию", type="primary")

if run:
    cfg = SimConfig(
        players_total=100,
        days=int(st.session_state["days"]),
        safe_supply_per_player=float(st.session_state["safe_supply_per_player"]),
        losing_safe_multiplier=float(st.session_state["losing_safe_multiplier"]),
        supply_from_gold=float(st.session_state["supply_from_gold"]),
        supply_from_crystal=float(st.session_state["supply_from_crystal"]),
        supply_upkeep_per_player=float(st.session_state["supply_upkeep_per_player"]),
        supply_cost_per_fighter=float(st.session_state["supply_cost_per_fighter"]),
        skirmish_base_prob=float(st.session_state["skirmish_base_prob"]),
        hot_phase_multiplier=float(st.session_state["hot_phase_multiplier"]),
        hot_phase_threshold_total_stock_ratio=float(st.session_state["hot_phase_threshold"]),
        contest_fraction=float(st.session_state["contest_fraction"]),
        randomness=float(st.session_state["randomness"]),
        casualty_rate=float(st.session_state["casualty_rate"]),
        loot_share_on_win=float(st.session_state["loot_share_on_win"]),
        transport_base_loss=float(st.session_state["transport_base_loss"]),
        transport_danger_loss=float(st.session_state["transport_danger_loss"]),
        transport_hot_multiplier=float(st.session_state["transport_hot_multiplier"]),
        miners_share=float(st.session_state["miners_share"]),
        focus_weight_crystal=float(st.session_state["focus_weight_crystal"]),
    )
    nodes = [NodeConfig(**d) for d in st.session_state["nodes"]]
    df_daily, df_nodes, df_control = simulate(cfg, nodes, seed=int(st.session_state["seed"]))

    left, right = st.columns([1.2, 1])

    with left:
        st.subheader("📈 Запасы ресурсов по узлам (stock)")
        fig = plt.figure()
        for node_name in df_nodes["node"].unique():
            s = df_nodes[df_nodes["node"] == node_name].set_index("day")["stock"]
            plt.plot(s.index, s.values, label=node_name)
        plt.xlabel("day")
        plt.ylabel("stock")
        plt.legend()
        st.pyplot(fig)

        st.subheader("📈 Добыча vs Потери (день)")
        fig2 = plt.figure()
        plt.plot(df_daily["day"], df_daily["blue_extracted"], label="🔵 добыча (после риска)")
        plt.plot(df_daily["day"], df_daily["red_extracted"], label="🔴 добыча (после риска)")
        plt.plot(df_daily["day"], df_daily["blue_lost_transport"], label="🔵 потери перевозки")
        plt.plot(df_daily["day"], df_daily["red_lost_transport"], label="🔴 потери перевозки")
        plt.xlabel("day")
        plt.ylabel("amount")
        plt.legend()
        st.pyplot(fig2)

    with right:
        st.subheader("🧭 Доли контроля узлов (по фракциям)")
        fig3 = plt.figure()
        plt.plot(df_daily["day"], df_daily["blue_nodes"] / 5.0, label="🔵 доля узлов")
        plt.plot(df_daily["day"], df_daily["red_nodes"] / 5.0, label="🔴 доля узлов")
        plt.xlabel("day")
        plt.ylabel("share")
        plt.ylim(0, 1)
        plt.legend()
        st.pyplot(fig3)

        st.subheader("⚔️ Интенсивность PvP")
        fig4 = plt.figure()
        plt.plot(df_daily["day"], df_daily["fights"], label="⚔️ бои/день")
        plt.plot(df_daily["day"], df_daily["blue_casualties"], label="🔵 потери (wounded)")
        plt.plot(df_daily["day"], df_daily["red_casualties"], label="🔴 потери (wounded)")
        plt.xlabel("day")
        plt.ylabel("count")
        plt.legend()
        st.pyplot(fig4)

    st.divider()
    st.subheader("⬇️ Экспорт результатов")
    st.download_button("💾 Скачать daily.csv", df_daily.to_csv(index=False).encode("utf-8"), "daily.csv", "text/csv")
    st.download_button("💾 Скачать nodes.csv", df_nodes.to_csv(index=False).encode("utf-8"), "nodes.csv", "text/csv")
    st.download_button("💾 Скачать control.csv", df_control.to_csv(index=False).encode("utf-8"), "control.csv", "text/csv")
else:
    st.info("Загрузи сценарий или настрой параметры и нажми ▶️ Запустить симуляцию.")
