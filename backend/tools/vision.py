import base64
from pathlib import Path

import mss
from PIL import Image


SCREENSHOT_PATH = Path(__file__).parent.parent / "screen.png"


def capture_screen(path=None, source="screen", camera_index=0):
    """
    Capture the primary monitor or one webcam frame and save it as an image.
    """

    try:
        if str(source).strip().lower() in {"camera", "webcam"}:
            import cv2

            camera = cv2.VideoCapture(int(camera_index))
            try:
                if not camera.isOpened():
                    return {"success": False, "message": "Could not open the camera."}
                captured, frame = camera.read()
                if not captured:
                    return {"success": False, "message": "Could not capture a camera frame."}
                if path is None:
                    path = Path(__file__).parent.parent / "uploads" / "camera_capture.jpg"
                path = Path(path)
                path.parent.mkdir(parents=True, exist_ok=True)
                if not cv2.imwrite(str(path), frame):
                    return {"success": False, "message": "Could not save the camera frame."}
                return {
                    "success": True,
                    "message": f"Camera frame captured: {path}",
                    "path": str(path),
                }
            finally:
                camera.release()

        if path is None:
            path = SCREENSHOT_PATH

        path = Path(path)

        # Make sure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        with mss.mss() as screen:

            # Monitor 1 = primary monitor
            monitor = screen.monitors[1]

            screenshot = screen.grab(monitor)

            image = Image.frombytes(
                "RGB",
                screenshot.size,
                screenshot.rgb
            )

            image.save(path)

        return {
            "success": True,
            "message": f"Screenshot captured: {path}",
            "path": str(path)
        }

    except Exception as e:

        return {
            "success": False,
            "message": f"Could not capture screen: {e}"
        }


def encode_image(path):
    """
    Convert an image into base64.
    """

    try:

        path = Path(path)

        if not path.exists():

            return {
                "success": False,
                "message": f"Image not found: {path}"
            }

        image_bytes = path.read_bytes()

        encoded = base64.b64encode(
            image_bytes
        ).decode("utf-8")

        return {
            "success": True,
            "data": encoded
        }

    except Exception as e:

        return {
            "success": False,
            "message": f"Could not encode image: {e}"
        }