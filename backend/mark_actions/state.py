import json
import hashlib
import os
import tempfile
from datetime import datetime
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent / "data"
MEMORY_PATH = DATA_DIR / "long_term.json"
MONITORS_PATH = DATA_DIR / "monitors.json"
BLOCKED_TOPICS = {
    "bitcoin", "ethereum", "dogecoin", "solana", "binance", "nft",
    "blockchain", "defi", "altcoin", "memecoin", "crypto", "kripto",
    "finance", "financial", "stock trading", "trading",
}


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.stem}-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def save_memory(parameters: dict) -> dict:
    category = str(parameters.get("category", "notes")).strip().lower() or "notes"
    key = str(parameters.get("key", "")).strip()
    value = str(parameters.get("value", "")).strip()
    if not key or not value:
        return {"success": False, "message": "A memory key and value are required."}
    memory = _read(MEMORY_PATH)
    facts = memory.setdefault(category, {})
    if not isinstance(facts, dict):
        facts = {}
        memory[category] = facts
    facts[key] = {"value": value}
    _write(MEMORY_PATH, memory)
    return {"success": True, "message": "Saved that for future conversations."}


def format_saved_memory() -> str:
    memory = _read(MEMORY_PATH)
    lines = []
    for category, entries in memory.items():
        if not isinstance(entries, dict):
            continue
        for key, item in entries.items():
            value = item.get("value") if isinstance(item, dict) else item
            if value:
                lines.append(f"{category}/{key}: {value}")
    return "\n".join(lines)


def manage_monitor(parameters: dict) -> dict:
    action = str(parameters.get("action", "")).strip().lower()
    topic = str(parameters.get("topic", "")).strip()
    monitors = _read(MONITORS_PATH)

    if action == "list":
        topics = [str(item.get("topic", key)) for key, item in monitors.items()]
        return {"success": True, "message": ", ".join(topics) if topics else "No topics are being monitored."}

    if not topic:
        return {"success": False, "message": "A topic is required."}

    normalized = " ".join(topic.casefold().split())
    if action == "add":
        if any(term in normalized for term in BLOCKED_TOPICS):
            return {"success": False, "message": "Financial and crypto topics are not monitored."}
        key = normalized.replace(" ", "_")[:48]
        if key in monitors:
            return {"success": True, "message": f"Already monitoring {monitors[key]['topic']}."}
        monitors[key] = {"topic": topic, "last_check": "", "last_hash": ""}
        _write(MONITORS_PATH, monitors)
        return {"success": True, "message": f"Now monitoring {topic}."}

    if action == "remove":
        key = normalized.replace(" ", "_")[:48]
        if key not in monitors:
            match = next((k for k, item in monitors.items() if normalized in item.get("topic", "").casefold()), None)
            key = match
        if key is None or key not in monitors:
            return {"success": False, "message": f"No matching monitored topic: {topic}."}
        removed = monitors.pop(key)["topic"]
        _write(MONITORS_PATH, monitors)
        return {"success": True, "message": f"Stopped monitoring {removed}."}

    return {"success": False, "message": "Choose add, remove, or list."}


def get_monitored_topics() -> list[str]:
    return [str(item.get("topic", key)) for key, item in _read(MONITORS_PATH).items()]


def check_monitored_topics() -> list[str]:
    from mark_actions.adapter import _load_action_module

    monitors = _read(MONITORS_PATH)
    today = datetime.now().strftime("%Y-%m-%d")
    changed = False
    alerts = []
    search = _load_action_module("actions.web_search")

    for key, item in monitors.items():
        if item.get("last_check") == today:
            continue
        topic = str(item.get("topic", key))
        try:
            results = search._ddg_news(topic, max_results=5)
        except Exception as error:
            print(f"[Monitor] Search failed for {topic}: {type(error).__name__}")
            continue

        item["last_check"] = today
        changed = True
        if not results:
            continue
        headline = str(results[0].get("title", "")).strip()
        if not headline:
            continue
        digest = hashlib.sha256(headline.encode("utf-8", errors="ignore")).hexdigest()[:16]
        if digest == item.get("last_hash"):
            continue
        item["last_hash"] = digest
        details = [f"New update for {topic}: {headline}"]
        snippet = str(results[0].get("snippet", "")).strip()
        source = str(results[0].get("source", "")).strip()
        if snippet:
            details.append(snippet[:180])
        if source:
            details.append(f"Source: {source}")
        alerts.append("\n".join(details))

    if changed:
        _write(MONITORS_PATH, monitors)
    return alerts