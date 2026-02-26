import re
import json
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo


# -------------------- Helpers --------------------

TIME_PRESETS = {
    "00:00": time(0, 0),
    "06:00": time(6, 0),
    "09:00": time(9, 0),
    "12:00": time(12, 0),
    "18:00": time(18, 0),
    "21:00": time(21, 0),
    "23:59": time(23, 59),
}

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

def parse_time_text(s: str) -> time | None:
    """
    Accepts:
      HH:MM
      HH:MM:SS
    """
    s = (s or "").strip()
    if not s:
        return None
    try:
        parts = s.split(":")
        if len(parts) == 2:
            h, m = int(parts[0]), int(parts[1])
            return time(h, m)
        if len(parts) == 3:
            h, m, sec = int(parts[0]), int(parts[1]), int(parts[2])
            return time(h, m, sec)
        return None
    except Exception:
        return None

def get_time_value(prefix: str) -> time:
    """
    Priority:
      1) manual text time (if valid)
      2) time_input widget value
    """
    manual = parse_time_text(st.session_state.get(f"{prefix}_time_text", ""))
    if manual is not None:
        return manual
    return st.session_state.get(f"{prefix}_time_picker", time(0, 0))

def on_preset_change(prefix: str):
    preset_label = st.session_state.get(f"{prefix}_preset", "—")
    if preset_label in TIME_PRESETS:
        st.session_state[f"{prefix}_time_picker"] = TIME_PRESETS[preset_label]
        # удобно: если пользователь выбирает пресет, можно ещё и обновить текст
        t = TIME_PRESETS[preset_label]
        st.session_state[f"{prefix}_time_text"] = f"{t.hour:02d}:{t.minute:02d}" + (f":{t.second:02d}" if t.second else "")

def to_unix(dt: datetime, unit: str) -> int:
    ts = int(dt.timestamp())
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


def datetime_block(title: str, prefix: str, default_time: time):
    """
    Рисует блок:
      - date_input
      - preset selectbox (оставляем список)
      - time_input (можно печатать)
      - text_input для ручного ввода (HH:MM[:SS]) — главный requested feature
    """
    st.markdown(f"**{title}**")

    # init defaults
    if f"{prefix}_time_picker" not in st.session_state:
        st.session_state[f"{prefix}_time_picker"] = default_time
    if f"{prefix}_time_text" not in st.session_state:
        st.session_state[f"{prefix}_time_text"] = ""

    date = st.date_input("Дата", key=f"{prefix}_date")

    c1, c2 = st.columns([1, 1])
    with c1:
        st.selectbox(
            "Пресет времени",
            options=["—"] + list(TIME_PRESETS.keys()),
            key=f"{prefix}_preset",
            on_change=on_preset_change,
            args=(prefix,),
            help="Быстрый выбор типового времени (не обязателен).",
        )
        st.time_input(
            "Время (пикер)",
            key=f"{prefix}_time_picker",
            help="Можно также печатать в поле.",
        )

    with c2:
        st.text_input(
            "Время (вручную: HH:MM или HH:MM:SS)",
            key=f"{prefix}_time_text",
            help="Если заполнено и валидно — оно приоритетнее пикера.",
            placeholder="Например: 14:30 или 14:30:15",
        )

    t = get_time_value(prefix)
    return date, t


# -------------------- App --------------------

st.set_page_config(page_title="GD Multitool", page_icon="🛠", layout="wide")
st.title("🛠 GD Multitool для ГД — UNIX ↔ DateTime + Подстановка в JSON")

tabs = st.tabs(["⏱ Конвертер UNIX", "🧩 Подстановка / Расшифровка"])

# Common settings (top)
top_c1, top_c2, top_c3 = st.columns([1, 1, 1])
with top_c1:
    unit = st.radio("Единицы timestamp", ["s", "ms"], horizontal=True)
with top_c2:
    tz_name = st.selectbox(
        "Таймзона отображения (для расшифровки)",
        options=["UTC", "Asia/Yerevan", "Europe/Moscow", "Europe/London", "America/Los_Angeles"],
        index=1,
    )
tz = ZoneInfo(tz_name)
with top_c3:
    st.caption("Порядок источников времени: **ручной ввод** → пикер → (опционально пресет, если выбран).")

st.divider()

