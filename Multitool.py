import re
import os
import json
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

# Optional OpenAI dependency
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except Exception:
    OPENAI_AVAILABLE = False

# Optional pandas dependency (for locale table)
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except Exception:
    PANDAS_AVAILABLE = False


# -------------------- Constants --------------------

LANGS = ["ru", "de", "en", "es", "fr", "it", "ja", "ko", "pl", "pt", "zh-cn", "zh-tw"]

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


# -------------------- Key / OpenAI helpers --------------------

def get_openai_key() -> str | None:
    # Secrets preferred, env as fallback
    try:
        return st.secrets.get("OPENAI_API_KEY", None) or os.getenv("OPENAI_API_KEY")
    except Exception:
        return os.getenv("OPENAI_API_KEY")


@st.cache_data(show_spinner=False, ttl=3600)
def list_models_openai_cached(api_key: str) -> list[str]:
    """
    Fetch list of available model IDs for this key.
    Cached for 1 hour.
    """
    client = OpenAI(api_key=api_key)
    models = client.models.list()
    ids = [m.id for m in models.data if getattr(m, "id", None)]

    # Keep likely chat/text models and sort
    preferred_prefixes = ("gpt-", "o-")
    ids = [mid for mid in ids if mid.startswith(preferred_prefixes)]
    ids.sort()
    return ids


@st.cache_data(show_spinner=False)
def translate_openai_cached(text: str, src_lang: str, tgt_lang: str, model: str, api_key: str) -> str:
    """
    Cached translation. Uses OpenAI Responses API.
    """
    if not OPENAI_AVAILABLE:
        raise RuntimeError("OpenAI SDK не установлен. Установи: pip install openai")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY не найден (secrets/env).")

    client = OpenAI(api_key=api_key)

    prompt = (
        f"Translate the text from {src_lang} to {tgt_lang}.\n"
        f"Rules:\n"
        f"- Return ONLY the translated text, no quotes, no explanations.\n"
        f"- Preserve placeholders/tokens exactly if present (e.g., {{0}}, %s, \\n, <color=...>, [tag]).\n"
        f"- Keep game/UI tone natural.\n\n"
        f"TEXT:\n{text}"
    )

    resp = client.responses.create(
        model=model,
        input=prompt,
    )
    out = (resp.output_text or "").strip()
    return out if out else text


# -------------------- UI helpers --------------------

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


# -------------------- Time / JSON helpers --------------------

