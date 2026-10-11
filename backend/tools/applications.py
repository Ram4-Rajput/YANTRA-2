import os
import subprocess


APPLICATIONS = {
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "google chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",

    "notepad": "notepad.exe",
    "notepad.exe": "notepad.exe",

    "calculator": "calc.exe",
    "calc": "calc.exe",

    "cmd": "cmd.exe",

    "powershell": "powershell.exe",
    "windows powershell": "powershell.exe",
    "excel": "excel.exe",
    "microsoft excel": "excel.exe",
}


def open_application(application):

    application = application.lower().strip()

    if application in {"camera", "windows camera"}:
        try:
            os.startfile("microsoft.windows.camera:")
            return {"success": True, "message": "Windows Camera opened."}
        except Exception as error:
            return {"success": False, "message": f"Could not open Windows Camera: {error}"}

    if application not in APPLICATIONS:
        return {
            "success": False,
            "message": f"I don't know how to open {application}."
        }

    try:

        subprocess.Popen(APPLICATIONS[application])

        return {
            "success": True,
            "message": f"{application} opened successfully."
        }

    except Exception as e:

        return {
            "success": False,
            "message": f"Failed to open {application}: {e}"
        }


def close_application(application):

    application = application.lower().strip()

    process_map = {
        "chrome": "chrome.exe",
        "google chrome": "chrome.exe",
        "notepad": "notepad.exe",
        "calculator": "CalculatorApp.exe",
        "calc": "CalculatorApp.exe",
    }

    process = process_map.get(application)

    if not process:

        return {
            "success": False,
            "message": f"I don't know how to close {application}."
        }

    try:

        subprocess.run(
            ["taskkill", "/F", "/IM", process],
            capture_output=True,
            text=True
        )

        return {
            "success": True,
            "message": f"{application} closed successfully."
        }

    except Exception as e:

        return {
            "success": False,
            "message": f"Failed to close {application}: {e}"
        }


def open_blank_excel():
    """Create and show a genuinely new blank Excel workbook through COM."""
    initialized_com = False
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        initialized_com = True
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = True
        workbook = excel.Workbooks.Add()
        workbook.Activate()
        return {
            "success": True,
            "message": "A new blank Excel workbook is open.",
        }
    except Exception as error:
        return {
            "success": False,
            "message": f"Could not create a blank Excel workbook: {error}",
        }
    finally:
        if initialized_com:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass