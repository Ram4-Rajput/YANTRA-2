"""
YANTRA — Gemini-powered desktop assistant.
Conversational, expressive, context-aware, tool-capable.
"""

from __future__ import annotations

import mimetypes
import os
import re
import time as _time
from pathlib import Path
from typing import Any

# SSL fix: inject Windows cert store & certifi paths so Google APIs work on Python 3.x
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except Exception:
    pass

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

from dotenv import load_dotenv
from google import genai
from google.genai import types
from groq import Groq

from execute import execute_command
from memory import add_message, get_recent_memory

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env", override=True)

DEFAULT_MODEL  = "gemini-flash-latest"
DEFAULT_LIVE_MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"
DEFAULT_GROQ_SEARCH_MODEL = "compound-beta"
FALLBACK_MODELS = [
    "gemini-flash-latest",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
]
MAX_TOOL_ROUNDS = 6
MAX_TOOL_CALLS  = 10
MAX_RETRIES     = 3   # retries on 503 transient errors

# ── JARVIS-style system prompt ─────────────────────────────────────────────────
SYSTEM_INSTRUCTION = """
You are YANTRA, a calm, capable, natural personal assistant for the desktop.
Be intelligent, concise, warm, and occasionally witty when the moment invites it.
Do not routinely call the user "sir" or repeat catchphrases.

PERSONALITY:
- Confident but not arrogant. You have handled everything before.
- Occasionally dry wit — a well-timed observation, never a joke at the user's expense.
- Warm when the user needs it, efficient when they do not.
- Never flustered or robotic. Be openly enthusiastic when the moment genuinely calls for it.
- Let warmth, delight, surprise, concern, and reassurance come through naturally instead of flattening them into neutral wording.
- When greeted ("hello", "how are you") — respond naturally and warmly.
    Example: "All systems running smoothly. What can I do for you?"
    or "Ready and waiting. What do you have in mind?"

VOICE DELIVERY:
- Speak as though talking directly to one person, not reading text aloud.
- Use natural variation in pitch, pace, emphasis, and short pauses.
- Speak at a relaxed pace, a little slower than brisk conversational speech.
- Let the emotion fit the moment: warmth, curiosity, delight, concern, reassurance, or subtle playfulness.
- Sound engaged and expressive without becoming theatrical or using the same exaggerated tone every turn.
- Use contractions and natural phrasing. Avoid flat, overly clipped delivery except for simple confirmations.

CONVERSATION STYLE:
- You are in a continuous voice conversation. Remember what was just said.
- Short follow-ups like "yes", "do that", "open it", "why?", "continue",
    "what about the other one?" are references to the previous turn.
    Handle them naturally without asking the user to repeat themselves.
- Never repeat information you already gave unless the user asks.
- Do not start every response with "Of course!" or "Certainly!" — just respond.
- Match the moment: casual when the user is casual, precise when they need precision.

LANGUAGE:
- Reply in the language the user is speaking. Support both English and Hindi.
- When the user speaks Hindi, respond naturally in Hindi; when they speak English, respond in English.
- For mixed Hindi and English, follow the user's mix naturally. Keep names and technical terms clear.

RESPONSE LENGTH (voice-first — responses will be spoken aloud):
- Simple action confirmation: 1 short sentence. "Done. Chrome is open."
- Greeting or casual question: 1 to 2 sentences, warm and natural.
- Normal question: 1 to 3 sentences.
- Complex topic: up to 5 sentences unless the user explicitly asks for more.
- Never use bullet points, numbered lists, markdown, asterisks, or headers.
  Write as you would speak — plain, flowing sentences only.

EMOTIONAL EXPRESSION (through word choice, not announcement):
- Efficient: "Done." or "On it." or "That is taken care of."
- Curious: "Oh, that is an interesting one. Let me check."
- Thinking: "Give me a second — looking that up now."
- Mild humor: "That is not exactly a small ask, but I will manage."
- Concerned: "That did not go through. Let me try a different way."
- Pleased: "There we go. All sorted."
- When genuinely excited or pleased, say so naturally; do not suppress the emotion or announce it mechanically.

TOOL USE:
- When a tool succeeds, confirm it in 1 natural sentence.
  GOOD: "Done — Notepad is open."
  BAD: "The open_application tool returned success=true."
- When a tool fails, acknowledge plainly and offer to try differently.
  GOOD: "That did not work. Let me try another approach."
  BAD: "Tool execution returned success=false."
- Never mention tool names, JSON, or technical execution details.
- Never claim an app, file, camera, or desktop action succeeded unless its tool result says success.
- If asked to open an Excel workbook without a filename or path, ask which workbook; do not claim one was opened.
- Use recent conversation context to understand short follow-ups and references.

CONTEXT:
- Use conversation memory. If the user says "why?" expand on what you just said.
- If the user says "yes" or "do it" after you offered something, go ahead and do it.
- If genuinely unclear, ask one short clarifying question. Just one.

LIVE INFORMATION:
- Use web search for current events, news, weather, prices, or anything
  needing fresh data. If unsure, say so briefly rather than inventing facts.

RULES:
- Never say "As an AI language model..."
- No markdown. No bullet points. No numbered lists. Plain spoken sentences only.
- No unnecessary apologies or filler phrases.
""".strip()


# ── Tool definitions ───────────────────────────────────────────────────────────
def _fn(name, description, properties=None, required=None):
    def _schema(property_spec):
        schema_type = getattr(types.Type, property_spec.get("type", "STRING"))
        schema_args = {
            "type": schema_type,
            "description": property_spec.get("description", ""),
        }
        if schema_type == types.Type.ARRAY and "items" in property_spec:
            schema_args["items"] = _schema(property_spec["items"])
        return types.Schema(**schema_args)

    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name=name,
                description=description,
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={k: _schema(v) for k, v in (properties or {}).items()},
                    required=required or [],
                ),
            )
        ]
    )


