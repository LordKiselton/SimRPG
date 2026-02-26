import re
import json
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo


# -------------------- Helpers --------------------

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


def copy_button_responsive(label: str, text_to_copy: str, key: str):
    """JS-кнопка копирования с быстрым визуальным фидбеком без перерендера."""
    safe_text = json.dumps(text_to_copy)
    html = f"""
    <div>
      <button id="btn_{key}" style="
          padding: 0.42rem 0.85rem;
          border-radius: 0.55rem;
          border: 1px solid #D0D0D0;
          background: white;
          cursor: pointer;
          font-size: 0.95rem;
      ">{label}</button>
    </div>

    <script>
      const btn = document.getElementById("btn_{key}");
      const original = btn.innerText;

      btn.addEventListener("click", async () => {{
        try {{
          await navigator.clipboard.writeText({safe_text});
          btn.innerText = "Скопировано ✓";
          btn.style.borderColor = "#4CAF50";
          btn.style.background = "#F2FFF5";
          setTimeout(() => {{
            btn.innerText = original;
            btn.style.borderColor = "#D0D0D0";
            btn.style.background = "white";
          }}, 900);
        }} catch (e) {{
          btn.innerText = "Не удалось :(";
          btn.style.borderColor = "#F44336";
          btn.style.background = "#FFF2F2";
          setTimeout(() => {{
            btn.innerText = original;
            btn.style.borderColor = "#D0D0D0";
            btn.style.background = "white";
          }}, 1200);
        }}
      }});
    </script>
    """
    components.html(html, height=54)


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


def fmt_dt(dt_aware: datetime, tz: ZoneInfo) -> str:
    local_dt = dt_aware.astimezone(tz)
    return local_dt.strftime("%Y-%m-%d %H:%M:%S") + f" ({tz.key})"


def fmt_utc(dt_aware: datetime) -> str:
    dt_utc = dt_aware.astimezone(timezone.utc)
    return dt_utc.strftime("%Y-%m-%d %H:%M:%S") + " (UTC)"


def validate_json(text: str):
    """(ok, info, pretty, minified)"""
    try:
        data = json.loads(text)
        pretty = json.dumps(data, ensure_ascii=False, indent=2)
        minified = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return True, "OK", pretty, minified
    except json.JSONDecodeError as e:
        return False, f"{e.msg} (строка {e.lineno}, колонка {e.colno})", None, None
    except Exception as e:
        return False, str(e), None, None


def compact_settings(tab_key: str):
    """
    Настройки сверху:
      1) Таймзона
      2) Единицы (s/ms) — ПОД таймзоной
    """
    tz_name = st.selectbox(
        "timezone",
        options=["UTC", "Asia/Yerevan", "Europe/Moscow", "Europe/London", "America/Los_Angeles"],
        index=0,  # UTC default
        key=f"{tab_key}_tz",
        label_visibility="collapsed",
    )
    unit = st.radio(
        "unit",
        ["s", "ms"],
        horizontal=True,
        key=f"{tab_key}_unit",
        label_visibility="collapsed",
    )
    return unit, ZoneInfo(tz_name)


def time_pair_controls(prefix: str, tz: ZoneInfo):
    """Дата + одно поле time_input (пикер + ручной ввод)."""
    c1, c2 = st.columns(2)
    with c1:
        sd = st.date_input("Дата старта", key=f"{prefix}_sd")
        stime = st.time_input("Время старта", value=time(0, 0), key=f"{prefix}_st")
    with c2:
        ed = st.date_input("Дата финиша", key=f"{prefix}_ed")
        etime = st.time_input("Время финиша", value=time(23, 59), key=f"{prefix}_et")

    start_local = datetime.combine(sd, stime).replace(tzinfo=tz)
    end_local = datetime.combine(ed, etime).replace(tzinfo=tz)
    return start_local, end_local


# -------------------- App --------------------

st.set_page_config(page_title="GD Multitool", page_icon="🛠", layout="wide")
st.title("🛠 GD Multitool")

# CSS: делаем селект таймзоны заметно уже
st.markdown(
    """
    <style>
      div[data-testid="stSelectbox"] { max-width: 240px; }
      div[data-testid="stRadio"] { max-width: 200px; }
    </style>
    """,
    unsafe_allow_html=True,
)

tabs = st.tabs(["🧩 Подстановка UNIX", "🔎 Расшифровка UNIX"])


# -------------------- Tab: Replace --------------------
with tabs[0]:
    unit, tz = compact_settings("rep")
    st.divider()

    left, right = st.columns([1, 1])

    with left:
        start_local, end_local = time_pair_controls("rep_time", tz)

        if end_local < start_local:
            st.warning("Финиш раньше старта.")

        start_ts = to_unix(start_local.astimezone(timezone.utc), unit)
        end_ts = to_unix(end_local.astimezone(timezone.utc), unit)
        st.caption(f"Start: `{start_ts}`  |  End: `{end_ts}`")

        src = st.text_area("Текст / JSON", value=DEFAULT_TEXT, height=280, key="rep_src")

        p1, p2 = st.columns(2)
        with p1:
            ph_start = st.text_input("Плейсхолдер старта", value="ВРЕМЯ СТАРТА", key="rep_phs")
        with p2:
            ph_end = st.text_input("Плейсхолдер финиша", value="ВРЕМЯ ЗАВЕРШЕНИЯ", key="rep_phe")

        if st.button("Подставить", type="primary", key="rep_btn"):
            st.session_state["rep_result"] = replace_placeholders(src, ph_start, ph_end, start_ts, end_ts)

    with right:
        result = st.session_state.get("rep_result", "")
        if not result:
            st.info("Здесь появится результат после подстановки.")
        else:
            ok, info, pretty, minified = validate_json(result)

            if ok:
                st.success("JSON валиден")
                view_mode = st.radio(
                    "Вид",
                    ["Pretty", "Minified"],
                    horizontal=True,
                    label_visibility="collapsed",
                    key="rep_json_view",
                )

                if view_mode == "Pretty":
                    st.code(pretty, language="json")
                    copy_button_responsive("Скопировать pretty", pretty, key="copy_rep_pretty")
                else:
                    st.code(minified, language="json")
                    copy_button_responsive("Скопировать minified", minified, key="copy_rep_minified")
            else:
                st.error(f"JSON невалиден: {info}")
                st.code(result, language="text")
                copy_button_responsive("Скопировать raw", result, key="copy_rep_raw")


# -------------------- Tab: Decode --------------------
with tabs[1]:
    _, tz = compact_settings("dec")
    st.divider()

    left, right = st.columns([1, 1])

    with left:
        src = st.text_area("Текст / JSON", value=DEFAULT_TEXT, height=340, key="dec_src")
        if st.button("Найти timestamps", type="primary", key="dec_btn"):
            found = find_timestamps(src, min_len=10)

            rows = []
            for ts in found[:400]:
                guessed = guess_unit(ts)
                dt_utc = from_unix(ts, unit=guessed)  # tz-aware UTC datetime
                rows.append(
                    (ts, guessed, fmt_dt(dt_utc, tz), fmt_utc(dt_utc))
                )

            st.session_state["dec_rows"] = rows

    with right:
        rows = st.session_state.get("dec_rows", [])
        if not rows:
            st.info("Здесь появится таблица после поиска.")
        else:
            st.dataframe(
                rows,
                use_container_width=True,
                column_config={
                    0: st.column_config.NumberColumn("Timestamp"),
                    1: st.column_config.TextColumn("s/ms"),
                    2: st.column_config.TextColumn("В выбранной TZ"),
                    3: st.column_config.TextColumn("GMT+0"),
                },
            )