def parse_time_text(s: str):
    """
    Parse HH:MM or HH:MM:SS.
    Returns: (time_obj or None, normalized_str or None, error_str or None)
    """
    s = (s or "").strip()
    if not s:
        return None, None, "Введи время (HH:MM или HH:MM:SS)"

    m = re.fullmatch(r"(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?", s)
    if not m:
        return None, None, "Неверный формат. Пример: 09:30 или 09:30:15"

    h = int(m.group(1))
    mi = int(m.group(2))
    se = int(m.group(3)) if m.group(3) is not None else 0

    if not (0 <= h <= 23 and 0 <= mi <= 59 and 0 <= se <= 59):
        return None, None, "Некорректное время (часы 0–23, минуты/секунды 0–59)"

    t = time(h, mi, se)
    norm = f"{h:02d}:{mi:02d}" + (f":{se:02d}" if m.group(3) is not None else "")
    return t, norm, None


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
      1) Таймзона (default UTC)
      2) Единицы (s/ms) — под таймзоной
    """
    tz_name = st.selectbox(
        "timezone",
        options=["UTC", "Asia/Yerevan", "Europe/Moscow", "Europe/London", "America/Los_Angeles"],
        index=0,
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
    """
    Дата + удобный ввод времени текстом (HH:MM или HH:MM:SS).
    Returns: (start_dt_local, end_dt_local, ok_bool)
    """
    c1, c2 = st.columns(2)

    with c1:
        sd = st.date_input("Дата старта", key=f"{prefix}_sd")
        st_text = st.text_input(
            "Время старта",
            value=st.session_state.get(f"{prefix}_st_text", "00:00"),
            key=f"{prefix}_st_text",
            placeholder="09:30",
        )
        st_t, st_norm, st_err = parse_time_text(st_text)
        if st_err:
            st.error(st_err)
        else:
            if st_norm != st_text:
                st.session_state[f"{prefix}_st_text"] = st_norm

    with c2:
        ed = st.date_input("Дата финиша", key=f"{prefix}_ed")
        et_text = st.text_input(
            "Время финиша",
            value=st.session_state.get(f"{prefix}_et_text", "23:59"),
            key=f"{prefix}_et_text",
            placeholder="18:00",
        )
        et_t, et_norm, et_err = parse_time_text(et_text)
        if et_err:
            st.error(et_err)
        else:
            if et_norm != et_text:
                st.session_state[f"{prefix}_et_text"] = et_norm

    ok = (st_t is not None) and (et_t is not None)
    if not ok:
        return None, None, False

    start_local = datetime.combine(sd, st_t).replace(tzinfo=tz)
    end_local = datetime.combine(ed, et_t).replace(tzinfo=tz)
    return start_local, end_local, True


# -------------------- Localization helpers --------------------

def now_last_update_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def build_locale_rows(
    ident: str,
    base_lang: str,
    base_text: str,
    appear_ident: str,
    translations: dict[str, str],
    last_update: str,
) -> list[dict]:
    """
    Build structured rows for table + export.
    """
    rows = []
    for lang in LANGS:
        text_val = base_text if lang == base_lang else translations.get(lang, base_text)
        rows.append(
            {
                "ident": ident,
                "lang": lang,
                "text": text_val,
                "lastUpdateDate": last_update,
                "description": "NULL",
                "deleted": "0",
                "_comment": "NULL",
                "appearIdent": appear_ident,
            }
        )
    return rows


def build_locale_tsv_from_rows(rows: list[dict]) -> str:
    header = "ident\tlang\ttext\tlastUpdateDate\tdescription\tdeleted\t_comment\tappearIdent"
    lines = [header]
    for r in rows:
        lines.append(
            f"{r['ident']}\t{r['lang']}\t{r['text']}\t{r['lastUpdateDate']}\t{r['description']}\t{r['deleted']}\t{r['_comment']}\t{r['appearIdent']}"
        )
    return "\n".join(lines)


# -------------------- App --------------------

st.set_page_config(page_title="GD Multitool", page_icon="🛠", layout="wide")
st.title("🛠 GD Multitool")

# CSS: compact selectors
st.markdown(
    """
    <style>
      div[data-testid="stSelectbox"] { max-width: 240px; }
      div[data-testid="stRadio"] { max-width: 220px; }
    </style>
    """,
    unsafe_allow_html=True,
)

tabs = st.tabs(["🧩 Подстановка UNIX", "🔎 Расшифровка UNIX", "🌐 Создание локали"])


# -------------------- Tab: Replace --------------------
with tabs[0]:
    unit, tz = compact_settings("rep")
    st.divider()

    left, right = st.columns([1, 1])

    with left:
        start_local, end_local, ok_time = time_pair_controls("rep_time", tz)

        if ok_time:
            if end_local < start_local:
                st.warning("Финиш раньше старта.")
            start_ts = to_unix(start_local.astimezone(timezone.utc), unit)
            end_ts = to_unix(end_local.astimezone(timezone.utc), unit)
            st.caption(f"Start: `{start_ts}`  |  End: `{end_ts}`")
        else:
            start_ts = end_ts = None

        src = st.text_area("Текст / JSON", value=DEFAULT_TEXT, height=280, key="rep_src")

        p1, p2 = st.columns(2)
        with p1:
            ph_start = st.text_input("Плейсхолдер старта", value="ВРЕМЯ СТАРТА", key="rep_phs")
        with p2:
            ph_end = st.text_input("Плейсхолдер финиша", value="ВРЕМЯ ЗАВЕРШЕНИЯ", key="rep_phe")

        do_replace = st.button("Подставить", type="primary", key="rep_btn", disabled=not ok_time)
        if do_replace:
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
                dt_utc = from_unix(ts, unit=guessed)
                rows.append((ts, guessed, fmt_dt(dt_utc, tz), fmt_utc(dt_utc)))

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


# -------------------- Tab: Locale creation --------------------
with tabs[2]:
    left, right = st.columns([1, 1])

    with left:
        ident = st.text_input("Ident", key="loc_ident", placeholder="GUILDVERSUS_CITY_ENTRY_POINT")
        base_text = st.text_area("Text", key="loc_text", height=120, placeholder="Текст на базовом языке")
        appear_ident = st.text_input("AppearIdent", key="loc_appear", placeholder="eventVS")

        base_lang = st.selectbox("Lang", options=LANGS, index=0, key="loc_lang")  # default ru
        use_ai = st.checkbox("Автоперевод нейросетью", value=True, key="loc_use_ai")

        api_key = get_openai_key()
        can_translate = use_ai and OPENAI_AVAILABLE and bool(api_key)

        selected_model = "gpt-4o-mini"
        if use_ai:
            if not OPENAI_AVAILABLE:
                st.warning("Для автоперевода установи: pip install openai")
            elif not api_key:
                st.warning("В secrets/env не найден OPENAI_API_KEY — автоперевод отключён.")
            else:
                try:
                    model_ids = list_models_openai_cached(api_key)
                    if model_ids:
                        default_model = "gpt-4o-mini" if "gpt-4o-mini" in model_ids else model_ids[0]
                        selected_model = st.selectbox(
                            "Model",
                            options=model_ids,
                            index=model_ids.index(default_model),
                            key="loc_model_select",
                        )
                    else:
                        st.warning("Список моделей пуст — автоперевод отключён.")
                        can_translate = False
                except Exception as e:
                    st.error(f"Не удалось загрузить список моделей: {e}")
                    can_translate = False

        gen = st.button(
            "Сгенерировать",
            type="primary",
            key="loc_gen",
            disabled=not (ident.strip() and base_text.strip() and appear_ident.strip()),
        )

        if gen:
            last_update = now_last_update_str()
            translations: dict[str, str] = {}

            if can_translate:
                with st.spinner("Перевожу…"):
                    for lang in LANGS:
                        if lang == base_lang:
                            continue
                        try:
                            translations[lang] = translate_openai_cached(
                                base_text.strip(),
                                src_lang=base_lang,
                                tgt_lang=lang,
                                model=selected_model,
                                api_key=api_key,
                            )
                        except Exception as e:
                            # show real error (no silent fail)
                            st.error(f"Ошибка перевода для {lang}: {e}")
                            translations[lang] = base_text.strip()
            else:
                # No AI: keep base text for all langs (still produces valid table/TSV)
                translations = {lang: base_text.strip() for lang in LANGS if lang != base_lang}

            locale_rows = build_locale_rows(
                ident=ident.strip(),
                base_lang=base_lang,
                base_text=base_text.strip(),
                appear_ident=appear_ident.strip(),
                translations=translations,
                last_update=last_update,
            )

            st.session_state["loc_rows"] = locale_rows
            st.session_state["loc_tsv"] = build_locale_tsv_from_rows(locale_rows)

    with right:
        if not PANDAS_AVAILABLE:
            st.error("Для табличного вывода локалей нужен пакет pandas. Добавь `pandas` в requirements.txt.")
        else:
            rows = st.session_state.get("loc_rows", [])
            tsv = st.session_state.get("loc_tsv", "")

            if not rows:
                st.info("Здесь появится таблица после генерации.")
            else:
                df = pd.DataFrame(rows)

                st.dataframe(
                    df,
                    use_container_width=True,
                    hide_index=True,
                )

                csv_data = df.to_csv(index=False)
                st.download_button(
                    label="Скачать CSV",
                    data=csv_data,
                    file_name="localization.csv",
                    mime="text/csv",
                )

                if tsv:
                    copy_button_responsive("Скопировать TSV", tsv, key="copy_loc_tsv")
