# Archive

Legacy Streamlit prototypes kept for history. **Do not run these as the product entrypoint.**

## Canonical app

```bash
streamlit run AIDungeon.py
```

See the root [README.md](../README.md).

## What lives here

| Path | Why archived |
|------|----------------|
| `legacy/AIDungeon2.py` | Twin of `AIDungeon.py` forked ~2026-03-04. Missing later polish (JSON repair, typewriter UI, HTML escape). Last commit earlier than `AIDungeon.py`. |
| `legacy/AdventureAI.py` | Early JSON/`chat.completions` prototype (2026-03-02). Superseded by the SQLite rooms/journal stack in `AIDungeon.py`. |

## Left in repo root (not archived)

These are separate GD tools, not RPG entrypoint twins:

- `Multitool.py` — locale / UNIX placeholder helpers
- `MM.py` — guild matchmaking prototype
- `Teleportation.py` — PvP teleport entry simulator
