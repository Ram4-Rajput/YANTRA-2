import os
import platform


def get_os() -> str:
    configured = os.getenv("OS_SYSTEM", "").strip().lower()
    if configured in {"windows", "mac", "linux"}:
        return configured
    return {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}.get(
        platform.system(), "linux"
    )


def is_windows() -> bool:
    return get_os() == "windows"


def is_mac() -> bool:
    return get_os() == "mac"


def is_linux() -> bool:
    return get_os() == "linux"


def get_config() -> dict:
    return {"os_system": get_os()}