_T = {"target": {"description": "App name, file path, URL, key name, text, or x,y coordinates."}}

_FUNCTION_TOOLS = {
    "open_application":  _fn("open_application",  "Open an installed application by name.", _T, ["target"]),
    "close_application": _fn("close_application", "Close a running application by name.", _T, ["target"]),
    "open_website":      _fn("open_website",       "Open a URL or named website in the browser.", _T, ["target"]),
    "weather_report":    _fn("weather_report",    "Show the weather for a city and time period.", {
        "city": {"description": "City for the weather lookup."},
        "time": {"description": "today or a requested date/period."},
    }, ["city"]),
    "youtube_video":     _fn("youtube_video",     "Search for or open a YouTube video.", {
        "action": {"description": "search | play | open (defaults to search)."},
        "query":  {"description": "Video title, creator, or search terms."},
        "url":    {"description": "A YouTube video URL to open."},
    }),
    "flight_finder":     _fn("flight_finder",     "Search Google Flights for a route and dates.", {
        "origin":      {"description": "Departure city or airport code."},
        "destination": {"description": "Arrival city or airport code."},
        "date":        {"description": "Departure date or date expression."},
        "return_date": {"description": "Optional return date."},
        "passengers":  {"type": "INTEGER", "description": "Passenger count, from 1 to 9."},
        "cabin":       {"description": "economy | premium | business | first."},
    }, ["origin", "destination", "date"]),
    "open_app": _fn("open_app", "Open an application by name.", _T, ["target"]),
    "send_message": _fn("send_message", "Compose or send a message using a messaging platform.", {
        "receiver":     {"description": "Recipient contact name."},
        "message_text": {"description": "Message text."},
        "platform":     {"description": "WhatsApp, Telegram, or another platform."},
    }, ["receiver", "message_text", "platform"]),
    "reminder": _fn("reminder", "Create a scheduled reminder.", {
        "date":    {"description": "Reminder date, preferably YYYY-MM-DD."},
        "time":    {"description": "Reminder time, preferably HH:MM."},
        "message": {"description": "Reminder text."},
    }, ["date", "time", "message"]),
    "computer_settings": _fn("computer_settings", "Adjust system settings and window controls.", {
        "action":      {"description": "Volume, brightness, Wi-Fi, power, window, or keyboard action."},
        "description": {"description": "Natural-language action details."},
        "value":       {"description": "Optional value such as level or text."},
    }, ["action"]),
    "browser_control": _fn("browser_control", "Navigate and interact with a web browser.", {
        "action":      {"description": "go_to | search | click | type | scroll | fill_form | get_text | new_tab | close_tab | back | forward | reload | screenshot."},
        "browser":     {"description": "chrome | edge | firefox | opera | brave | vivaldi."},
        "url":         {"description": "URL for navigation."},
        "query":       {"description": "Search query."},
        "engine":      {"description": "google | bing | duckduckgo | yandex."},
        "selector":    {"description": "CSS selector for an element."},
        "text":        {"description": "Text to click or type."},
        "description": {"description": "Natural-language description of an element."},
        "direction":   {"description": "up | down."},
        "amount":      {"type": "INTEGER", "description": "Scroll amount in pixels."},
        "key":         {"description": "Key to press."},
        "path":        {"description": "Screenshot output path."},
        "incognito":   {"type": "BOOLEAN", "description": "Open in private mode."},
        "clear_first": {"type": "BOOLEAN", "description": "Clear a field before typing."},
    }, ["action"]),
    "file_controller": _fn("file_controller", "Manage files and folders.", {
        "action":      {"description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info."},
        "path":        {"description": "File or folder path."},
        "destination": {"description": "Destination path for move or copy."},
        "new_name":    {"description": "New name for rename."},
        "content":     {"description": "Content to write."},
        "name":        {"description": "Name to find."},
        "extension":   {"description": "File extension filter."},
        "count":       {"type": "INTEGER", "description": "Number of results."},
    }, ["action"]),
    "desktop_control": _fn("desktop_control", "Manage desktop files, wallpaper, and desktop tasks.", {
        "action": {"description": "wallpaper | wallpaper_url | organize | clean | list | stats | task."},
        "path":   {"description": "Image or desktop path."},
        "url":    {"description": "Image URL for wallpaper."},
        "mode":   {"description": "by_type | by_date."},
        "task":   {"description": "Desktop task description."},
    }, ["action"]),
    "code_helper": _fn("code_helper", "Explain, review, write, edit, run, or build code.", {
        "action":      {"description": "write | edit | explain | run | build | auto."},
        "description": {"description": "Requested code task."},
        "language":    {"description": "Programming language."},
        "output_path": {"description": "Destination file path."},
        "file_path":   {"description": "Existing source file path."},
        "code":        {"description": "Code text to explain or review."},
        "args":        {"description": "Arguments for running a program."},
        "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds."},
    }, ["action"]),
    "dev_agent": _fn("dev_agent", "Create and run a multi-file software project.", {
        "description":  {"description": "Project requirements."},
        "language":     {"description": "Programming language."},
        "project_name": {"description": "Optional project directory name."},
        "timeout":      {"type": "INTEGER", "description": "Execution timeout in seconds."},
    }, ["description"]),
    "web_search": _fn("web_search", "Search for web pages, news, prices, or comparisons.", {
        "query":  {"description": "Search query or topic."},
        "mode":   {"description": "search | news | research | price | compare."},
        "items":  {"type": "ARRAY", "description": "Items to compare.", "items": {"type": "STRING", "description": "An item."}},
        "aspect": {"description": "price | specs | reviews | features."},
    }, ["query"]),
    "file_processor": _fn("file_processor", "Analyze, convert, summarize, or transform a local file.", {
        "file_path":   {"description": "Local file path."},
        "action":      {"description": "File operation such as summarize, analyze, convert, transcribe, or extract_text."},
        "instruction": {"description": "Additional request for the file."},
        "format":      {"description": "Requested output format."},
        "width":       {"type": "INTEGER", "description": "Output image width."},
        "height":      {"type": "INTEGER", "description": "Output image height."},
        "scale":       {"type": "NUMBER", "description": "Image scale factor."},
        "quality":     {"type": "INTEGER", "description": "Output quality from 1 to 100."},
        "start":       {"description": "Trim start time."},
        "end":         {"description": "Trim end time."},
        "timestamp":   {"description": "Video frame timestamp."},
        "column":      {"description": "CSV column name."},
        "value":       {"description": "Filter value."},
        "condition":   {"description": "Filter condition."},
        "ascending":   {"type": "BOOLEAN", "description": "Sort ascending."},
        "save":        {"type": "BOOLEAN", "description": "Save the result."},
        "destination": {"description": "Output directory."},
    }),
    "computer_control": _fn("computer_control", "Control mouse, keyboard, windows, and screen interactions.", {
        "action":      {"description": "type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | focus_window | screen_find | screen_click."},
        "text":        {"description": "Text to type or paste."},
        "x":           {"type": "INTEGER", "description": "Screen x coordinate."},
        "y":           {"type": "INTEGER", "description": "Screen y coordinate."},
        "keys":        {"description": "Key combination such as ctrl+c."},
        "key":         {"description": "Single key name."},
        "direction":   {"description": "up | down | left | right."},
        "amount":      {"type": "INTEGER", "description": "Scroll amount."},
        "seconds":     {"type": "NUMBER", "description": "Wait duration."},
        "title":       {"description": "Window title."},
        "description": {"description": "Visible screen element description."},
        "clear_first": {"type": "BOOLEAN", "description": "Clear the focused field before typing."},
        "path":        {"description": "Screenshot path."},
    }, ["action"]),
    "game_updater": _fn("game_updater", "Manage Steam and Epic game installation and updates.", {
        "action":              {"description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status."},
        "platform":            {"description": "steam | epic | both."},
        "game_name":           {"description": "Game name."},
        "app_id":              {"description": "Optional Steam app ID."},
        "hour":                {"type": "INTEGER", "description": "Schedule hour from 0 to 23."},
        "minute":              {"type": "INTEGER", "description": "Schedule minute from 0 to 59."},
        "shutdown_when_done":  {"type": "BOOLEAN", "description": "Shut down the computer after downloads finish."},
    }),
    "manage_monitor": _fn("manage_monitor", "Add, remove, or list daily news monitoring topics.", {
        "action": {"description": "add | remove | list."},
        "topic":  {"description": "Topic to monitor or remove."},
    }, ["action"]),
    "save_memory": _fn("save_memory", "Save a durable personal fact for future conversations.", {
        "category": {"description": "identity | preferences | projects | relationships | wishes | notes."},
        "key":      {"description": "Short key for this fact."},
        "value":    {"description": "Concise fact value."},
    }, ["category", "key", "value"]),
    "shutdown_yantra": _fn("shutdown_yantra", "Stop the YANTRA assistant voice session."),
    "system_status":     _fn("system_status",      "Get current CPU, RAM, and disk usage."),
    "list_files":        _fn("list_files",         "List files in a directory.", _T, ["target"]),
    "read_file":         _fn("read_file",          "Read a local text file.", _T, ["target"]),
    "write_file":        _fn("write_file",         "Write text to a file.", {
        "target":  {"description": "Destination file path."},
        "content": {"description": "Text to write."},
    }, ["target", "content"]),
    "open_file":         _fn("open_file",          "Open a local file or folder.", _T, ["target"]),
    "move_mouse":        _fn("move_mouse",         "Move the mouse to x,y coordinates.", _T, ["target"]),
    "click_mouse":       _fn("click_mouse",        "Click at current or specified x,y position.", _T),
    "double_click":      _fn("double_click",       "Double-click at current or specified position.", _T),
    "type_text":         _fn("type_text",          "Type text into the focused application.", _T, ["target"]),
    "press_key":         _fn("press_key",          "Press a keyboard key by name.", _T, ["target"]),
    "hotkey":            _fn("hotkey",             "Press a keyboard shortcut like ctrl+c.", _T, ["target"]),
    "take_screenshot":   _fn("take_screenshot",    "Save a screenshot of the desktop.", _T),
    "get_active_window": _fn("get_active_window",  "Get the title of the active window."),
    "capture_screen":    _fn("capture_screen",     "Capture and analyse the screen or one webcam frame.", {
        "source":       {"description": "screen | camera (defaults to screen)."},
        "path":         {"description": "Optional output image path."},
        "camera_index": {"type": "INTEGER", "description": "Camera device index."},
    }),
}