default_json = '''{
  "questEventGroup": { "groupId": 182, "order": 1 },
  "teamLevel": 1,
  "mission": { "id": 10, "value": 1 },
  "time": {
    "value": [ ВРЕМЯ СТАРТА, ВРЕМЯ ЗАВЕРШЕНИЯ ],
    "operator": "bt"
  },
  "enable": 1
}'''

# -------------------- TAB 1: Converter --------------------
with tabs[0]:
    st.subheader("Конвертер даты/времени → UNIX timestamp")

    c1, c2 = st.columns(2)
    with c1:
        start_date, start_t = datetime_block("Старт", "start1", default_time=time(0, 0))
    with c2:
        end_date, end_t = datetime_block("Завершение", "end1", default_time=time(23, 59))

    start_dt_local = datetime.combine(start_date, start_t).replace(tzinfo=tz)
    end_dt_local = datetime.combine(end_date, end_t).replace(tzinfo=tz)

    if end_dt_local < start_dt_local:
        st.warning("Финиш раньше старта — проверь, это точно нужно?")

    start_ts = to_unix(start_dt_local.astimezone(timezone.utc), unit)
    end_ts = to_unix(end_dt_local.astimezone(timezone.utc), unit)

    st.markdown("### Результат")
    r1, r2 = st.columns(2)
    with r1:
        st.markdown("**Start**")
        st.code(str(start_ts), language="text")
        copy_button("Скопировать start", str(start_ts), key="copy_start_tab1")
        st.caption(f"Дата: {fmt_dt(start_dt_local.astimezone(timezone.utc), tz)}")
    with r2:
        st.markdown("**End**")
        st.code(str(end_ts), language="text")
        copy_button("Скопировать end", str(end_ts), key="copy_end_tab1")
        st.caption(f"Дата: {fmt_dt(end_dt_local.astimezone(timezone.utc), tz)}")


# -------------------- TAB 2: Replace + Decode --------------------
with tabs[1]:
    st.subheader("Подстановка timestamps в текст/JSON + расшифровка timestamps из текста")

    c1, c2 = st.columns(2)
    with c1:
        start_date, start_t = datetime_block("Старт", "start2", default_time=time(0, 0))
    with c2:
        end_date, end_t = datetime_block("Завершение", "end2", default_time=time(23, 59))

    start_dt_local = datetime.combine(start_date, start_t).replace(tzinfo=tz)
    end_dt_local = datetime.combine(end_date, end_t).replace(tzinfo=tz)

    start_ts = to_unix(start_dt_local.astimezone(timezone.utc), unit)
    end_ts = to_unix(end_dt_local.astimezone(timezone.utc), unit)

    st.markdown("### Текст / JSON")
    source_text = st.text_area("Вставь любой текст", value=default_json, height=280)

    ph1, ph2 = st.columns(2)
    with ph1:
        placeholder_start = st.text_input("Плейсхолдер старта", value="ВРЕМЯ СТАРТА")
    with ph2:
        placeholder_end = st.text_input("Плейсхолдер завершения", value="ВРЕМЯ ЗАВЕРШЕНИЯ")

    btn_c1, btn_c2 = st.columns([1, 1])
    with btn_c1:
        do_replace = st.button("Подставить timestamps", type="primary")
    with btn_c2:
        do_decode = st.button("Расшифровать timestamps из текста")

    st.divider()

    # --- Replace result ---
    if do_replace:
        result = replace_placeholders(source_text, placeholder_start, placeholder_end, start_ts, end_ts)
        st.markdown("### Результат подстановки")
        st.text_area(" ", value=result, height=260, disabled=True)
        copy_button("Скопировать результат", result, key="copy_replace_tab2")

    # --- Decode result ---
    if do_decode:
        st.markdown("### Расшифровка timestamps")
        found = find_timestamps(source_text, min_len=10)
        if not found:
            st.info("Не нашёл чисел, похожих на timestamp (10+ цифр).")
        else:
            rows = []
            for ts in found[:200]:
                guessed = guess_unit(ts)
                dt_utc = from_unix(ts, unit=guessed)
                rows.append((ts, guessed, fmt_dt(dt_utc, tz)))

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
            st.markdown("**Сводка для копирования**")
            st.text_area("  ", value=summary, height=160, disabled=True)
            copy_button("Скопировать сводку", summary, key="copy_decode_summary_tab2")
