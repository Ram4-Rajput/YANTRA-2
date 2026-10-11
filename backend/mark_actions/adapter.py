import importlib
import os
import sys
from pathlib import Path


MARK_ROOT = Path(__file__).resolve().parent
if str(MARK_ROOT) not in sys.path:
    sys.path.insert(0, str(MARK_ROOT))

MARK_TOOL_MODULES = {
    "open_app": ("actions.open_app", "open_app"),
    "weather_report": ("actions.weather_report", "weather_action"),
    "send_message": ("actions.send_message", "send_message"),
    "reminder": ("actions.reminder", "reminder"),
    "youtube_video": ("actions.youtube_video", "youtube_video"),
    "computer_settings": ("actions.computer_settings", "computer_settings"),
    "browser_control": ("actions.browser_control", "browser_control"),
    "file_controller": ("actions.file_controller", "file_controller"),
    "desktop_control": ("actions.desktop", "desktop_control"),
    "code_helper": ("actions.code_helper", "code_helper"),
    "dev_agent": ("actions.dev_agent", "dev_agent"),
    "web_search": ("actions.web_search", "web_search"),
    "file_processor": ("actions.file_processor", "file_processor"),
    "computer_control": ("actions.computer_control", "computer_control"),
    "game_updater": ("actions.game_updater", "game_updater"),
    "flight_finder": ("actions.flight_finder", "flight_finder"),
    "system_status": ("actions.system_monitor", "get_system_status"),
    "manage_monitor": ("mark_actions.state", "manage_monitor"),
    "save_memory": ("mark_actions.state", "save_memory"),
    "shutdown_yantra": ("mark_actions.adapter", "request_shutdown"),
}


class _DashboardAdapter:
    current_file = None

    def write_log(self, message: str) -> None:
        print(f"[Mark action] {message}")

    def show_content(self, title: str, content: str) -> None:
        return None


def _api_key() -> str:
    return os.getenv("GEMINI_API_KEY", "").strip()


def _load_action_module(module_name: str):
    module = importlib.import_module(module_name)
    if hasattr(module, "_get_api_key"):
        module._get_api_key = _api_key
    if hasattr(module, "_load_config"):
        module._load_config = lambda: {
            "gemini_api_key": _api_key(),
            "os_system": importlib.import_module("config").get_os(),
        }
    return module


def _normalize_result(result):
    if isinstance(result, dict):
        return result
    message = str(result or "Action completed.")
    lowered = message.strip().lower()
    failed = lowered.startswith((
        "could not", "couldn't", "failed", "error:", "unable to", "i couldn't",
        "not found:", "no results", "search failed",
    ))
    return {"success": not failed, "message": message}


def request_shutdown(parameters: dict) -> dict:
    server = sys.modules.get("ui_server")
    stop = getattr(server, "_stop_voice_safely", None) if server else None
    if stop is None:
        return {"success": False, "message": "The voice session is not running."}
    stop()
    return {"success": True, "message": "Stopping the voice session."}


def execute_mark_tool(command: dict, tool_name: str | None = None) -> dict:
    explicit_tool_name = tool_name or command.get("_tool_name")
    action = explicit_tool_name or (command.get("action") if isinstance(command, dict) else None)
    entry = MARK_TOOL_MODULES.get(action)
    if entry is None:
        return {"success": False, "message": f"Unsupported Mark automation: {action}"}

    module_name, function_name = entry
    try:
        module = _load_action_module(module_name)
        function = getattr(module, function_name)
        excluded = {"_tool_name"} if explicit_tool_name else {"action"}
        arguments = {key: value for key, value in command.items() if key not in excluded}
        player = _DashboardAdapter()

        if action == "system_status":
            result = function()
        elif action == "open_app":
            result = function(parameters=arguments, response=None, player=player)
        elif action in {"send_message", "reminder", "youtube_video"}:
            result = function(
                parameters=arguments,
                response=None,
                player=player,
                session_memory=None,
            ) if action == "send_message" else function(
                parameters=arguments,
                response=None,
                player=player,
            )
        elif action in {"code_helper", "dev_agent", "file_processor", "game_updater", "flight_finder"}:
            result = function(parameters=arguments, player=player, speak=lambda _text: None)
        elif action in {"weather_report", "browser_control", "file_controller", "desktop_control", "computer_settings", "web_search", "computer_control"}:
            result = function(parameters=arguments, player=player)
        else:
            result = function(parameters=arguments)

        return _normalize_result(result)
    except Exception as error:
        return {"success": False, "message": f"{action} failed: {type(error).__name__}: {error}"}