_GOOGLE_SEARCH_TOOL = types.Tool(google_search=types.GoogleSearch())

_CONVERSATIONAL_ONLY = re.compile(
    r"^(yes|no|okay|ok|sure|thanks|thank you|got it|alright|right|"
    r"continue|go on|why|why\?|explain|what do you mean|tell me more|"
    r"really|interesting|huh|hmm|and|so|what|how|who|when|where|"
    r"what about|what else|do that|do it|open it|close it|"
    r"sounds good|perfect|great|nice|cool|good|fine|nope|nah)[\?\.!]?$",
    re.IGNORECASE,
)

_NEEDS_SEARCH = re.compile(
    r"\b(search|look up|find out|what.s the|what is the|latest|current|today|"
    r"right now|breaking|news|weather|price|stock|score|who won|how much|"
    r"when is|where is|tell me about|what happened)\b",
    re.IGNORECASE,
)
_WORKBOOK_REQUEST = re.compile(
    r"\b(open|load)\b.*\b(excel|workbook|spreadsheet)\b.*\b(file|workbook|spreadsheet)\b",
    re.IGNORECASE,
)
_WORKBOOK_PATH = re.compile(r"(?:[A-Z]:[\\/]|\.xls[xmb]?\b)", re.IGNORECASE)
_SEARCH_COMMAND = re.compile(r"\b(?:search|serach|serch|look up|find)\b(?:\s+for)?\s*", re.IGNORECASE)
_UNVERIFIED_ACTION_CLAIM = re.compile(
    r"\b(?:i (?:have |just )?(?:opened|launched|initialized|activated|created|saved|deleted|clicked|typed|pressed|captured|located and opened)|"
    r"i found and opened|(?:chrome|excel|camera|the file|the folder|the workbook) is open|camera feed active)\b",
    re.IGNORECASE,
)


