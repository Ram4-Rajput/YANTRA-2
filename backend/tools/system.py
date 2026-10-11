import psutil


def get_system_status(target=None):

    try:

        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        message = (
            f"CPU: {cpu}% | "
            f"RAM: {ram.percent}% used ({ram.available // (1024**2)} MB free) | "
            f"Disk: {disk.percent}% used ({disk.free // (1024**3)} GB free)"
        )

        return {
            "success": True,
            "message": message
        }

    except Exception as e:

        return {
            "success": False,
            "message": f"Could not get system status: {e}"
        }
