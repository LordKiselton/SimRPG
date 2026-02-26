import re
import json
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo


# -------------------- Utils --------------------

def to_unix(dt: datetime, unit: str = "s") -> int:
    """datetime -> unix timestamp in seconds or milliseconds"""
    ts = int(dt.timestamp())
    return ts if unit == "s" else ts * 1000


def from_unix(ts: int, unit: str = "s") -> datetime:
    """unix timestamp -> datetime (naive in UTC)"""
    if unit == "ms":
        ts = ts / 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def copy_button(label: str, text_to_copy: str, key: str):
    safe_text = json.dumps(text_to_copy)
    html = f"""
    <script>
    function copyToClipboard_{key}() {{
        navigator.clipboard.writeText({safe_text});
    }}
    </script>
    <button onclick="copyToClipboard_{key}()" style="
        padding: 0.42rem 0.8rem;
        border-radius: 0.55rem;
        border: 1px solid #D0D0D0;
        background: white;
        cursor: pointer;
        font-size: 0.95rem;
    ">{label}</button>
    """
    components.html(html, height=52)


def replace_placeholders(text: str, ph_start: str, ph_end: str, start_ts: int, end_ts: int) -> str:
    return text.replace(ph_start, str(start_ts)).replace(ph_end, str(end_ts))


def find_timestamps(text: str, min_len: int = 10):
    """
    Находит числа похожие на unix timestamp.
    min_len=10 по умолчанию (секунды обычно 10 цифр, ms 13).
    """
    # числа, окруженные не-цифрами, чтобы не ловить куски id слишком агрессивно
    pattern = r"(?<!\d)(\d{" + str(min_len) + r",})(?!\d)"
    return [int(m.group(1)) for m in re.finditer(pattern, text)]


def guess_unit(ts: int) -> str:
    """
    Грубая эвристика:
    - 13+ цифр чаще ms
    - 10 цифр чаще s
    """
    digits = len(str(abs(ts)))
    return "ms" if digits >= 13 else "s"


def format_dt(dt_utc: datetime, tz: ZoneInfo) -> str:
    local_dt = dt_utc.astimezone(tz)
    return f"{local_dt.strftime('%Y-%m-%d %H:%M:%S')} ({tz.key})"


# -------------------- App --------------------

st.set_page_config(page_title="GD Multitool", page_icon="🛠", layout="wide")

st.title("🛠 GD Multitool — Time & Text")
st.caption("Конвертация времени ↔ UNIX timestamp, подстановка в текст/JSON, расшифровка timestamp из текста.")

# Sidebar = единая панель управления временем
with st.sidebar:
    st.header("⏱ Time Panel")

    tz_name = st.selectbox(
        "Таймзона отображения (для расшифровки)",
        options=["UTC", "Asia/Yerevan", "Europe/Moscow", "Europe/London", "America/Los_Angeles"],
        index=1
    )
    tz = ZoneInfo(tz_name)

    unit = st.radio("Единицы timestamp", options=["s", "ms"], horizontal=True, help="s=секунды, ms=миллисекунды")

    st.divider()
    st.subheader("Старт")
    start_date = st.date_input("Дата", key="start_date")
    start_time = st.time_input("Время", value=time(0, 0), key="start_time")

    st.subheader("Финиш")
    end_date = st.date_input("Дата ", key="end_date")
    end_time = st.time_input("Время ", value=time(23, 59), key="end_time")

    st.divider()
    mode = st.selectbox(
        "Режим",
        options=[
            "Показать UNIX",
            "Подставить в текст (placeholder)",
            "Расшифровать timestamp из текста",
            "Комбо: подставить + расшифровать",
        ],
        index=3
    )

# вычисления времени (один раз)
start_dt = datetime.combine(start_date, start_time).replace(tzinfo=tz)
end_dt = datetime.combine(end_date, end_time).replace(tzinfo=tz)

start_ts = to_unix(start_dt.astimezone(timezone.utc), unit=unit)
end_ts = to_unix(end_dt.astimezone(timezone.utc), unit=unit)

# предупреждения
if end_dt < start_dt:
    st.warning("Финиш раньше старта. Проверь даты/время — это может быть ошибка или намеренно (например, тест).")

# верхний компактный summary
summary_cols = st.columns(3)
with summary_cols[0]:
    st.markdown("**Старт**")
    st.write(f"`{format_dt(start_dt.astimezone(timezone.utc), tz)}`")
with summary_cols[1]:
    st.markdown("**Финиш**")
    st.write(f"`{format_dt(end_dt.astimezone(timezone.utc), tz)}`")