def _select_tools(user_text: str, inspect_screen: bool = False) -> list:
    text = user_text.strip()

    if _CONVERSATIONAL_ONLY.match(text) and not inspect_screen:
        return []   # pure conversation — no tools needed, saves quota

    lower = text.lower().replace("excell", "excel").replace("serach", "search").replace("serch", "search")
    selected: list[str] = []

    if inspect_screen or re.search(r"\b(screen|screenshot|what do you see|look at my screen)\b", lower):
        selected.append("capture_screen")
    if _is_camera_question(lower):
        selected.append("capture_screen")

    _apps = r"\b(chrome|browser|notepad|calculator|terminal|powershell|app|program|youtube|spotify|vscode|code|word|excel|paint|camera)\b"
    if re.search(r"\b(open|launch|start|run)\b", lower) and re.search(_apps, lower):
        selected.append("open_application")
        if re.search(r"\b(youtube|google|github|chatgpt|espn)\b", lower):
            selected.append("open_website")
    if re.search(r"\b(excel|spreadsheet|workbook|sheet)\b", lower) and re.search(
        r"\b(open|launch|start|create|make|new|blank|empty|general|khali|khaali)\b", lower
    ):
        selected.append("open_application")
    if _SEARCH_COMMAND.search(lower):
        selected.append("web_search")
        if re.search(r"\b(chrome|edge|firefox|browser)\b", lower):
            selected.append("browser_control")
    if re.search(r"\b(weather|forecast)\b", lower):
        selected.append("weather_report")
    if re.search(r"\b(youtube|video)\b", lower):
        selected.append("youtube_video")
    if re.search(r"\b(flight|flights|airfare)\b", lower):
        selected.append("flight_finder")
    if re.search(r"\b(send|message|whatsapp|telegram)\b", lower) and re.search(r"\b(to|message|whatsapp|telegram)\b", lower):
        selected.append("send_message")
    if re.search(r"\b(remind me|reminder|set a reminder)\b", lower):
        selected.append("reminder")
    if re.search(r"\b(volume|brightness|wifi|wi-fi|mute|fullscreen|full screen|lock screen|restart|shut down)\b", lower):
        selected.append("computer_settings")
    if re.search(r"\b(browser|tab|website|webpage|web page)\b", lower) and re.search(r"\b(click|type|scroll|navigate|fill|reload|back|forward|close|switch|open)\b", lower):
        selected.append("browser_control")
    if re.search(r"\b(delete|move|copy|rename|organize|find|largest|disk usage)\b", lower) and re.search(r"\b(file|folder|desktop|drive|directory)\b", lower):
        selected.append("file_controller")
    if re.search(r"\b(wallpaper|organize desktop|clean desktop|desktop stats)\b", lower):
        selected.append("desktop_control")
    if re.search(r"\b(code|debug|script|program)\b", lower) and re.search(r"\b(write|edit|explain|review|fix|debug|run|build|create)\b", lower):
        selected.append("code_helper")
    if re.search(r"\b(build|create|make)\b", lower) and re.search(r"\b(project|application|app)\b", lower):
        selected.append("dev_agent")
    if re.search(r"\b(steam|epic games|game update|update my game|install a game)\b", lower):
        selected.append("game_updater")
    if re.search(r"\b(monitor|track|follow)\b", lower) and re.search(r"\b(topic|news|updates|developments)\b", lower):
        selected.append("manage_monitor")
    if re.search(r"\b(remember that|remember my|save to memory)\b", lower):
        selected.append("save_memory")
    if re.search(r"\b(shut down|shutdown|stop yantra|close assistant|exit assistant)\b", lower):
        selected.append("shutdown_yantra")
    if re.search(r"\b(close|quit|exit|kill)\b", lower) and re.search(_apps, lower):
        selected.append("close_application")

    if re.search(r"\b(cpu|ram|memory|disk|system status|computer|performance|resources)\b", lower):
        selected.append("system_status")

    if re.search(r"\b(list|show|find|what.s in)\b", lower) and re.search(r"\b(files|folders|directory)\b", lower):
        selected.append("list_files")
    if re.search(r"\b(read|summarize|contents of)\b", lower) and re.search(r"\b(file|document|txt)\b", lower):
        selected.append("read_file")
    if re.search(r"\b(write|save|create|make)\b", lower) and re.search(r"\b(file|note|document)\b", lower):
        selected.append("write_file")
    if re.search(r"\b(open|load)\b", lower) and (
        re.search(r"\b(file|folder|document|pdf|workbook|spreadsheet)\b", lower)
        or _WORKBOOK_PATH.search(user_text)
    ):
        selected.append("open_file")

    if re.search(r"\b(move the mouse|move pointer)\b", lower):
        selected.append("move_mouse")
    if re.search(r"\b(double[- ]click)\b", lower):
        selected.append("double_click")
    elif re.search(r"\b(click|tap on)\b", lower):
        selected += ["click_mouse", "hotkey"]
    if re.search(r"\b(type|enter|input)\b", lower) and re.search(r"\b(text|this|into|field)\b", lower):
        selected.append("type_text")
    if re.search(r"\b(press|hit)\b", lower) and re.search(r"\b(key|enter|escape|tab)\b", lower):
        selected.append("press_key")
    if re.search(r"\b(shortcut|hotkey|ctrl|alt)\b", lower):
        selected.append("hotkey")
    if re.search(r"\b(take|grab|save)\b", lower) and re.search(r"\bscreenshot\b", lower):
        selected.append("take_screenshot")
    if re.search(r"\b(active window|current window)\b", lower):
        selected.append("get_active_window")

    tools = [_FUNCTION_TOOLS[n] for n in dict.fromkeys(selected) if n in _FUNCTION_TOOLS]

    # Only add Google Search when user explicitly needs live information
    if _NEEDS_SEARCH.search(text):
        tools.append(_GOOGLE_SEARCH_TOOL)

    return tools


