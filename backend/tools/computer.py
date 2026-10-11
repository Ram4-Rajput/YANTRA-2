import pyautogui
import pygetwindow as gw


def move_mouse(target):

    try:

        if not target:

            return {
                "success": False,
                "message": "Mouse coordinates were not provided."
            }

        x, y = map(
            int,
            target.split(",")
        )

        pyautogui.moveTo(
            x,
            y,
            duration=0.3
        )

        return {
            "success": True,
            "message": f"Mouse moved to {x}, {y}."
        }

    except Exception as e:

        return {
            "success": False,
            "message": f"Could not move mouse: {e}"
        }


def click_mouse(target=None):

    try:

        if target:

            x, y = map(
                int,
                target.split(",")
            )

            pyautogui.click(
                x,
                y
            )

            return {
                "success": True,
                "message": f"Clicked at {x}, {y}."
            }

        pyautogui.click()

        return {
            "success": True,
            "message": "Mouse clicked."
        }

    except Exception as e:

        return {
            "success": False,
            "message": f"Could not click mouse: {e}"
        }


def double_click(target=None):

    try:

        if target:

            x, y = map(
                int,
                target.split(",")
            )

            pyautogui.doubleClick(
                x,
                y
            )

        else:

            pyautogui.doubleClick()

        return {
            "success": True,
            "message": "Double click completed."
        }

    except Exception as e:

        return {
            "success": False,
            "message": f"Could not double click: {e}"
        }


def type_text(text):

    try:

        if not text:

            return {
                "success": False,
                "message": "No text was provided."
            }

        pyautogui.write(
            text,
            interval=0.01
        )

        return {
            "success": True,
            "message": "Text typed successfully."
        }

    except Exception as e:

        return {
            "success": False,
            "message": f"Could not type text: {e}"
        }


def press_key(key):

    try:

        if not key:

            return {
                "success": False,
                "message": "No key was provided."
            }

        pyautogui.press(
            key
        )

        return {
            "success": True,
            "message": f"Pressed {key}."
        }

    except Exception as e:

        return {
            "success": False,
            "message": f"Could not press key: {e}"
        }


def hotkey(keys):

    try:

        if not keys:

            return {
                "success": False,
                "message": "No hotkey was provided."
            }

        key_list = [
            key.strip()
            for key in keys.split("+")
        ]

        pyautogui.hotkey(
            *key_list
        )

        return {
            "success": True,
            "message": (
                f"Pressed {' + '.join(key_list)}."
            )
        }

    except Exception as e:

        return {
            "success": False,
            "message": f"Could not execute hotkey: {e}"
        }


def take_screenshot(
    path="screenshot.png"
):

    try:

        screenshot = pyautogui.screenshot()

        screenshot.save(
            path
        )

        return {
            "success": True,
            "message": f"Screenshot saved to {path}."
        }

    except Exception as e:

        return {
            "success": False,
            "message": f"Could not take screenshot: {e}"
        }


def get_active_window():

    try:

        window = gw.getActiveWindow()

        if window is None:

            return {
                "success": False,
                "message": "No active window detected."
            }

        return {
            "success": True,
            "message": (
                f"Active window: {window.title}"
            )
        }

    except Exception as e:

        return {
            "success": False,
            "message": (
                f"Could not detect active window: {e}"
            )
        }