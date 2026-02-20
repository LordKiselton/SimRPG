# app.py
# Run:
#   pip install streamlit pandas
#   streamlit run app.py
#
# Optional (for easy tuning):
#   Create a file "factions.csv" рядом с app.py:
#     name,power,stability,radicalization,resources
#     Merchants,60,70,20,75
#     Temple,55,65,40,55
#     Mages,45,50,30,50
#     Lodge,30,60,20,40
#     Council,35,50,25,45

from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st


# -----------------------------
# Data model
# -----------------------------

@dataclass
class Faction:
    name: str
    power: int
    stability: int
    radicalization: int
    resources: int
    rel_player: int = 0

    def clamp(self):
        self.power = int(max(0, min(100, self.power)))
        self.stability = int(max(0, min(100, self.stability)))
        self.radicalization = int(max(0, min(100, self.radicalization)))
        self.resources = int(max(0, min(100, self.resources)))
        self.rel_player = int(max(-100, min(100, self.rel_player)))


@dataclass
class World:
    seed: int = 42
    day: int = 1
    max_days: int = 7

    economic_stress: int = 40
    public_fear: int = 30
    magical_tension: int = 50

    factions: Dict[str, Faction] = field(default_factory=dict)
    log: List[str] = field(default_factory=list)

    crisis_truth: str = "unknown"  # lodge/mages/merchants/accident

    def rng(self) -> random.Random:
        return random.Random(self.seed + self.day * 999)

    def clamp(self):
        self.economic_stress = int(max(0, min(100, self.economic_stress)))
        self.public_fear = int(max(0, min(100, self.public_fear)))
        self.magical_tension = int(max(0, min(100, self.magical_tension)))
        for f in self.factions.values():
            f.clamp()


# -----------------------------
# Load/save parameters
# -----------------------------

DEFAULT_FACTIONS = pd.DataFrame(
    [
        {"name": "Merchants", "power": 60, "stability": 70, "radicalization": 20, "resources": 75},
        {"name": "Temple",    "power": 55, "stability": 65, "radicalization": 40, "resources": 55},
        {"name": "Mages",     "power": 45, "stability": 50, "radicalization": 30, "resources": 50},
        {"name": "Lodge",     "power": 30, "stability": 60, "radicalization": 20, "resources": 40},
        {"name": "Council",   "power": 35, "stability": 50, "radicalization": 25, "resources": 45},
    ]
)

CSV_PATH = "factions.csv"


def load_factions_df() -> pd.DataFrame:
    if os.path.exists(CSV_PATH):
        df = pd.read_csv(CSV_PATH)
        # Normalize columns
        cols = ["name", "power", "stability", "radicalization", "resources"]
        for c in cols:
            if c not in df.columns:
                raise ValueError(f"Missing column '{c}' in {CSV_PATH}")
        df = df[cols].copy()
        return df
    return DEFAULT_FACTIONS.copy()


def save_factions_df(df: pd.DataFrame):
    df.to_csv(CSV_PATH, index=False)


def df_to_factions(df: pd.DataFrame) -> Dict[str, Faction]:
    factions: Dict[str, Faction] = {}
    for _, row in df.iterrows():
        f = Faction(
            name=str(row["name"]),
            power=int(row["power"]),
            stability=int(row["stability"]),
            radicalization=int(row["radicalization"]),
            resources=int(row["resources"]),
        )
        f.clamp()
        factions[f.name] = f
    return factions


# -----------------------------
# World init / step
# -----------------------------

PLAYER_ACTIONS = [
    "investigate",
    "support_temple",
    "support_mages",
    "support_merchants",
    "spread_rumour",
    "bribe",
]


def init_world_from_df(df: pd.DataFrame, seed: int, max_days: int) -> World:
    w = World(seed=seed, max_days=max_days)
    w.factions = df_to_factions(df)

    r = random.Random(seed)
    w.crisis_truth = r.choices(
        ["lodge", "mages", "merchants", "accident"],
        weights=[30, 30, 20, 20],
        k=1
    )[0]

    w.log = []
    w.day = 1

    # Day 1 trigger
    w.log.append("Day 1: A ship carrying Astral Coal has vanished. Prices surge; rumours spread.")
    w.economic_stress = 40 + 20
    w.public_fear = 30 + 15
    if "Mages" in w.factions:
        w.factions["Mages"].stability -= 10
    w.clamp()
    return w