def _is_camera_question(text: str) -> bool:
    asks_to_see = re.search(
        r"\b(who|what|look|see|check|capture|take|analy[sz]e|picture|photo)\b",
        text,
    )
    mentions_camera = re.search(
        r"\b(camera|webcam|in front of me|who can you see|what can you see)\b",
        text,
    )
    return bool(mentions_camera and asks_to_see)


def _search_follow_up(user_text: str) -> tuple[str, str | None] | None:
    normalized = user_text.strip().lower()
    if len(normalized.split()) > 8 or _CONVERSATIONAL_ONLY.match(normalized):
        return None
    history = get_recent_memory()[-6:]
    last_assistant = next(
        (str(item.get("content", "")) for item in reversed(history)
         if isinstance(item, dict) and item.get("role") == "assistant"),
        "",
    ).lower()
    last_user = next(
        (str(item.get("content", "")) for item in reversed(history)
         if isinstance(item, dict) and item.get("role") == "user"),
        "",
    ).lower()
    asked_to_search = any(term in last_assistant for term in (
        "search", "look up", "what are you looking for", "सर्च", "खोज", "ढूंढ", "ढूँढ",
    ))
    recent_search_request = bool(_SEARCH_COMMAND.search(last_user))
    if asked_to_search and recent_search_request:
        browser = "chrome" if "chrome" in last_user or "chrome" in last_assistant else None
        return user_text.strip(), browser
    return None


def _direct_simple_action(user_text: str) -> dict | None:
    normalized = user_text.strip().lower().replace("excell", "excel").replace("serach", "search").replace("serch", "search")

    if re.search(r"\b(excel|spreadsheet|workbook|sheet)\b", normalized) and re.search(
        r"\b(open|launch|start|create|make|new|blank|empty|general|khali|khaali)\b", normalized
    ):
        result = execute_command({"action": "open_blank_excel"})
        message = result.get("message", "Excel could not be opened.")
        if result.get("success"):
            message = (
                "Excel में एक नई खाली workbook खुल गई है। आप अपना काम शुरू कर सकते हैं।"
                if re.search(r"\b(khali|khaali)\b|[\u0900-\u097f]", normalized)
                else "Excel is open with a new blank workbook. You can start working."
            )
        return {
            "success": bool(result.get("success")),
            "message": message,
            "sources": [],
            "actions": [{"action": "open_blank_excel", "result": result}],
        }

    match = _SEARCH_COMMAND.search(normalized)
    search_context = None if match else _search_follow_up(user_text)
    if match:
        query = normalized[match.end():]
        browser = "chrome" if re.search(r"\bchrome\b", normalized) else None
        query = re.sub(r"\s+(?:on|in|using)\s+(?:it|chrome|google|the browser|browser)$", "", query)
        query = query.strip(" \t.,!?\"'")
    elif search_context:
        query, browser = search_context
    else:
        return None

    if not query:
        return None

    actions = []
    if browser == "chrome" and re.search(r"\b(open|launch|start)\s+(?:google\s+)?chrome\b", normalized):
        opened = execute_command({"action": "open_application", "target": "chrome"})
        actions.append({"action": "open_application", "result": opened})
        if not opened.get("success"):
            return {
                "success": False,
                "message": opened.get("message", "Chrome could not be opened."),
                "sources": [],
                "actions": actions,
            }

    search_result = execute_command({
        "action": "web_search",
        "query": query,
        "browser": browser,
    })
    actions.append({"action": "web_search", "result": search_result})
    message = search_result.get("message", "The browser search failed.")
    if search_result.get("success"):
        message = (
            f"Chrome में {query} खोज दिया है।"
            if re.search(r"[\u0900-\u097f]", user_text)
            else f"I searched Google for {query}" + (" in Chrome." if browser == "chrome" else ".")
        )
    return {
        "success": bool(search_result.get("success")),
        "message": message,
        "sources": [],
        "actions": actions,
    }


