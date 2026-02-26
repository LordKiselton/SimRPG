import re
import json
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo


# -------------------- Helpers --------------------

def copy_button(label: str, text_to_copy: str, key: str):
    safe_text = json.dumps(text_to_copy)
    html = f"""
    <script>
    function copyToClipboard_{key}() {{
        navigator.clipboard.writeText({safe_text});
    }}
    </script>
    <button onclick="copyToClipboard_{key}()" style="
        padding: 0.42rem 0.85rem;
        border-radius: 0.55rem;
        border: 1px solid #D0D0D0;
        background: white;
        cursor: pointer;
        font-size: 0.95rem;
    ">{label}</button>
    """
    components.html(html, height=52)

def to_unix(dt_utc: datetime, unit: str) -> int:
    ts = int(dt_utc.timestamp())
    return ts if unit == "s" else ts * 1000

def from_unix(ts: int, unit: str) -> datetime:
    if unit == "ms":
        ts = ts / 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc)

def replace_placeholders(text: str, ph_start: str, ph_end: str, start_ts: int, end_ts: int) -> str:
    return text.replace(ph_start, str(start_ts)).replace(ph_end, str(end_ts))

def find_timestamps(text: str, min_len: int = 10) -> list[int]:
    pattern = r"(?<!\d)(\d{" + str(min_len) + r",})(?!\d)"
    return [int(m.group(1)) for m in re.finditer(pattern, text)]

def guess_unit(ts: int) -> str:
    digits = len(str(abs(ts)))
    return "ms" if digits >= 13 else "s"

def fmt_dt(dt_utc: datetime, tz: ZoneInfo) -> str:
    local_dt = dt_utc.astimezone(tz)
    return local_dt.strftime("%Y-%m-%d %H:%M:%S") + f" ({tz.key})"


DEFAULT_TEXT = '''{
  "questEventGroup": { "groupId": 182, "order": 1 },
  "teamLevel": 1,
  "mission": { "id": 10, "value": 1 },
  "time": {
    "value": [ ВРЕМЯ СТАРТА, ВРЕМЯ ЗАВЕРШЕНИЯ ],
    "operator": "bt"
  },
  "enable": 1
}'''


def time_controls_block(key_prefix: str, tz: ZoneInfo):
    """
    Только 2 поля:
      - дата
      - время (один input, который умеет и пикер, и ручной ввод)
    """
    col1, col2 = st.columns([1, 1])
    with col1:
        d = st.date_input("Дата", key=f"{key_prefix}_date")
    with col2:
        t = st.time_input(
            "Время",
            key=f"{key_prefix}_time",
            value=time(0, 0) if "start" in key_prefix else time(23, 59),
            help="Можно выбрать из пикера или напечатать вручную (HH:MM).",
        )
    dt_local = datetime.combine(d, t).replace(tzinfo=tz)
    return dt_local


def top_settings_block(tab_key: str):
    """
    Настройки в самом верху вкладки:
      - unit (s/ms)
      - timezone
    """
    c1, c2 = st.columns([1, 2])
    with c1:
        unit = st.radio(
            "Единицы timestamp",
            ["s", "ms"],
            horizontal=True,
            key=f"{tab_key}_unit",
        )
    with c2:
        tz_name = st.selectbox(
            "Таймзона (для ввода дат и отображения расшифровки)",
            options=["UTC", "Asia/Yerevan", "Europe/Moscow", "Europe/London", "America/Los_Angeles"],
            index=1,
            key=f"{tab_key}_tz",
        )
    return unit, ZoneInfo(tz_name)


# -------------------- App --------------------

st.set_page_config(page_title="GD Multitool", page_icon="🛠", layout="wide")
st.title("🛠 GD Multitool — Подстановка и расшифровка времени в JSON/тексте")

tabs = st.tabs(["🧩 Подстановка timestamps", "🔎 Расшифровка timestamps"])


# -------------------- TAB 1: Replace --------------------
with tabs[0]:
    st.subheader("Подстановка времени в текст/JSON по плейсхолдерам")

    # settings at top
    unit, tz = top_settings_block("replace")

    st.markdown("### Время")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Старт**")
        start_dt_local = time_controls_block("replace_start", tz)
    with c2:
        st.markdown("**Завершение**")
        end_dt_local = time_controls_block("replace_end", tz)

    if end_dt_local < start_dt_local:
        st.warning("Финиш раньше старта — проверь даты/время.")

    start_ts = to_unix(start_dt_local.astimezone(timezone.utc), unit)
    end_ts = to_unix(end_dt_local.astimezone(timezone.utc), unit)

    st.caption(f"Start: `{start_ts}`  |  End: `{end_ts}`")

    st.markdown("### Текст / JSON")
    source_text = st.text_area("Исходный текст", value=DEFAULT_TEXT, height=280)

    p1, p2 = st.columns(2)
    with p1:
        ph_start = st.text_input("Плейсхолдер старта", value="ВРЕМЯ СТАРТА")
    with p2:
        ph_end = st.text_input("Плейсхолдер завершения", value="ВРЕМЯ ЗАВЕРШЕНИЯ")

    if st.button("Подставить", type="primary", key="do_replace"):
        result = replace_placeholders(source_text, ph_start, ph_end, start_ts, end_ts)

        st.markdown("### Результат")
        st.text_area(" ", value=result, height=280, disabled=True)
        copy_button("Скопировать результат", result, key="copy_replace_result")


# -------------------- TAB 2: Decode --------------------
with tabs[1]:
    st.subheader("Расшифровка timestamps из текста/JSON → человекочитаемые даты")

    # settings at top
    unit_hint, tz = top_settings_block("decode")
    st.caption("Расшифровка использует авто-определение (s/ms) по длине числа, но можно сверяться с выбранными единицами выше.")

    st.markdown("### Текст / JSON")
    source_text = st.text_area("Вставь текст для расшифровки", value=DEFAULT_TEXT, height=320)

    if st.button("Найти и расшифровать timestamps", type="primary", key="do_decode"):
        found = find_timestamps(source_text, min_len=10)

        if not found:
            st.info("Не нашёл чисел, похожих на timestamp (10+ цифр).")
        else:
            rows = []
            for ts in found[:300]:
                guessed = guess_unit(ts)
                dt_utc = from_unix(ts, unit=guessed)
                rows.append((ts, guessed, fmt_dt(dt_utc, tz)))

            st.markdown("### Найденные timestamps")
            st.dataframe(
                rows,
                use_container_width=True,
                column_config={
                    0: st.column_config.NumberColumn("Timestamp"),
                    1: st.column_config.TextColumn("Guess (s/ms)"),
                    2: st.column_config.TextColumn("Дата"),
                },
            )

            summary = "\n".join([f"{ts} [{g}] -> {d}" for ts, g, d in rows])
            st.markdown("### Сводка")
            st.text_area("  ", value=summary, height=180, disabled=True)
            copy_button("Скопировать сводку", summary, key="copy_decode_summary")