def compute_effective_power(f: Faction) -> int:
    return int((f.resources * 0.5 + f.power * 0.5) * (0.5 + f.stability / 200.0))


def faction_intent(w: World, f: Faction) -> str:
    # Simple heuristics (cheap + understandable)
    if w.economic_stress > 70 and f.name == "Merchants":
        return "law"
    if w.magical_tension > 70 and f.name == "Temple":
        return "propaganda"
    if f.stability < 35 and f.name == "Mages":
        return "aid"
    if w.public_fear > 70 and f.name in ("Lodge", "Temple"):
        return "sabotage"
    return "propaganda"


def apply_player_action(w: World, action: str) -> str:
    rng = w.rng()

    if action == "investigate":
        w.public_fear -= 4
        if w.crisis_truth == "lodge" and "Lodge" in w.factions:
            w.factions["Lodge"].stability -= 6
            return "You investigate the docks. Evidence points to the Lodge (Lodge -6 Stability)."
        if w.crisis_truth == "mages" and "Mages" in w.factions:
            w.factions["Mages"].stability -= 4
            w.magical_tension += 6
            return "You uncover arcane traces. Suspicion shifts to the Mages (Magical Tension +6)."
        if w.crisis_truth == "merchants" and "Merchants" in w.factions:
            w.factions["Merchants"].power -= 4
            w.factions["Merchants"].resources -= 6
            return "You find suspicious ledgers. The Guild's story cracks (Merchants -4 Power, -6 Resources)."
        w.economic_stress -= 3
        return "You confirm it was a tragic accident. The city breathes a little easier (Economic Stress -3)."

    if action == "support_temple" and "Temple" in w.factions and "Mages" in w.factions:
        w.factions["Temple"].power += 6
        w.magical_tension += 5
        w.factions["Mages"].stability -= 3
        return "You back the Temple publicly (Temple +6 Power, Magical Tension +5)."

    if action == "support_mages" and "Mages" in w.factions and "Temple" in w.factions:
        w.factions["Mages"].stability += 6
        w.magical_tension -= 4
        w.factions["Temple"].radicalization += 4
        return "You protect the Mages from accusations (Mages +6 Stability, Magical Tension -4)."

    if action == "support_merchants" and "Merchants" in w.factions and "Council" in w.factions:
        w.factions["Merchants"].resources += 6
        w.economic_stress -= 5
        w.factions["Council"].power -= 2
        return "You help the Merchants restore supply lines (Economic Stress -5, Merchants +6 Resources)."

    if action == "spread_rumour":
        target = rng.choice(list(w.factions.values()))
        target.power -= 4
        w.public_fear += 3
        return f"You spread a rumour against {target.name} ({target.name} -4 Power, Public Fear +3)."

    if action == "bribe":
        target = rng.choice(list(w.factions.values()))
        target.rel_player += 8
        target.resources -= 3
        return f"You bribe intermediaries close to {target.name} ({target.name} +8 Player Relations)."

    return "You do nothing."


def apply_faction_action(w: World, actor: Faction, intent: str) -> str:
    rng = w.rng()
    others = [x for x in w.factions.values() if x.name != actor.name]
    target = rng.choice(others) if others else None

    if intent == "propaganda":
        delta = rng.randint(2, 6)
        actor.power += delta
        actor.radicalization += 1
        if actor.name == "Temple":
            w.magical_tension += 3
        if actor.name == "Lodge":
            w.public_fear += 3
        return f"{actor.name} runs propaganda (+{delta} Power)."

    if intent == "sabotage" and target:
        dmg = rng.randint(3, 8)
        target.stability -= dmg
        target.resources -= rng.randint(1, 5)
        w.public_fear += 4
        if rng.random() < 0.2:
            actor.power -= 5
            return f"{actor.name} sabotages {target.name} (-{dmg} Stability), but gets exposed (-5 Power)."
        return f"{actor.name} sabotages {target.name} (-{dmg} Stability)."

    if intent == "aid":
        actor.stability += 8
        actor.resources -= 3
        return f"{actor.name} invests in internal stability (+8 Stability, -3 Resources)."

    if intent == "law":
        if actor.name == "Merchants":
            w.economic_stress -= 8
            actor.power += 3
            return "Merchants push emergency tariffs: Economic Stress -8, Merchants +3 Power."
        if actor.name == "Temple":
            w.magical_tension -= 5
            actor.power += 3
            return "Temple proposes restrictions on magic: Magical Tension -5, Temple +3 Power."
        w.public_fear -= 3
        return f"{actor.name} passes a calming decree: Public Fear -3."

    return f"{actor.name} hesitates."