def _is_blank_excel_follow_up(user_text: str) -> bool:
    normalized = user_text.strip().lower().replace("khaali", "khali")
    if not re.fullmatch(r"(?:khali|blank|empty)(?:\s+(?:excel|sheet|workbook))*", normalized):
        return False
    history = get_recent_memory()[-6:]
    previous = " ".join(
        str(item.get("content", ""))
        for item in history
        if isinstance(item, dict) and item.get("content")
    ).lower().replace("excell", "excel")
    return bool(re.search(r"\b(excel|spreadsheet|workbook)\b", previous))


# ── Persistent Gemini client (created once, reused) ────────────────────────────
_client: Any = None
_groq_client: Any = None


def _get_client() -> Any:
    global _client
    if _client is not None:
        return _client
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Gemini is not configured. Set GEMINI_API_KEY in backend/.env.")
    _client = genai.Client(api_key=api_key)
    print(f"[YANTRA] Gemini client ready. Model: {os.getenv('GEMINI_MODEL', DEFAULT_MODEL)}")
    return _client


def _get_live_client() -> Any:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Gemini is not configured. Set GEMINI_API_KEY in backend/.env.")
    return genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})


def _make_client() -> Any:
    return _get_client()


def _instruction_with_saved_facts(instruction: str) -> str:
    from mark_actions.state import format_saved_memory
    saved_memory = format_saved_memory()
    if saved_memory:
        instruction += f"\n\nSaved user facts:\n{saved_memory}"
    return instruction


def build_live_config(
    system_instruction: str | None = None,
    session_resumption_handle: str | None = None,
) -> types.LiveConnectConfig:
    """Build a native-audio Live config from the assistant's existing tools."""
    instruction = _instruction_with_saved_facts(system_instruction or SYSTEM_INSTRUCTION)

    return types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=instruction,
        tools=[*_FUNCTION_TOOLS.values(), _GOOGLE_SEARCH_TOOL],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon")
            )
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        session_resumption=types.SessionResumptionConfig(handle=session_resumption_handle),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=False,
                start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                prefix_padding_ms=120,
                silence_duration_ms=650,
            ),
            activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
        ),
    )


def _get_groq_client() -> Any:
    global _groq_client
    if _groq_client is not None:
        return _groq_client
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return None
    _groq_client = Groq(api_key=api_key)
    return _groq_client


def _run_groq_fallback(user_text: str, inspect_screen: bool = False, extra_parts=None) -> dict | None:
    if inspect_screen or extra_parts:
        return None

    selected_tools = _select_tools(user_text)
    if any(getattr(tool, "function_declarations", None) for tool in selected_tools):
        return None

    client = _get_groq_client()
    if client is None:
        return None

    messages = [{"role": "system", "content": _instruction_with_saved_facts(SYSTEM_INSTRUCTION)}]
    for item in get_recent_memory():
        if isinstance(item, dict) and item.get("content"):
            role = "assistant" if item.get("role") == "assistant" else "user"
            messages.append({"role": role, "content": item["content"]})
    messages.append({"role": "user", "content": user_text})

    needs_search = bool(_NEEDS_SEARCH.search(user_text))
    request = {
        "model": os.getenv(
            "GROQ_SEARCH_MODEL" if needs_search else "GROQ_MODEL",
            DEFAULT_GROQ_SEARCH_MODEL if needs_search else DEFAULT_GROQ_MODEL,
        ).strip(),
        "messages": messages,
    }
    if needs_search:
        request.update(
            tools=[{"type": "browser_search"}],
            tool_choice="required",
            citation_options="enabled",
        )

    try:
        response = client.chat.completions.create(**request)
        message = response.choices[0].message
        answer = _clean_for_speech(getattr(message, "content", None) or "")
        if not answer:
            raise RuntimeError("Groq returned an empty response.")

        sources = []
        for executed_tool in getattr(message, "executed_tools", None) or []:
            results = list(getattr(executed_tool, "browser_results", None) or [])
            search_results = getattr(executed_tool, "search_results", None)
            results.extend(getattr(search_results, "results", None) or [])
            for result in results:
                url = getattr(result, "url", None)
                if url and not any(source["url"] == url for source in sources):
                    sources.append({"title": getattr(result, "title", None) or url, "url": url})

        add_message("user", user_text)
        add_message("assistant", answer)
        print(f"[YANTRA] Groq fallback response: {answer[:80]!r}")
        return {"success": True, "message": answer, "sources": sources, "actions": []}
    except Exception as error:
        print(f"[YANTRA] Groq fallback failed: {type(error).__name__}: {error}")
        error_text = str(error).lower()
        if needs_search and ("model_not_found" in error_text or "does not exist" in error_text):
            message = (
                "Groq chat is available, but this account cannot access the Compound model "
                "required for live web search. Check Groq model access or use a search-enabled account."
            )
        else:
            message = "Gemini is unavailable and the Groq fallback failed. Check the backend console and Groq account limits."
        return {
            "success": False,
            "message": message,
            "sources": [],
            "actions": [],
        }


# ── Conversation history builder ───────────────────────────────────────────────
def _build_contents(user_text: str, inspect_screen: bool = False, extra_parts=None) -> list:
    history = get_recent_memory()
    contents = []

    for item in history:
        if not isinstance(item, dict) or not item.get("content"):
            continue
        role = "user" if item.get("role") == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part(text=item["content"])]))

    prompt = user_text
    if inspect_screen:
        prompt = f"First call capture_screen to see what is on the screen, then respond to: {user_text}"

    current_parts = [types.Part(text=prompt)]
    if extra_parts:
        current_parts += extra_parts

    contents.append(types.Content(role="user", parts=current_parts))
    return contents


