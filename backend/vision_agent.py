import base64
from pathlib import Path

from ollama import chat


MODEL = "qwen2.5vl:3b"


VISION_PROMPT = """
You are the vision system of a Windows desktop AI assistant.

Analyze the provided screenshot accurately.

Identify visible:

- applications
- windows
- buttons
- menus
- dialogs
- text
- icons
- browser pages
- input fields
- error messages
- UI elements
- important controls

Do not invent elements that are not visible.

If the user asks about a specific element, focus on that element.

When a clickable element is visible and its approximate location can be
determined reliably, provide approximate screen coordinates.

Use:

Element: <description>
Approximate position: (x, y)

Only provide coordinates when reasonably visible.

Be concise and factual.
"""


def analyze_screen(
    image_path,
    user_question
):

    image_path = Path(
        image_path
    )

    if not image_path.exists():

        return {
            "success": False,
            "message": (
                f"Screenshot not found: "
                f"{image_path}"
            )
        }

    try:

        image_data = base64.b64encode(
            image_path.read_bytes()
        ).decode(
            "utf-8"
        )

        response = chat(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": VISION_PROMPT
                },
                {
                    "role": "user",
                    "content": user_question,
                    "images": [
                        image_data
                    ]
                }
            ]
        )

        answer = response[
            "message"
        ][
            "content"
        ].strip()

        return {
            "success": True,
            "message": answer
        }

    except Exception as e:

        return {
            "success": False,
            "message": (
                f"Vision analysis failed: {e}"
            )
        }


if __name__ == "__main__":

    screenshot = (
        Path(__file__).parent
        / "screen.png"
    )

    result = analyze_screen(
        screenshot,
        "Describe what is visible on the screen."
    )

    print(
        result.get(
            "message",
            "No result."
        )
    )