def system_escalations(w: World) -> List[str]:
    out = []
    rng = w.rng()

    mages = w.factions.get("Mages")
    if mages and w.magical_tension > 75 and mages.stability < 35 and rng.random() < 0.35:
        out.append("A magical mishap erupts in the docks. People panic.")
        w.public_fear += 12
        w.economic_stress += 8
        mages.power -= 10
        mages.stability -= 10

    if w.public_fear > 80 and rng.random() < 0.30:
        out.append("A street riot breaks out. Shops burn; arrests follow.")
        w.economic_stress += 10
        w.public_fear += 5
        if "Council" in w.factions:
            w.factions["Council"].power -= 5
        if "Temple" in w.factions:
            w.factions["Temple"].power += 3

    if w.day in (3, 5) and rng.random() < 0.6:
        clue = {
            "lodge": "A dockworker whispers about masked men near the lighthouse.",
            "mages": "Arcane residue is found on torn sailcloth—someone used a sigil.",
            "merchants": "A ledger shows insurance fraud tied to a guild ship.",
            "accident": "The harbourmaster reports a sudden storm and faulty charts."
        }[w.crisis_truth]
        out.append(f"Clue: {clue}")

    return out


def check_ending(w: World) -> Optional[str]:
    temple = w.factions.get("Temple")
    merchants = w.factions.get("Merchants")
    mages = w.factions.get("Mages")
    lodge = w.factions.get("Lodge")
    council = w.factions.get("Council")

    if mages and w.magical_tension > 85 and mages.stability < 25:
        return "Arcane Disaster: the docks burn with violet fire; emergency rule follows."

    if temple and temple.radicalization > 75 and w.public_fear > 65 and temple.power > 70:
        return "Theocracy: the Temple seizes sacred rule; magic is outlawed."

    if merchants and merchants.power > 78 and w.economic_stress < 45:
        return "Merchant Protectorate: trade stabilizes; the city becomes a gilded oligarchy."

    if lodge and lodge.power > 60 and w.public_fear > 70:
        return "Shadow Regency: people obey out of fear; nothing is officially true."

    if council and council.power > 60 and w.public_fear < 55 and w.economic_stress < 55:
        return "Civic Reform: the Council brokers a fragile social contract."

    return None


def step_world(w: World, player_action: str) -> Optional[str]:
    # Player acts
    w.log.append(f"Day {w.day}: PLAYER -> {apply_player_action(w, player_action)}")

    # Factions act
    for f in list(w.factions.values()):
        intent = faction_intent(w, f)
        w.log.append(f"Day {w.day}: {apply_faction_action(w, f, intent)}")

    # System escalations
    for e in system_escalations(w):
        w.log.append(f"Day {w.day}: {e}")

    # Natural drift
    w.public_fear += 1 if w.economic_stress > 65 else -2
    w.economic_stress += 1 if w.public_fear > 75 else 0
    if "Temple" in w.factions and "Mages" in w.factions:
        w.magical_tension += 1 if w.factions["Temple"].power > w.factions["Mages"].power + 20 else -1

    w.clamp()
    ending = check_ending(w)
    w.day += 1
    return ending


# -----------------------------
# Streamlit UI
# -----------------------------

st.set_page_config(page_title="CRPG City Sim (Vertical Slice)", layout="wide")

st.title("CRPG City Sim — Vertical Slice (Headless Engine + UI)")

