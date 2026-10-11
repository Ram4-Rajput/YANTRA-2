from pathlib import Path

from tools.vision import capture_screen
from vision_agent import analyze_screen


SCREENSHOT_PATH = (
    Path(__file__).parent
    / "screen.png"
)


def observe_screen(question):

    # Capture screen
    capture_result = capture_screen(
        SCREENSHOT_PATH
    )

    if not capture_result.get(
        "success",
        False
    ):

        return {
            "success": False,
            "message": capture_result.get(
                "message",
                "Could not capture screen."
            )
        }

    # Analyze screenshot
    vision_result = analyze_screen(
        SCREENSHOT_PATH,
        question
    )

    return vision_result


if __name__ == "__main__":

    print(
        "================================"
    )

    print(
        "       VISION CONTROLLER"
    )

    print(
        "================================"
    )

    question = input(
        "\nWhat should I look for? "
    ).strip()

    if not question:

        question = (
            "Describe everything visible "
            "on the screen."
        )

    result = observe_screen(
        question
    )

    print()
    print(
        "Vision result:"
    )

    print(
        result.get(
            "message",
            "No result."
        )
    )