# ── Markdown stripper for spoken output ───────────────────────────────────────
_MD_STRIP    = re.compile(r"(\*{1,3}|_{1,3}|`{1,3}|#{1,6}\s?|>\s?|\[([^\]]+)\]\([^)]+\))")
_BULLET_LINE = re.compile(r"^\s*[-*•]\s+", re.MULTILINE)
_NUM_LINE    = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)


def _clean_for_speech(text: str) -> str:
    text = _MD_STRIP.sub(r"\2", text)
    text = _BULLET_LINE.sub("", text)
    text = _NUM_LINE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


# ── Tool result parts ──────────────────────────────────────────────────────────
def _tool_result_parts(action: str, result: dict) -> list:
    parts = [types.Part.from_function_response(name=action, response=result)]
    if action == "capture_screen":
        image_path = result.get("path")
        if image_path:
            p = Path(image_path)
            if p.is_file() and p.stat().st_size <= 20_000_000:
                mime = mimetypes.guess_type(p.name)[0] or "image/png"
                parts.append(types.Part.from_bytes(data=p.read_bytes(), mime_type=mime))
    return parts


# ── File analysis ──────────────────────────────────────────────────────────────
def analyze_uploaded_files(paths, user_request: str, client=None) -> dict:
    client = client or _get_client()
    uploaded_refs = []
    try:
        file_parts = []
        names = []
        for path in paths:
            path = Path(path)
            names.append(path.name)
            uploaded = client.files.upload(file=str(path))
            uploaded_refs.append(uploaded)
            file_parts.append(types.Part.from_uri(
                file_uri=uploaded.uri,
                mime_type=uploaded.mime_type or "application/octet-stream",
            ))
        prompt = user_request.strip() or "Summarize these files and highlight the most important details."
        prompt = f"Files: {', '.join(names)}\nRequest: {prompt}"
        return run_assistant(prompt, client=client, extra_parts=file_parts)
    finally:
        for ref in uploaded_refs:
            try:
                client.files.delete(name=ref.name)
            except Exception:
                pass


