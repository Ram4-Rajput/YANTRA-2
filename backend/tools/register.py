from tools.applications import (
    open_application,
    close_application,
    open_blank_excel,
)

from tools.browser import (
    open_website,
    web_search,
)

from tools.system import (
    get_system_status,
)

from tools.files import (
    list_files,
    read_file,
    write_file,
    open_file,
)

from tools.computer import (
    move_mouse,
    click_mouse,
    double_click,
    type_text,
    press_key,
    hotkey,
    take_screenshot,
    get_active_window,
)

from tools.vision import (
    capture_screen,
)
from mark_actions.adapter import MARK_TOOL_MODULES, execute_mark_tool

LOCAL_TOOL_OVERRIDES = {"web_search"}

TOOLS = {

    # Applications
    "open_application": open_application,
    "close_application": close_application,
    "open_blank_excel": open_blank_excel,

    # Browser
    "open_website": open_website,
    "web_search": web_search,
    # System
    "system_status": get_system_status,

    # Files
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "open_file": open_file,

    # Computer
    "move_mouse": move_mouse,
    "click_mouse": click_mouse,
    "double_click": double_click,
    "type_text": type_text,
    "press_key": press_key,
    "hotkey": hotkey,
    "take_screenshot": take_screenshot,
    "get_active_window": get_active_window,

    # Vision
    "capture_screen": capture_screen,
}

for mark_tool in MARK_TOOL_MODULES:
    TOOLS.setdefault(mark_tool, execute_mark_tool)


def execute_tool(command):

    if not isinstance(command, dict):

        return {
            "success": False,
            "message": "Invalid tool command."
        }

    explicit_tool_name = command.get("_tool_name")
    if explicit_tool_name in MARK_TOOL_MODULES and explicit_tool_name not in LOCAL_TOOL_OVERRIDES:
        return execute_mark_tool(command, explicit_tool_name)
    if explicit_tool_name:
        command = {key: value for key, value in command.items() if key != "_tool_name"}
        command["action"] = explicit_tool_name

    action = command.get("action")

    if action in MARK_TOOL_MODULES and action not in LOCAL_TOOL_OVERRIDES:
        return execute_mark_tool(command)

    target = command.get("target")

    query = command.get("query")

    content = command.get("content")

    tool = TOOLS.get(action)

    if tool is None:

        return {
            "success": False,
            "message": f"Unsupported action: {action}"
        }

    # Web search
    if action == "web_search":

        try:

            return tool(query, browser=command.get("browser"))

        except Exception as e:

            return {
                "success": False,
                "message": f"Web search failed: {e}"
            }

    if action in {"weather_report", "youtube_video", "flight_finder"}:
        try:
            return tool(command)
        except Exception as e:
            return {
                "success": False,
                "message": f"Automation failed: {e}"
            }

    if action == "capture_screen":
        try:
            return tool(
                path=command.get("path") or target,
                source=command.get("source", "screen"),
                camera_index=command.get("camera_index", 0),
            )
        except Exception as e:
            return {
                "success": False,
                "message": f"Vision capture failed: {e}"
            }

    # Write file
    if action == "write_file":

        try:

            return tool(
                target,
                content or ""
            )

        except Exception as e:

            return {
                "success": False,
                "message": f"File writing failed: {e}"
            }

    # Actions that don't require arguments
    if action in {"get_active_window", "open_blank_excel"}:

        try:
            return tool()

        except Exception as e:

            return {
                "success": False,
                "message": f"Tool execution failed: {e}"
            }

    # Default tool execution
    try:

        return tool(target)

    except Exception as e:

        return {
            "success": False,
            "message": f"Tool execution failed: {e}"
        }


def get_available_tools():

    return list(TOOLS.keys())


if __name__ == "__main__":

    print()
    print("================================")
    print("        TOOL REGISTRY")
    print("================================")

    print()
    print("Available tools:")
    print()

    for index, tool_name in enumerate(
        TOOLS.keys(),
        start=1
    ):

        print(
            f"{index:2}. {tool_name}"
        )

    print()
    print(
        f"Total tools: {len(TOOLS)}"
    )