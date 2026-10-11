import subprocess
import webbrowser
from urllib.parse import quote_plus


WEBSITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "github": "https://github.com",
    "chatgpt": "https://chatgpt.com",
    "espn": "https://www.espn.com",
}


def open_website(website):

    website = website.lower().strip()

    if website in WEBSITES:

        webbrowser.open(WEBSITES[website])

        return {
            "success": True,
            "message": f"Opening {website}."
        }

    # Allow direct URLs
    if website.startswith("http://") or website.startswith("https://"):

        webbrowser.open(website)

        return {
            "success": True,
            "message": f"Opening {website}."
        }

    # Allow www addresses
    if website.startswith("www."):

        url = "https://" + website

        webbrowser.open(url)

        return {
            "success": True,
            "message": f"Opening {website}."
        }

    return {
        "success": False,
        "message": f"I don't know that website: {website}."
    }


def web_search(query, browser=None):

    if not query:

        return {
            "success": False,
            "message": "No search query was provided."
        }

    url = (
        "https://www.google.com/search?q="
        + quote_plus(query)
    )

    if str(browser or "").strip().lower() in {"chrome", "google chrome"}:
        from tools.applications import APPLICATIONS

        subprocess.Popen([APPLICATIONS["chrome"], url])
    elif not webbrowser.open(url):
        return {
            "success": False,
            "message": "The browser could not open the search results.",
        }

    return {
        "success": True,
        "message": f"Searching for {query}."
    }