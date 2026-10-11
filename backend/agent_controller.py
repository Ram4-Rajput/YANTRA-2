import json

from ollama import chat

from agent import plan_command
from execute import execute_plan
from vision_control import observe_screen
from memory import add_message


MODEL = "llama3.2"

MAX_AGENT_ITERATIONS = 5


def extract_results(execution_results):

    messages = []

    for item in execution_results:

        action = item.get(
            "action"
        )

        result = item.get(
            "result",
            {}
        )

        message = result.get(
            "message",
            ""
        )

        if message:

            messages.append(
                f"{action}: {message}"
            )

    return "\n".join(
        messages
    )


def plan_requires_vision(plan):

    for step in plan.get(
        "steps",
        []
    ):

        if step.get(
            "action"
        ) == "capture_screen":

            return True

    return False


def clean_json_response(raw):

    raw = raw.strip()

    if raw.startswith("```"):

        raw = raw.replace(
            "```json",
            ""
        )

        raw = raw.replace(
            "```",
            ""
        )

        raw = raw.strip()

    return raw


def ask_after_observation(
    user_request,
    observation
):

    prompt = f"""
You are controlling a Windows desktop.

The user's original request was:

{user_request}


CURRENT SCREEN OBSERVATION:

{observation}


AVAILABLE TOOLS:

- open_application
- close_application
- open_website
- web_search
- system_status
- list_files
- read_file
- write_file
- open_file
- move_mouse
- click_mouse
- double_click
- type_text
- press_key
- hotkey
- take_screenshot
- get_active_window
- capture_screen


YOUR TASK:

Decide what should happen next.

Return ONLY JSON:

{{
    "steps": [
        {{
            "action": "click_mouse",
            "target": "500,300",
            "query": null,
            "content": null
        }}
    ]
}}


RULES:

1. Use only the available tools.

2. Do not invent coordinates.

3. Only click coordinates that are reasonably identified
   in the screen observation.

4. If the user's task is complete, return:

{{
    "steps": []
}}

5. If another screen observation is required, use:

capture_screen

6. JSON only.

7. No markdown.

8. No explanation outside JSON.
"""

    try:

        response = chat(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": prompt
                }
            ]
        )

        raw = response[
            "message"
        ][
            "content"
        ]

        raw = clean_json_response(
            raw
        )

        plan = json.loads(
            raw
        )

        if not isinstance(
            plan,
            dict
        ):

            return {
                "steps": []
            }

        if not isinstance(
            plan.get("steps"),
            list
        ):

            return {
                "steps": []
            }

        return plan

    except Exception as e:

        print(
            f"❌ Observation planning error: {e}"
        )

        return {
            "steps": []
        }


def run_agent(user_request):

    print()
    print(
        "================================"
    )
    print(
        "        DESKTOP AGENT"
    )
    print(
        "================================"
    )

    print(
        f"\nUser: {user_request}"
    )

    # Save user request
    add_message(
        "user",
        user_request
    )

    # Initial planning
    current_plan = plan_command(
        user_request
    )

    final_messages = []

    for iteration in range(
        MAX_AGENT_ITERATIONS
    ):

        print()
        print(
            f"========== ITERATION "
            f"{iteration + 1} =========="
        )

        # Nothing to execute
        if not current_plan.get(
            "steps"
        ):

            break

        print()
        print("Plan:")

        print(
            json.dumps(
                current_plan,
                indent=4,
                ensure_ascii=False
            )
        )

        # ==========================================
        # VISION
        # ==========================================

        if plan_requires_vision(
            current_plan
        ):

            print()
            print(
                "👁 Capturing screen..."
            )

            observation = observe_screen(
                user_request
            )

            if not observation.get(
                "success",
                False
            ):

                error_message = observation.get(
                    "message",
                    "Vision failed."
                )

                final_messages.append(
                    error_message
                )

                break

            vision_message = observation.get(
                "message",
                ""
            )

            print()
            print(
                "👁 Vision observation:"
            )

            print(
                vision_message
            )

            # Give observation back to Llama
            current_plan = ask_after_observation(
                user_request,
                vision_message
            )

            continue

        # ==========================================
        # NORMAL TOOL EXECUTION
        # ==========================================

        execution_results = execute_plan(
            current_plan
        )

        result_text = extract_results(
            execution_results
        )

        if result_text:

            final_messages.append(
                result_text
            )

        # Stop if something failed
        failed = False

        for item in execution_results:

            result = item.get(
                "result",
                {}
            )

            if not result.get(
                "success",
                False
            ):

                failed = True

                break

        if failed:

            break

        # Current plan finished
        break

    # ==========================================
    # FINAL RESPONSE
    # ==========================================

    if final_messages:

        response_text = "\n".join(
            final_messages
        )

    else:

        response_text = (
            "I couldn't complete that request."
        )

    add_message(
        "assistant",
        response_text
    )

    return {
        "success": True,
        "message": response_text
    }


if __name__ == "__main__":

    print(
        "================================"
    )

    print(
        "       DESKTOP AGENT"
    )

    print(
        "================================"
    )

    while True:

        request = input(
            "\nCommand: "
        ).strip()

        if request.lower() in [
            "exit",
            "quit"
        ]:

            break

        if not request:

            continue

        result = run_agent(
            request
        )

        print()
        print(
            "Assistant:"
        )

        print(
            result.get(
                "message",
                "No response."
            )
        )