with summary_cols[2]:
    st.markdown("**UNIX**")
    st.write(f"Start: `{start_ts}`")
    st.write(f"End: `{end_ts}`")

st.divider()


# -------------------- Mode: Show UNIX --------------------
if mode == "Показать UNIX":
    st.subheader("UNIX timestamps")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Start timestamp**")
        st.code(str(start_ts), language="text")
        copy_button("Скопировать start", str(start_ts), key="copy_start")
    with c2:
        st.markdown("**End timestamp**")
        st.code(str(end_ts), language="text")
        copy_button("Скопировать end", str(end_ts), key="copy_end")


# -------------------- Common: Text input --------------------
default_text = '''{
  "questEventGroup": { "groupId": 182, "order": 1 },
  "teamLevel": 1,
  "mission": { "id": 10, "value": 1 },
  "time": {
    "value": [ ВРЕМЯ СТАРТА, ВРЕМЯ ЗАВЕРШЕНИЯ ],
    "operator": "bt"
  },
  "enable": 1
}'''

need_text = mode in [
    "Подставить в текст (placeholder)",
    "Расшифровать timestamp из текста",
    "Комбо: подставить + расшифровать",
]

if need_text:
    st.subheader("🧩 Текст / JSON")

    left, right = st.columns([1, 1])

    with left:
        source_text = st.text_area(
            "Вставь любой текст / JSON",
            value=default_text,
            height=320
        )

        if mode in ["Подставить в текст (placeholder)", "Комбо: подставить + расшифровать"]:
            st.markdown("**Placeholder-подстановка**")
            ph1, ph2 = st.columns(2)
            with ph1:
                placeholder_start = st.text_input("Плейсхолдер старта", value="ВРЕМЯ СТАРТА")
            with ph2:
                placeholder_end = st.text_input("Плейсхолдер финиша", value="ВРЕМЯ ЗАВЕРШЕНИЯ")

    with right:
        if mode == "Подставить в текст (placeholder)":
            result = replace_placeholders(source_text, placeholder_start, placeholder_end, start_ts, end_ts)

            st.markdown("**Результат подстановки**")
            st.text_area(" ", value=result, height=320, disabled=True)
            copy_button("Скопировать результат", result, key="copy_result_replace")

        elif mode == "Расшифровать timestamp из текста":
            st.markdown("**Найденные timestamps и их даты**")

            # находим
            found = find_timestamps(source_text, min_len=10)
            if not found:
                st.info("Не нашёл чисел, похожих на timestamp (10+ цифр).")
            else:
                rows = []
                for ts in found[:200]:  # защита от адского спама
                    guessed = guess_unit(ts)
                    dt_utc = from_unix(ts, unit=guessed)
                    rows.append((ts, guessed, format_dt(dt_utc, tz)))

                st.dataframe(
                    rows,
                    use_container_width=True,
                    column_config={
                        0: st.column_config.NumberColumn("Timestamp"),
                        1: st.column_config.TextColumn("Guess (s/ms)"),
                        2: st.column_config.TextColumn("Дата"),
                    },
                )

                # удобный “сводный” блок для копирования
                summary = "\n".join([f"{ts} [{g}] -> {d}" for ts, g, d in rows])
                st.markdown("**Сводка**")
                st.text_area("  ", value=summary, height=180, disabled=True)
                copy_button("Скопировать сводку", summary, key="copy_decode_summary")

        else:  # combo
            replaced = replace_placeholders(source_text, placeholder_start, placeholder_end, start_ts, end_ts)

            st.markdown("**1) После подстановки**")
            st.text_area("Результат", value=replaced, height=180, disabled=True)
            copy_button("Скопировать подстановку", replaced, key="copy_combo_replaced")

            st.markdown("**2) Расшифровка timestamps (из результата)**")
            found = find_timestamps(replaced, min_len=10)
            if not found:
                st.info("Не нашёл чисел, похожих на timestamp (10+ цифр).")
            else:
                rows = []
                for ts in found[:200]:
                    guessed = guess_unit(ts)
                    dt_utc = from_unix(ts, unit=guessed)
                    rows.append((ts, guessed, format_dt(dt_utc, tz)))

                st.dataframe(
                    rows,
                    use_container_width=True,
                    column_config={
                        0: st.column_config.NumberColumn("Timestamp"),
                        1: st.column_config.TextColumn("Guess (s/ms)"),
                        2: st.column_config.TextColumn("Дата"),
                    },
                )
