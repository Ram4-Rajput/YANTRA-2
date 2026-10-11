"""
YANTRA conversation memory — persistent JSON store.
Keeps the last N turns so Gemini has full conversational context.
"""
import json
from pathlib import Path

MEMORY_FILE = Path(__file__).parent / "assistant_memory.json"

# Keep more turns for better follow-up context ("what about the other one?", "why?")
MAX_MESSAGES = 30
# How many turns we actually send to Gemini (keeps the prompt lean)
CONTEXT_WINDOW = 20


def load_memory() -> list:
    if not MEMORY_FILE.exists():
        return []
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def save_memory(memory: list) -> None:
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memory, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[YANTRA] Memory save error: {e}")


def add_message(role: str, content: str) -> None:
    memory = load_memory()
    memory.append({"role": role, "content": content})
    if len(memory) > MAX_MESSAGES:
        memory = memory[-MAX_MESSAGES:]
    save_memory(memory)


def get_recent_memory() -> list:
    """Return the most recent CONTEXT_WINDOW messages for Gemini."""
    return load_memory()[-CONTEXT_WINDOW:]


def clear_memory() -> dict:
    save_memory([])
    return {"success": True, "message": "Conversation memory cleared."}
