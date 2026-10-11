from pathlib import Path
import os
import subprocess


def list_files(path="."):
    """List files and folders in a directory."""

    try:
        directory = Path(path).expanduser().resolve()

        if not directory.exists():
            return {
                "success": False,
                "message": f"The path {path} does not exist."
            }

        if not directory.is_dir():
            return {
                "success": False,
                "message": f"{path} is not a folder."
            }

        items = []

        for item in directory.iterdir():
            if item.is_dir():
                items.append(f"[FOLDER] {item.name}")
            else:
                items.append(f"[FILE] {item.name}")

        if not items:
            return {
                "success": True,
                "message": f"{directory} is empty."
            }

        return {
            "success": True,
            "message": (
                f"Contents of {directory}:\n"
                + "\n".join(items)
            )
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Could not list files: {e}"
        }


def read_file(path):
    """Read a text file."""

    try:
        file_path = Path(path).expanduser().resolve()

        if not file_path.exists():
            return {
                "success": False,
                "message": f"File not found: {path}"
            }

        if not file_path.is_file():
            return {
                "success": False,
                "message": f"{path} is not a file."
            }

        # Safety limit for the first version
        if file_path.stat().st_size > 1_000_000:
            return {
                "success": False,
                "message": "File is too large to read directly."
            }

        content = file_path.read_text(
            encoding="utf-8",
            errors="replace"
        )

        return {
            "success": True,
            "message": content
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Could not read file: {e}"
        }


def write_file(path, content):
    """Create or overwrite a text file."""

    try:
        file_path = Path(path).expanduser().resolve()

        file_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        file_path.write_text(
            content,
            encoding="utf-8"
        )

        return {
            "success": True,
            "message": f"File created successfully: {file_path}"
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Could not write file: {e}"
        }


def open_file(path):
    """Open a file or folder using Windows."""

    try:
        target = Path(path).expanduser().resolve()

        if not target.exists():
            return {
                "success": False,
                "message": f"Path not found: {path}"
            }

        os.startfile(str(target))

        return {
            "success": True,
            "message": f"Opened {target}"
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Could not open {path}: {e}"
        }