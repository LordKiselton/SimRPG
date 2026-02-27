import json
import math
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt


# -----------------------------
# 🧩 Модель (простая, расширяемая)
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
    miners_share: float = 0.55  # доля игроков, которых фракция пытается держать "на добыче" (остальные условно охрана/логистика)
    focus_weight_crystal: float = 1.0  # предпочтение кристаллов (если >1, будут сильнее фокусить кристалл)


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def softcap_supply_factor(supply_per_player: float) -> float:
    """
    Преобразует снабжение/игрока в множитель силы.
    Интуиция:
      0.0 supply -> 0.6 силы (дерутся плохо)
      1.0 supply -> 1.0 силы (норма)
      2.0 supply -> 1.15 силы (плато)
    """
    # логистическая кривая, гладкая и понятная
    return 0.6 + 0.65 * (1 - math.exp(-1.2 * supply_per_player))


def choose_winner(strength_a: float, strength_b: float, randomness: float, rng: np.random.Generator) -> int:
    """
    Возвращает 0 если выиграл A, 1 если выиграл B.
    """
    # добавим шум к силам, чтобы не было "вечного доминирования"
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
    """
    Простейшая "ценность узла" для распределения добытчиков.
    """
    base = 1.0
    if node.resource_type == "💎 Crystal":
        base *= cfg.focus_weight_crystal
    # опасные узлы немного менее привлекательны, но не запрещены
    base *= (1.0 - 0.25 * node.danger)
    return max(0.1, base)


