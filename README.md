# SimRPG

Набор Streamlit-прототипов: AI-приключение и отдельные GD-утилиты.

## Основное приложение (канон)

```bash
pip install -r requirements.txt
streamlit run AIDungeon.py
```

Нужны переменные окружения (или `st.secrets`):

| Переменная | Назначение |
|------------|------------|
| `OPENAI_API_KEY` | ключ OpenAI |
| `OPENAI_MODEL` | модель (опционально) |
| `ADVENTURE_DB_PATH` | путь к SQLite (по умолчанию `adventure.db`) |

## Карта скриптов

| Файл | Что это |
|------|---------|
| **`AIDungeon.py`** | Канонический AI Adventure (комнаты, герои, журнал, SQLite, GDD v1.4) |
| `Multitool.py` | GD Multitool: UNIX/локали, опциональный перевод |
| `MM.py` | Прототип матчмейкинга гильдий |
| `Teleportation.py` | Симулятор точки входа при телепорте |
| `archive/legacy/` | Устаревшие RPG-прототипы (`AIDungeon2.py`, `AdventureAI.py`) — см. [archive/README.md](archive/README.md) |

## Dev container

После открытия в Codespaces / Dev Containers поднимается `streamlit run AIDungeon.py` на порту `8501`.