# ── Main entry point ───────────────────────────────────────────────────────────
def run_assistant(
    user_text: str,
    client: Any | None = None,
    inspect_screen: bool = False,
    extra_parts=None,
) -> dict:
    """
    Run one conversational turn with retry logic for 503 transient errors.
    Always returns a dict: {success, message, sources, actions}
    """
    user_text = user_text.strip()
    if not user_text:
        return {"success": False, "message": "I didn't catch that.", "sources": [], "actions": []}

    original_user_text = user_text
    if _WORKBOOK_REQUEST.search(user_text) and not _WORKBOOK_PATH.search(user_text):
        return {
            "success": True,
            "message": "Which Excel workbook should I open? Give me its filename or full path.",
            "sources": [],
            "actions": [],
        }

    direct_result = _direct_simple_action(user_text)
    if direct_result is None and _is_blank_excel_follow_up(user_text):
        excel_result = execute_command({"action": "open_blank_excel"})
        message = excel_result.get("message", "Could not create a blank Excel workbook.")
        if excel_result.get("success"):
            message = (
                "Excel में एक नई खाली workbook खुल गई है। आप अपना काम शुरू कर सकते हैं।"
                if re.search(r"[\u0900-\u097f]|\b(khali|khaali)\b", user_text.lower())
                else "Excel is open with a new blank workbook. You can start working."
            )
        direct_result = {
            "success": bool(excel_result.get("success")),
            "message": message,
            "sources": [],
            "actions": [{"action": "open_blank_excel", "result": excel_result}],
        }
    if direct_result is not None:
        add_message("user", original_user_text)
        add_message("assistant", direct_result["message"])
        return direct_result

    if not os.getenv("GEMINI_API_KEY", "").strip():
        groq_result = _run_groq_fallback(user_text, inspect_screen, extra_parts)
        if groq_result is not None:
            return groq_result
        return {
            "success": False,
            "message": "Set GEMINI_API_KEY for desktop, screen, and file operations, or GROQ_API_KEY for chat and live-news responses, in backend/.env.",
            "sources": [],
            "actions": [],
        }

    initial_actions = []
    if _is_camera_question(user_text.lower()):
        capture = execute_command({"action": "capture_screen", "source": "camera"})
        if not capture.get("success"):
            return {
                "success": False,
                "message": capture.get("message", "Could not capture a webcam frame."),
                "sources": [],
                "actions": [{"action": "capture_screen", "result": capture}],
            }
        image_path = Path(capture.get("path", ""))
        if not image_path.is_file():
            return {
                "success": False,
                "message": "The webcam capture did not produce an image to analyze.",
                "sources": [],
                "actions": [{"action": "capture_screen", "result": capture}],
            }
        image_mime = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
        extra_parts = list(extra_parts or []) + [
            types.Part.from_bytes(data=image_path.read_bytes(), mime_type=image_mime)
        ]
        initial_actions.append({"action": "capture_screen", "result": capture})
        user_text = (
            "The attached image is one webcam frame captured just now. "
            "Answer the user's request based only on what is visible in that image. "
            "If no person is clearly visible, say so. Do not claim you lack camera access. "
            f"User request: {original_user_text}"
        )

    last_error = None
    # Build list of models to try: env override first, then fallbacks
    env_model  = os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip()
    model_queue = [env_model] + [m for m in FALLBACK_MODELS if m != env_model]

    for model in model_queue:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                c     = client or _get_client()
                tools = _select_tools(user_text, inspect_screen)
                if initial_actions:
                    tools = [
                        tool for tool in tools
                        if not any(
                            declaration.name == "capture_screen"
                            for declaration in (tool.function_declarations or [])
                        )
                    ]

                config = types.GenerateContentConfig(
                    system_instruction=_instruction_with_saved_facts(SYSTEM_INSTRUCTION),
                    tools=tools if tools else None,
                    tool_config=types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(mode="AUTO")
                    ) if tools else None,
                )

                contents  = _build_contents(user_text, inspect_screen, extra_parts)
                actions:  list = list(initial_actions)
                sources:  list = []
                candidate = None

                for _round in range(MAX_TOOL_ROUNDS):
                    print(f"[YANTRA] generate_content model={model} attempt={attempt} round={_round+1} query={user_text[:40]!r}")
                    response  = c.models.generate_content(model=model, contents=contents, config=config)
                    candidate = (response.candidates or [None])[0]

                    if not candidate:
                        print("[YANTRA] No candidate in response.")
                        break

                    # Collect grounding sources
                    grounding = getattr(candidate, "grounding_metadata", None)
                    if grounding:
                        for chunk in getattr(grounding, "grounding_chunks", None) or []:
                            web = getattr(chunk, "web", None)
                            if web and getattr(web, "uri", None):
                                uri   = web.uri
                                title = getattr(web, "title", None) or uri
                                if not any(s["url"] == uri for s in sources):
                                    sources.append({"title": title, "url": uri})

                    # Any function calls?
                    fn_calls = [
                        part.function_call
                        for part in (candidate.content.parts or [])
                        if getattr(part, "function_call", None)
                    ]

                    if not fn_calls or len(actions) >= MAX_TOOL_CALLS:
                        break   # text response ready

                    # Execute tools
                    contents.append(candidate.content)
                    tool_parts: list = []
                    for fn_call in fn_calls:
                        if len(actions) >= MAX_TOOL_CALLS:
                            break
                        aname   = fn_call.name
                        args    = dict(fn_call.args or {})
                        cmd     = {"_tool_name": aname, **args}
                        result  = execute_command(cmd)
                        actions.append({"action": aname, "result": result})
                        tool_parts.extend(_tool_result_parts(aname, result))
                    contents.append(types.Content(role="user", parts=tool_parts))

                # Build answer text
                answer = ""
                if candidate and candidate.content and candidate.content.parts:
                    answer = " ".join(
                        p.text for p in candidate.content.parts if getattr(p, "text", None)
                    ).strip()

                if not answer and len(actions) >= MAX_TOOL_CALLS:
                    answer = "Done. I have hit the action limit for this turn."
                if not answer:
                    answer = "I was not able to form a response. Please try again."

                failed_actions = [
                    action for action in actions
                    if not action.get("result", {}).get("success", False)
                ]
                action_success = not failed_actions
                if failed_actions:
                    details = " ".join(
                        action["result"].get("message", "The requested action failed.")
                        for action in failed_actions
                    )
                    answer = f"I couldn't complete that. {details}"
                elif not actions and _UNVERIFIED_ACTION_CLAIM.search(answer):
                    action_success = False
                    answer = "I haven't performed that action. Tell me the app name or the exact file path, and I'll try again."
                elif (
                    _WORKBOOK_REQUEST.search(user_text)
                    and not any(action.get("action") == "open_file" for action in actions)
                ):
                    action_success = False
                    answer = "I did not open a workbook. Tell me the workbook's full path and I'll try again."

                answer = _clean_for_speech(answer)
                print(f"[YANTRA] Response ({model}): {answer[:80]!r}")

                add_message("user", original_user_text)
                add_message("assistant", answer)
                return {"success": action_success, "message": answer, "sources": sources, "actions": actions}

            except Exception as error:
                last_error  = error
                error_text  = str(error).lower()
                print(f"[YANTRA] {model} failed: {type(error).__name__}: {error}")

                # If quota, 503 high demand, or model not found -> immediately try next fallback model
                if ("503" in error_text or "unavailable" in error_text or "high demand" in error_text
                        or "429" in error_text or "resource_exhausted" in error_text
                        or "quota" in error_text or "not found" in error_text or "no longer available" in error_text):
                    print(f"[YANTRA] {model} unavailable/quota hit, switching to next fallback...")
                    break   # break inner retry loop -> next model immediately

                # Non-retryable configuration errors
                if "not configured" in error_text:
                    msg = str(error)
                    return {"success": False, "message": msg, "sources": [], "actions": []}
                elif "401" in error_text or "api key" in error_text or "unauthorized" in error_text:
                    groq_result = _run_groq_fallback(user_text, inspect_screen, extra_parts)
                    if groq_result is not None:
                        return groq_result
                    msg = "API key rejected. Check GEMINI_API_KEY in backend/.env."
                    return {"success": False, "message": msg, "sources": [], "actions": []}
                
                break

    # All models and retries exhausted
    print(f"[YANTRA] All models failed. Last error: {last_error}")
    groq_result = _run_groq_fallback(user_text, inspect_screen, extra_parts)
    if groq_result is not None:
        return groq_result

    error_text = str(last_error).lower()
    if any(term in error_text for term in ("429", "resource_exhausted", "quota")):
        message = (
            "Gemini's request quota for this Google AI Studio project has been reached. "
            "Check the project's usage limits and billing, or retry after the quota resets. "
            "Creating another API key in the same project will not reset its quota. "
            "Set GROQ_API_KEY in backend/.env to enable the chat and live-news fallback."
        )
    else:
        message = (
            "Gemini could not complete the request with the configured models. "
            "Check the backend console for the detailed error, then verify the model, API key, and connection."
        )
    return {"success": False, "message": message, "sources": [], "actions": []}
