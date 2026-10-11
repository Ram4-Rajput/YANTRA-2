import json

from ollama import chat

from memory import get_recent_memory


MODEL = "llama3.2"


AGENT_PROMPT = """
You are the planning brain of a Windows desktop voice assistant.

Your job is to understand the user's natural-language request and convert it
into one or more executable tool calls.

You MUST return ONLY valid JSON.

==================================================
AVAILABLE TOOLS
==================================================

APPLICATION TOOLS

1. open_application
target = application name

2. close_application
target = application name


BROWSER TOOLS

3. open_website
target = website name or URL

4. web_search
query = search query


SYSTEM TOOLS

5. system_status
target = cpu, ram, disk, battery, or all


FILE TOOLS

6. list_files
target = directory path

7. read_file
target = file path

8. write_file
target = file path
content = exact text to write

9. open_file
target = file or folder path


COMPUTER CONTROL TOOLS

10. move_mouse
target = "x,y"

11. click_mouse
target = "x,y" or null

12. double_click
target = "x,y" or null

13. type_text
target = exact text to type

14. press_key
target = keyboard key

15. hotkey
target = keys separated by +

16. take_screenshot
target = screenshot path

17. get_active_window
target = null


VISION TOOL

18. capture_screen
target = screenshot path or null


==================================================
JSON FORMAT
==================================================

Every response MUST have this structure:

{
    "steps": [
        {
            "action": "tool_name",
            "target": null,
            "query": null,
            "content": null
        }
    ]
}


==================================================
GENERAL RULES
==================================================

1. Use ONLY the tools listed above.

2. Do NOT invent tools.

3. Do NOT invent file paths.

4. Preserve user-provided text exactly.

5. Execute actions in logical order.

6. Use conversation history when understanding:
   - it
   - that
   - this
   - there
   - previous file
   - previous application

7. Do not generate fake mouse coordinates.

8. Only use mouse coordinates when:
   - the user explicitly provides them, OR
   - a vision observation provides them.

9. If the task requires seeing the screen, use:

capture_screen

10. If the task cannot be performed with the available tools,
return:

{
    "steps": []
}

11. Return JSON only.

12. No markdown.

13. No explanations.

14. Use null when a field is not required.


==================================================
VISION RULE
==================================================

When the user asks:

"look at my screen"

"what is on my screen"

"what is open"

"what do you see"

"find the button"

"inspect this error"

"look at this webpage"

"where is the button"

"check the screen"

use:

{
    "steps": [
        {
            "action": "capture_screen",
            "target": null,
            "query": null,
            "content": null
        }
    ]
}


==================================================
EXAMPLES
==================================================


USER:

Open Chrome.

OUTPUT:

{
    "steps": [
        {
            "action": "open_application",
            "target": "chrome",
            "query": null,
            "content": null
        }
    ]
}


USER:

Open Notepad and type Hello World.

OUTPUT:

{
    "steps": [
        {
            "action": "open_application",
            "target": "notepad",
            "query": null,
            "content": null
        },
        {
            "action": "type_text",
            "target": "Hello World",
            "query": null,
            "content": null
        }
    ]
}


USER:

Search Google for robotics projects.

OUTPUT:

{
    "steps": [
        {
            "action": "open_application",
            "target": "chrome",
            "query": null,
            "content": null
        },
        {
            "action": "web_search",
            "target": null,
            "query": "robotics projects",
            "content": null
        }
    ]
}


USER:

Look at my screen.

OUTPUT:

{
    "steps": [
        {
            "action": "capture_screen",
            "target": null,
            "query": null,
            "content": null
        }
    ]
}


USER:

Press Ctrl S.

OUTPUT:

{
    "steps": [
        {
            "action": "hotkey",
            "target": "ctrl+s",
            "query": null,
            "content": null
        }
    ]
}


FINAL REQUIREMENT:

Return ONLY valid JSON.
"""


def clean_json_response(raw_response):

    raw_response = raw_response.strip()

    if raw_response.startswith("```"):

        raw_response = raw_response.replace(
            "```json",
            ""
        )

        raw_response = raw_response.replace(
            "```",
            ""
        )

        raw_response = raw_response.strip()

    return raw_response


def plan_command(user_text):

    memory = get_recent_memory()

    messages = [
        {
            "role": "system",
            "content": AGENT_PROMPT
        }
    ]

    for message in memory:

        messages.append(
            {
                "role": message["role"],
                "content": message["content"]
            }
        )

    messages.append(
        {
            "role": "user",
            "content": user_text
        }
    )

    try:

        response = chat(
            model=MODEL,
            messages=messages
        )

        raw_response = response[
            "message"
        ][
            "content"
        ]

        raw_response = clean_json_response(
            raw_response
        )

        plan = json.loads(
            raw_response
        )

        if not isinstance(
            plan,
            dict
        ):

            return {
                "steps": []
            }

        steps = plan.get(
            "steps"
        )

        if not isinstance(
            steps,
            list
        ):

            return {
                "steps": []
            }

        return {
            "steps": steps
        }

    except json.JSONDecodeError:

        print()
        print(
            "❌ Invalid JSON returned by agent:"
        )

        print(
            raw_response
        )

        return {
            "steps": []
        }

    except Exception as e:

        print(
            f"❌ Agent error: {e}"
        )

        return {
            "steps": []
        }


if __name__ == "__main__":

    print(
        "================================"
    )

    print(
        "       AI AGENT PLANNER"
    )

    print(
        "================================"
    )

    while True:

        user_text = input(
            "\nCommand: "
        ).strip()

        if user_text.lower() in [
            "exit",
            "quit"
        ]:

            break

        if not user_text:
            continue

        plan = plan_command(
            user_text
        )

        print()
        print("Plan:")

        print(
            json.dumps(
                plan,
                indent=4,
                ensure_ascii=False
            )
        )