with st.sidebar:
    st.header("Session")
    seed = st.number_input("Seed", min_value=1, max_value=999999, value=42, step=1)
    max_days = st.slider("Max days", min_value=3, max_value=30, value=7, step=1)

    st.divider()
    st.header("Tuning (CSV)")
    st.caption(f"CSV file: {CSV_PATH}")
    if os.path.exists(CSV_PATH):
        st.success("factions.csv найден")
    else:
        st.info("factions.csv не найден — используется дефолт")

    if st.button("Reload factions from CSV"):
        st.session_state["factions_df"] = load_factions_df()
        st.toast("Loaded", icon="✅")

    colA, colB = st.columns(2)
    with colA:
        if st.button("Save factions to CSV"):
            save_factions_df(st.session_state.get("factions_df", load_factions_df()))
            st.toast("Saved to factions.csv", icon="💾")
    with colB:
        if st.button("Reset to defaults"):
            st.session_state["factions_df"] = DEFAULT_FACTIONS.copy()
            st.toast("Reset", icon="🔄")

    st.divider()
    if st.button("New game / Reset world", type="primary"):
        df = st.session_state.get("factions_df", load_factions_df())
        st.session_state["world"] = init_world_from_df(df, seed=seed, max_days=max_days)
        st.session_state["ending"] = None
        st.toast("World reset", icon="🌍")


# Init session state
if "factions_df" not in st.session_state:
    st.session_state["factions_df"] = load_factions_df()

if "world" not in st.session_state:
    st.session_state["world"] = init_world_from_df(st.session_state["factions_df"], seed=seed, max_days=max_days)

if "ending" not in st.session_state:
    st.session_state["ending"] = None

w: World = st.session_state["world"]

# Layout
left, right = st.columns([1.05, 0.95], gap="large")

with left:
    st.subheader("Parameters (editable)")
    st.caption("Правь значения и нажми **New game / Reset world** чтобы применить их к симуляции.")
    edited = st.data_editor(
        st.session_state["factions_df"],
        num_rows="dynamic",
        use_container_width=True,
        key="factions_editor",
    )

    # Keep only expected cols and clamp-ish
    expected = ["name", "power", "stability", "radicalization", "resources"]
    for c in expected:
        if c not in edited.columns:
            st.error(f"Missing column: {c}")
            st.stop()
    edited = edited[expected].copy()
    # Ensure types
    for c in ["power", "stability", "radicalization", "resources"]:
        edited[c] = pd.to_numeric(edited[c], errors="coerce").fillna(0).astype(int).clip(0, 100)
    edited["name"] = edited["name"].astype(str)

    st.session_state["factions_df"] = edited

    st.divider()
    st.subheader("World state")
    g1, g2, g3 = st.columns(3)
    g1.metric("Economic Stress", w.economic_stress)
    g2.metric("Public Fear", w.public_fear)
    g3.metric("Magical Tension", w.magical_tension)

    # Factions table (computed)
    rows = []
    for f in w.factions.values():
        rows.append(
            {
                "name": f.name,
                "power": f.power,
                "stability": f.stability,
                "radicalization": f.radicalization,
                "resources": f.resources,
                "eff_power": compute_effective_power(f),
                "player_rel": f.rel_player,
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

with right:
    st.subheader(f"Turn: Day {w.day}/{w.max_days}")
    st.caption("Выбирай действие — город отвечает. Это UI-обёртка над движком, без контента и катсцен.")

    if st.session_state["ending"]:
        st.error(f"ENDING: {st.session_state['ending']}")
        st.info("Нажми **New game / Reset world** в сайдбаре, чтобы начать заново.")

    # Action buttons
    st.markdown("### Your action")
    btn_cols = st.columns(3)
    action_map = {
        "Investigate": "investigate",
        "Support Temple": "support_temple",
        "Support Mages": "support_mages",
        "Support Merchants": "support_merchants",
        "Spread Rumour": "spread_rumour",
        "Bribe": "bribe",
    }
    clicked_action = None
    labels = list(action_map.keys())
    for i, label in enumerate(labels):
        with btn_cols[i % 3]:
            if st.button(label, use_container_width=True, disabled=bool(st.session_state["ending"])):
                clicked_action = action_map[label]

    # Step world on click
    if clicked_action and not st.session_state["ending"]:
        ending = step_world(w, clicked_action)
        if ending:
            st.session_state["ending"] = ending
        # force rerun to refresh UI immediately
        st.rerun()

    st.divider()
    st.markdown("### Latest news")
    latest = w.log[-8:] if len(w.log) > 8 else w.log
    if latest:
        for line in reversed(latest):
            st.write("• " + line)
    else:
        st.write("No events yet.")

    with st.expander("Full log"):
        for line in w.log:
            st.write(line)

st.caption("Tip: измени factions.csv → Reload factions → Reset world. Потом можно переносить движок в Godot/Unity, не переписывая систему.")