def simulate(cfg: SimConfig, nodes: List[NodeConfig], seed: int = 42) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)

    players_per_faction = {FACTIONS[0]: cfg.players_total // 2, FACTIONS[1]: cfg.players_total - cfg.players_total // 2}

    # контроль узлов: старт — равномерно (с лёгкой случайностью)
    control = {node.name: rng.choice(FACTIONS) for node in nodes}

    # запасы узлов
    node_stock = {node.name: node.capacity for node in nodes}

    # снабжение фракций (в условных единицах)
    supply_stock = {FACTIONS[0]: cfg.players_total * 0.5, FACTIONS[1]: cfg.players_total * 0.5}

    # выведенные из строя (потери в PvP) — возвращаются на следующий день (упрощение)
    wounded = {FACTIONS[0]: 0, FACTIONS[1]: 0}

    # трекинг результатов
    daily_rows = []
    node_rows = []
    control_rows = []

    total_capacity = sum(n.capacity for n in nodes)

    for day in range(1, cfg.days + 1):
        # 1) Определяем горячую фазу (по суммарному запасу)
        total_stock = sum(node_stock.values())
        hot = is_hot_phase(total_stock, total_capacity, cfg.hot_phase_threshold_total_stock_ratio)

        # 2) Эффективная численность (без выведенных из строя)
        eff_players = {
            f: max(0, players_per_faction[f] - wounded[f])
            for f in FACTIONS
        }

        # 3) Базовое снабжение из безопасных источников:
        #    проигрывающей стороне дадим 20% safe income — но кто "проигрывает"?
        #    Возьмём простой критерий: у кого меньше контроля узлов на текущий день.
        control_counts = {FACTIONS[0]: 0, FACTIONS[1]: 0}
        for node in nodes:
            control_counts[control[node.name]] += 1
        leader = FACTIONS[0] if control_counts[FACTIONS[0]] >= control_counts[FACTIONS[1]] else FACTIONS[1]
        loser = FACTIONS[1] if leader == FACTIONS[0] else FACTIONS[0]

        safe_income = {
            leader: cfg.safe_supply_per_player * eff_players[leader],
            loser: cfg.safe_supply_per_player * cfg.losing_safe_multiplier * eff_players[loser],
        }

        # 4) Ежедневный upkeep снабжения
        upkeep = {f: cfg.supply_upkeep_per_player * eff_players[f] for f in FACTIONS}

        # 5) Распределение добытчиков по узлам (наивная стратегия):
        #    каждая фракция направляет miners_share от доступных игроков на добычу,
        #    с весами по "ценности" узлов и текущему запасу узла.
        miners = {f: int(round(cfg.miners_share * eff_players[f])) for f in FACTIONS}

        # веса узлов с учетом типа и опасности + запасности
        weights = []
        for node in nodes:
            stock_ratio = node_stock[node.name] / max(1e-6, node.capacity)
            w = node_value_weight(node, cfg) * (0.35 + 0.65 * stock_ratio)
            weights.append(w)
        weights = np.array(weights, dtype=float)
        weights = weights / weights.sum()

        allocation = {f: {node.name: 0 for node in nodes} for f in FACTIONS}
        for f in FACTIONS:
            # мультиномиал — распределяем miners[f] по узлам
            counts = rng.multinomial(miners[f], weights)
            for i, node in enumerate(nodes):
                allocation[f][node.name] = int(counts[i])

        # 6) Добыча + перевозка + стычки
        day_extracted = {FACTIONS[0]: 0.0, FACTIONS[1]: 0.0}
        day_lost_transport = {FACTIONS[0]: 0.0, FACTIONS[1]: 0.0}
        day_looted = {FACTIONS[0]: 0.0, FACTIONS[1]: 0.0}
        fights = 0
        casualties = {FACTIONS[0]: 0, FACTIONS[1]: 0}

        for node in nodes:
            nname = node.name
            # реген узла
            node_stock[nname] = min(node.capacity, node_stock[nname] + node.regen)

            # потенциальная добыча обеих сторон
            # добыча зависит от текущего запаса (если узел почти пуст, добыча хуже)
            stock_ratio = node_stock[nname] / max(1e-6, node.capacity)
            yield_per_miner = node.base_yield * (0.25 + 0.75 * stock_ratio)

            want_a = allocation[FACTIONS[0]][nname]
            want_b = allocation[FACTIONS[1]][nname]
            total_want = want_a + want_b

            if total_want <= 0 or node_stock[nname] <= 0:
                # логируем узел
                node_rows.append({
                    "day": day,
                    "node": nname,
                    "type": node.resource_type,
                    "stock": node_stock[nname],
                    "extracted_total": 0.0,
                    "hot": hot,
                })
                continue

            # ограничение по запасу
            max_extractable = node_stock[nname]
            potential_total = total_want * yield_per_miner
            extracted_total = min(max_extractable, potential_total)

            # делим добычу пропорционально майнерам
            extracted_a = extracted_total * (want_a / total_want) if total_want > 0 else 0.0
            extracted_b = extracted_total * (want_b / total_want) if total_want > 0 else 0.0

            # 6.1) Стычка?
            p_fight = cfg.skirmish_base_prob * (cfg.hot_phase_multiplier if hot else 1.0)
            p_fight *= (0.65 + 0.70 * node.danger)  # опасные регионы чаще конфликтные
            p_fight = clamp01(p_fight)

            fight_happened = rng.random() < p_fight and (want_a > 0 and want_b > 0)

            # расход снабжения на бойцов, если бой случился
            if fight_happened:
                fights += 1

                # сколько бойцов "вступает в стычку"
                fighters_a = max(1, int(round(cfg.contest_fraction * want_a)))
                fighters_b = max(1, int(round(cfg.contest_fraction * want_b)))

                # снабжение на игрока
                supply_per_player_a = supply_stock[FACTIONS[0]] / max(1, eff_players[FACTIONS[0]])
                supply_per_player_b = supply_stock[FACTIONS[1]] / max(1, eff_players[FACTIONS[1]])

                strength_a = fighters_a * softcap_supply_factor(supply_per_player_a)
                strength_b = fighters_b * softcap_supply_factor(supply_per_player_b)

                winner_idx = choose_winner(strength_a, strength_b, cfg.randomness, rng)
                winner = FACTIONS[winner_idx]
                loser_f = FACTIONS[1 - winner_idx]

                # потери у проигравшего (выведены из строя на 1 день)
                loss = int(round(cfg.casualty_rate * (fighters_b if loser_f == FACTIONS[1] else fighters_a)))
                loss = max(0, loss)
                casualties[loser_f] += loss

                # победитель может перехватить долю добычи проигравшего (loot)
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

                # контроль узла переходит победителю с небольшой вероятностью (или если он не контролил)
                # проще: победитель становится контролирующим, если бой произошёл
                control[nname] = winner

                # расход снабжения на бойцов
                supply_stock[FACTIONS[0]] -= cfg.supply_cost_per_fighter * fighters_a
                supply_stock[FACTIONS[1]] -= cfg.supply_cost_per_fighter * fighters_b

            # 6.2) Транспортные потери (зависят от danger и hot)
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

            # 6.3) Списываем добычу из запаса узла
            node_stock[nname] = max(0.0, node_stock[nname] - extracted_total)

            # 6.4) Конвертируем добычу в снабжение (ресурс => снабжение)
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

            # Лог узла
            node_rows.append({
                "day": day,
                "node": nname,
                "type": node.resource_type,
                "stock": node_stock[nname],
                "extracted_total": extracted_total,
                "hot": hot,
            })

        # 7) Применяем safe income и upkeep (в конце дня)
        for f in FACTIONS:
            supply_stock[f] += safe_income.get(f, 0.0)
            supply_stock[f] -= upkeep[f]
            supply_stock[f] = max(0.0, supply_stock[f])

        # 8) Применяем потери (wounded на следующий день)
        wounded = {f: casualties[f] for f in FACTIONS}

        # 9) Лог контроля (доли узлов)
        control_counts = {FACTIONS[0]: 0, FACTIONS[1]: 0}
        for node in nodes:
            control_counts[control[node.name]] += 1
            control_rows.append({
                "day": day,
                "node": node.name,
                "controller": control[node.name],
            })

        # 10) Дневной лог
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

    df_daily = pd.DataFrame(daily_rows)
    df_nodes = pd.DataFrame(node_rows)
    df_control = pd.DataFrame(control_rows)
    return df_daily, df_nodes, df_control


# -----------------------------
# 🎛️ Streamlit UI
# -----------------------------

st.set_page_config(page_title="🧪 Sandbox Economy & PvP Simulator", layout="wide")

st.title("🧪 Sandbox симулятор: ресурсы → истощение → конфликт → снабжение")
st.caption("Поворачиваем ручки параметров, симулируем N дней, смотрим графики и ищем устойчивую динамику.")

with st.expander("ℹ️ Как читать модель (коротко)"):
    st.markdown(
        """
- 🍞 **Безопасное снабжение** приходит каждый день всем (проигрывающим — 20%).
- 🪙/💎 **Стратегические узлы** имеют запас, который **истощается**, и **реген**.
- Фракции распределяют добытчиков по узлам, добыча конвертируется в **снабжение**.
- ⚔️ На узлах случаются **ежедневные стычки с вероятностью**, сила = бойцы × снабжение.
- 🚚 Перевозка имеет риск потерь, который растёт с **опасностью региона** и в **горячей фазе**.
- 🔥 **Горячая фаза** включается, когда суммарный запас узлов падает ниже порога.
        """
    )

# --- Сайдбар параметров
st.sidebar.header("🎛️ Параметры симуляции")

days = st.sidebar.slider("📅 Дней симуляции", 10, 365, 90, help="Сколько дней симулируем (шаг = 1 день).")
seed = st.sidebar.number_input("🎲 Seed (повторяемость)", min_value=0, max_value=10_000_000, value=42, step=1,
                               help="Одинаковый seed даёт одинаковый результат при тех же параметрах.")

st.sidebar.subheader("🍞 Безопасное снабжение")
safe_supply_per_player = st.sidebar.slider("🍞 Safe supply / игрок / день", 0.0, 5.0, 1.0, 0.05,
                                           help="Сколько снабжения каждый игрок получает из безопасных источников (еда/дерево/камень).")
losing_safe_multiplier = st.sidebar.slider("🛡️ Множитель для проигрывающих", 0.0, 1.0, 0.2, 0.05,
                                           help="Проигрывающие получают safe_supply * множитель. По ТЗ: 0.2 (20%).")

st.sidebar.subheader("⚙️ Конверсия в снабжение")
supply_from_gold = st.sidebar.slider("🪙 1 Gold -> supply", 0.0, 0.3, 0.05, 0.005,
                                     help="Сколько снабжения даёт 1 золота (после потерь перевозки).")
supply_from_crystal = st.sidebar.slider("💎 1 Crystal -> supply", 0.0, 0.5, 0.12, 0.01,
                                        help="Сколько снабжения даёт 1 кристалла (обычно ценнее золота).")

st.sidebar.subheader("🧰 Расход снабжения")
supply_upkeep_per_player = st.sidebar.slider("🧰 Upkeep / игрок / день", 0.0, 0.5, 0.10, 0.01,
                                             help="Ежедневное 'содержание' игроков. Если слишком высоко — экономика стагнирует.")
supply_cost_per_fighter = st.sidebar.slider("⚔️ Cost / боец при стычке", 0.0, 1.0, 0.20, 0.01,
                                            help="Доп. расход снабжения на участника боя (если бой произошёл).")

st.sidebar.subheader("⚔️ PvP")
skirmish_base_prob = st.sidebar.slider("🎯 Базовая вероятность стычки/узел/день", 0.0, 1.0, 0.25, 0.01,
                                       help="Вероятность боя на узле в день (умножается в горячей фазе и растёт с опасностью узла).")
hot_phase_multiplier = st.sidebar.slider("🔥 Множитель вероятности в горячей фазе", 1.0, 5.0, 1.6, 0.1,
                                         help="Насколько чаще происходят бои, когда ресурсы истощены.")
hot_phase_threshold = st.sidebar.slider("📉 Порог горячей фазы (доля запаса)", 0.05, 0.95, 0.35, 0.02,
                                       help="Горячая фаза включается, когда суммарный запас узлов / суммарная ёмкость < порога.")
contest_fraction = st.sidebar.slider("👊 Доля добытчиков, вступающих в бой", 0.1, 1.0, 0.60, 0.05,
                                     help="Если бой случился, какая доля добытчиков на узле реально дерётся.")
randomness = st.sidebar.slider("🎲 Случайность исхода боя", 0.0, 0.8, 0.20, 0.02,
                               help="Шум в силе. Нужен для камбэков и чтобы мета не 'застывала'.")
casualty_rate = st.sidebar.slider("🩸 Потери проигравшего (доля бойцов)", 0.0, 0.5, 0.08, 0.01,
                                  help="Доля бойцов проигравшей стороны, выведенных из строя на следующий день.")
loot_share_on_win = st.sidebar.slider("🎒 Доля перехвата добычи победителем", 0.0, 0.9, 0.35, 0.05,
                                      help="Сколько добычи проигравшей стороны перехватывает победитель.")

st.sidebar.subheader("🚚 Риск перевозки")
transport_base_loss = st.sidebar.slider("📦 Базовый риск потерь груза", 0.0, 0.2, 0.02, 0.005,
                                        help="Минимальный риск потерь даже в спокойных регионах.")
transport_danger_loss = st.sidebar.slider("☠️ Вклад опасности региона", 0.0, 0.8, 0.20, 0.02,
                                          help="Насколько danger узла добавляет к риску потерь груза.")
transport_hot_multiplier = st.sidebar.slider("🔥 Множитель риска в горячей фазе", 1.0, 3.0, 1.3, 0.05,
                                             help="В горячей фазе перевозка опаснее (больше засад, рейдов).")

st.sidebar.subheader("🧠 Поведение фракций")
miners_share = st.sidebar.slider("⛏️ Доля игроков на добыче", 0.1, 0.9, 0.55, 0.05,
                                 help="Сколько игроков фракция в среднем отправляет добывать (остальные условно охрана/логистика).")
focus_weight_crystal = st.sidebar.slider("💎 Предпочтение кристаллов", 0.5, 3.0, 1.0, 0.1,
                                         help=">1 означает, что фракции сильнее фокусируются на узлах с кристаллами.")

# --- Конфиг узлов
st.subheader("🗺️ Ресурсные узлы (5 регионов)")
st.caption("Каждый узел: тип (🪙/💎), ёмкость запаса, реген/день, добыча на добытчика, опасность региона.")

default_nodes = [
    NodeConfig("🏞️ Node A", "🪙 Gold", 20000, 600, 7.0, 0.35),
    NodeConfig("🏜️ Node B", "💎 Crystal", 14000, 450, 6.0, 0.55),
    NodeConfig("🌲 Node C", "🪙 Gold", 18000, 520, 6.5, 0.45),
    NodeConfig("⛰️ Node D", "💎 Crystal", 12000, 380, 5.5, 0.65),
    NodeConfig("🏝️ Node E", "🪙 Gold", 16000, 480, 6.2, 0.30),
]

if "nodes" not in st.session_state:
    st.session_state["nodes"] = [asdict(n) for n in default_nodes]

# --- Сохранение/загрузка сценариев
st.sidebar.header("💾 Сценарии")
scenario_name = st.sidebar.text_input("🗂️ Имя сценария", value="my_scenario", help="Имя для сохранения параметров в JSON.")

def current_scenario_dict() -> Dict:
    return {
        "sim": {
            "players_total": 100,  # фиксировано по ТЗ
            "days": int(days),
            "safe_supply_per_player": float(safe_supply_per_player),
            "losing_safe_multiplier": float(losing_safe_multiplier),
            "supply_from_gold": float(supply_from_gold),
            "supply_from_crystal": float(supply_from_crystal),
            "supply_upkeep_per_player": float(supply_upkeep_per_player),
            "supply_cost_per_fighter": float(supply_cost_per_fighter),
            "skirmish_base_prob": float(skirmish_base_prob),
            "hot_phase_multiplier": float(hot_phase_multiplier),
            "hot_phase_threshold_total_stock_ratio": float(hot_phase_threshold),
            "contest_fraction": float(contest_fraction),
            "randomness": float(randomness),
            "casualty_rate": float(casualty_rate),
            "loot_share_on_win": float(loot_share_on_win),
            "transport_base_loss": float(transport_base_loss),
            "transport_danger_loss": float(transport_danger_loss),
            "transport_hot_multiplier": float(transport_hot_multiplier),
            "miners_share": float(miners_share),
            "focus_weight_crystal": float(focus_weight_crystal),
        },
        "nodes": st.session_state["nodes"],
        "seed": int(seed),
        "name": scenario_name,
    }

scenario_json = json.dumps(current_scenario_dict(), ensure_ascii=False, indent=2)
st.sidebar.download_button(
    "⬇️ Скачать сценарий (JSON)",
    data=scenario_json.encode("utf-8"),
    file_name=f"{scenario_name}.json",
    mime="application/json",
    help="Скачай JSON, чтобы быстро переключаться между наборами параметров."
)

uploaded = st.sidebar.file_uploader("⬆️ Загрузить сценарий (JSON)", type=["json"], help="Загрузи ранее сохранённый сценарий.")
if uploaded is not None:
    try:
        loaded = json.loads(uploaded.read().decode("utf-8"))
        if "nodes" in loaded:
            st.session_state["nodes"] = loaded["nodes"]
        if "sim" in loaded:
            s = loaded["sim"]
            # Мы не делаем авто-перезапись всех виджетов (Streamlit ограничение),
            # но загрузка узлов уже сильно помогает.
        if "seed" in loaded:
            st.sidebar.info("Seed загружен из сценария (введи вручную, если хочешь точно воспроизвести).")
        st.sidebar.success("Сценарий загружен ✅ (узлы обновлены).")
    except Exception as e:
        st.sidebar.error(f"Не удалось загрузить сценарий: {e}")

# --- Редактор узлов
cols = st.columns(5)
new_nodes = []
for i, node_dict in enumerate(st.session_state["nodes"]):
    with cols[i]:
        st.markdown(f"### {node_dict.get('name', f'Node {i+1}')}")
        name = st.text_input("🏷️ Имя", value=node_dict.get("name", f"Node {i+1}"), key=f"node_name_{i}")
        rtype = st.selectbox("🧿 Тип", STRATEGIC_TYPES,
                             index=0 if node_dict.get("resource_type") == "🪙 Gold" else 1,
                             key=f"node_type_{i}",
                             help="Золото и кристаллы конвертируются в снабжение с разной эффективностью.")
        capacity = st.number_input("🧺 Ёмкость (max stock)", min_value=0.0, value=float(node_dict.get("capacity", 10000.0)),
                                   step=500.0, key=f"node_cap_{i}", help="Максимальный запас ресурса в узле.")
        regen = st.number_input("🌿 Реген/день", min_value=0.0, value=float(node_dict.get("regen", 300.0)),
                                step=10.0, key=f"node_reg_{i}", help="Сколько ресурса восстанавливается ежедневно.")
        base_yield = st.number_input("⛏️ Yield/добытчик/день", min_value=0.0, value=float(node_dict.get("base_yield", 6.0)),
                                     step=0.2, key=f"node_yield_{i}",
                                     help="Базовая добыча на 1 добытчика. При пустеющем узле эффективность падает.")
        danger = st.slider("☠️ Опасность", 0.0, 1.0, float(node_dict.get("danger", 0.4)), 0.05,
                           key=f"node_danger_{i}",
                           help="Влияет на риск перевозки и вероятность стычек.")

        new_nodes.append(asdict(NodeConfig(name, rtype, float(capacity), float(regen), float(base_yield), float(danger))))

st.session_state["nodes"] = new_nodes

# --- Запуск
st.divider()
run = st.button("▶️ Запустить симуляцию", type="primary", help="Запустит симуляцию на выбранное число дней и построит графики.")

if run:
    cfg = SimConfig(
        players_total=100,
        days=int(days),
        safe_supply_per_player=float(safe_supply_per_player),
        losing_safe_multiplier=float(losing_safe_multiplier),
        supply_from_gold=float(supply_from_gold),
        supply_from_crystal=float(supply_from_crystal),
        supply_upkeep_per_player=float(supply_upkeep_per_player),
        supply_cost_per_fighter=float(supply_cost_per_fighter),
        skirmish_base_prob=float(skirmish_base_prob),
        hot_phase_multiplier=float(hot_phase_multiplier),
        hot_phase_threshold_total_stock_ratio=float(hot_phase_threshold),
        contest_fraction=float(contest_fraction),
        randomness=float(randomness),
        casualty_rate=float(casualty_rate),
        loot_share_on_win=float(loot_share_on_win),
        transport_base_loss=float(transport_base_loss),
        transport_danger_loss=float(transport_danger_loss),
        transport_hot_multiplier=float(transport_hot_multiplier),
        miners_share=float(miners_share),
        focus_weight_crystal=float(focus_weight_crystal),
    )
    nodes = [NodeConfig(**d) for d in st.session_state["nodes"]]

    df_daily, df_nodes, df_control = simulate(cfg, nodes, seed=int(seed))

    # -----------------------------
    # 📊 Графики
    # -----------------------------
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

        st.subheader("🧰 Снабжение фракций (supply stock)")
        fig5 = plt.figure()
        plt.plot(df_daily["day"], df_daily["blue_supply"], label="🔵 supply")
        plt.plot(df_daily["day"], df_daily["red_supply"], label="🔴 supply")
        plt.xlabel("day")
        plt.ylabel("supply")
        plt.legend()
        st.pyplot(fig5)

    st.divider()
    st.subheader("🧾 Таблицы (для быстрой диагностики)")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**📌 Daily summary (последние 15 дней)**")
        st.dataframe(df_daily.tail(15), use_container_width=True)
    with c2:
        st.markdown("**📌 Node stock snapshot (последний день)**")
        last_day = df_nodes["day"].max()
        st.dataframe(df_nodes[df_nodes["day"] == last_day][["node", "type", "stock", "extracted_total", "hot"]],
                     use_container_width=True)

    st.divider()
    st.subheader("⬇️ Экспорт результатов")
    st.download_button("💾 Скачать daily.csv", df_daily.to_csv(index=False).encode("utf-8"), "daily.csv", "text/csv")
    st.download_button("💾 Скачать nodes.csv", df_nodes.to_csv(index=False).encode("utf-8"), "nodes.csv", "text/csv")
    st.download_button("💾 Скачать control.csv", df_control.to_csv(index=False).encode("utf-8"), "control.csv", "text/csv")

    # -----------------------------
    # 🧠 Быстрые подсказки (диагностика)
    # -----------------------------
    st.divider()
    st.subheader("🧠 Авто-диагностика (подсказки)")
    tips = []

    # 1) если боёв мало
    avg_fights = df_daily["fights"].mean()
    if avg_fights < 0.6:
        tips.append("⚠️ **Конфликт слабый**: среднее боёв/день низкое. Подними 🎯 вероятность стычек или усили горячую фазу.")
    elif avg_fights > 3.0:
        tips.append("⚠️ **Конфликт слишком частый**: боёв/день много. Возможно, игроки не успевают восстанавливаться/добывать.")

    # 2) если снабжение падает в ноль
    if (df_daily["blue_supply"].min() <= 1e-6) or (df_daily["red_supply"].min() <= 1e-6):
        tips.append("⚠️ **Коллапс снабжения**: одна из сторон уходит в 0 supply. Снизь upkeep/боевые расходы или увеличь safe supply/конверсию.")

    # 3) если контроль одной стороны почти всегда
    dominance = (df_daily["blue_nodes"] >= 4).mean() or (df_daily["red_nodes"] >= 4).mean()
    if dominance > 0.6:
        tips.append("⚠️ **Снежный ком контроля**: одна сторона часто держит ≥80% узлов. Увеличь случайность, потери перевозки или цену удержания (в этой модели — через upkeep/бой).")

    # 4) если узлы часто полностью пустые
    empty_ratio = (df_nodes["stock"] <= 0.01 * df_nodes.groupby("node")["stock"].transform("max")).mean()
    if empty_ratio > 0.35:
        tips.append("⚠️ **Частое опустошение узлов**: реген низкий/добыча высокая. Подними 🌿 regen или ёмкость, либо понизь yield.")

    if not tips:
        tips.append("✅ Динамика выглядит **живой и устойчивой** по базовым сигналам. Теперь можно точечно крутить 'ритм войны' и риск логистики.")

    for t in tips:
        st.markdown(t)

else:
    st.info("Настрой параметры и нажми **▶️ Запустить симуляцию**.")
