import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, time
import json


# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------

def to_unix(dt: datetime) -> int:
    """Перевод datetime в UNIX timestamp (секунды)."""
    return int(dt.timestamp())


def copy_button(label: str, text_to_copy: str, key: str):
    """
    Рисует кнопку, которая копирует text_to_copy в буфер обмена.
    Использует простой JS через components.html.
    """
    safe_text = json.dumps(text_to_copy)  # безопасно экранируем для JS-строки
    html = f"""
    <script>
    function copyToClipboard_{key}() {{
        navigator.clipboard.writeText({safe_text});
    }}
    </script>
    <button onclick="copyToClipboard_{key}()" style="
        padding: 0.4rem 0.8rem;
        border-radius: 0.4rem;
        border: 1px solid #ccc;
        cursor: pointer;
    ">{label}</button>
    """
    components.html(html, height=45)


# ---------- UI ПРИЛОЖЕНИЯ ----------

st.set_page_config(page_title="GD Multitool", page_icon="🛠", layout="wide")
st.title("🛠 GD Multitool — конвертер времени и подстановка в JSON")

st.markdown(
    """
**Функции:**
1. Конвертация даты/времени в **UNIX timestamp** (старт и конец).
2. Подстановка сконвертированных значений в **произвольный текст/JSON** по плейсхолдерам.
"""
)

tab1, tab2 = st.tabs(["⏱ Конвертер времени", "🧩 Подстановка в текст / JSON"])


# ---------- ТАБ 1: ПРОСТОЙ КОНВЕРТЕР ВРЕМЕНИ ----------

with tab1:
    st.subheader("Конвертация даты и времени в UNIX")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Время старта**")
        start_date = st.date_input("Дата старта", key="start_date_tab1")
        start_time = st.time_input("Время старта", value=time(0, 0), key="start_time_tab1")

    with col2:
        st.markdown("**Время завершения**")
        end_date = st.date_input("Дата завершения", key="end_date_tab1")
        end_time = st.time_input("Время завершения", value=time(23, 59), key="end_time_tab1")

    if st.button("Конвертировать в UNIX", type="primary", key="convert_tab1"):
        start_dt = datetime.combine(start_date, start_time)
        end_dt = datetime.combine(end_date, end_time)

        unix_start = to_unix(start_dt)
        unix_end = to_unix(end_dt)

        st.success("Результаты конвертации:")
        c1, c2 = st.columns(2)

        with c1:
            st.markdown("**UNIX время старта**")
            st.code(str(unix_start), language="text")
            copy_button("Скопировать старт", str(unix_start), key="copy_start_tab1")

        with c2:
            st.markdown("**UNIX время завершения**")
            st.code(str(unix_end), language="text")
            copy_button("Скопировать финиш", str(unix_end), key="copy_end_tab1")


# ---------- ТАБ 2: ПОДСТАНОВКА В ПРОИЗВОЛЬНЫЙ ТЕКСТ / JSON ----------

with tab2:
    st.subheader("Подстановка сконвертированного времени в текст / JSON")

    st.markdown(
        """
1. Выбери **две даты/времени** (старт и конец).
2. Вставь произвольный текст или JSON.
3. Укажи плейсхолдеры для подстановки (что заменять на UNIX-значения).
4. Нажми «Сгенерировать текст с подстановкой».
"""
    )

    # --- Блок выбора времени ---
    st.markdown("### 1. Выбор временного интервала")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Время старта**")
        start_date_2 = st.date_input("Дата старта", key="start_date_tab2")
        start_time_2 = st.time_input("Время старта", value=time(0, 0), key="start_time_tab2")

    with col2:
        st.markdown("**Время завершения**")
        end_date_2 = st.date_input("Дата завершения", key="end_date_tab2")
        end_time_2 = st.time_input("Время завершения", value=time(23, 59), key="end_time_tab2")

    start_dt_2 = datetime.combine(start_date_2, start_time_2)
    end_dt_2 = datetime.combine(end_date_2, end_time_2)

    unix_start_2 = to_unix(start_dt_2)
    unix_end_2 = to_unix(end_dt_2)

    st.markdown("**Текущие UNIX значения (для информации):**")
    c1, c2 = st.columns(2)
    with c1:
        st.write(f"Старт: `{unix_start_2}`")
    with c2:
        st.write(f"Финиш: `{unix_end_2}`")

    # --- Блок плейсхолдеров ---
    st.markdown("### 2. Плейсхолдеры для подстановки")

    ph_col1, ph_col2 = st.columns(2)

    with ph_col1:
        placeholder_start = st.text_input(
            "Плейсхолдер старта",
            value="ВРЕМЯ СТАРТА",
            help="Эта строка в тексте будет заменена на UNIX-время старта",
            key="ph_start",
        )
    with ph_col2:
        placeholder_end = st.text_input(
            "Плейсхолдер завершения",
            value="ВРЕМЯ ЗАВЕРШЕНИЯ",
            help="Эта строка в тексте будет заменена на UNIX-время завершения",
            key="ph_end",
        )

    # --- Блок исходного текста ---
    st.markdown("### 3. Исходный текст / JSON")

    default_json = '''{
    "questEventGroup": {
        "groupId": 182,
        "order": 1
    },
    "teamLevel": 1,
    "mission": {
        "id": 10,
        "value": 1
    },
    "time": {
        "value": [
            ВРЕМЯ СТАРТА,
            ВРЕМЯ ЗАВЕРШЕНИЯ
        ],
        "operator": "bt"
    },
    "enable": 1
}'''

    source_text = st.text_area(
        "Исходный текст",
        value=default_json,
        height=300,
        help="Сюда можно вставить любой текст или JSON. "
             "Все вхождения плейсхолдеров будут заменены на соответствующие UNIX-времена.",
    )

    # --- Кнопка генерации и результат ---
    if st.button("Сгенерировать текст с подстановкой", type="primary", key="generate_tab2"):
        # Простая замена всех вхождений плейсхолдеров
        result_text = source_text.replace(placeholder_start, str(unix_start_2))
        result_text = result_text.replace(placeholder_end, str(unix_end_2))

        st.success("Сгенерированный текст:")
        st.text_area(
            "Результат",
            value=result_text,
            height=300,
            disabled=True,
        )

        copy_button("Скопировать результат", result_text, key="copy_result_tab2")

        st.info(
            "Подстановка сделана простым `.replace()` по строкам плейсхолдеров. "
            "Если нужно, можно расширить до шаблонов / RegExp / нескольких пар дат."
        )
