# YANTRA Assistant Setup

## Install

From the workspace root, install the dashboard, Gemini, desktop-tool, and voice dependencies:

```powershell
python -m pip install -r backend/requirements-assistant.txt
```

Copy `backend/.env.example` to `backend/.env`, then set your Google AI Studio and Groq keys:

```text
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-3.8-flash
GEMINI_LIVE_MODEL=models/gemini-2.5-flash-native-audio-preview-12-2025
GROQ_API_KEY=your_groq_key_here
GROQ_MODEL=openai/gpt-oss-20b
GROQ_SEARCH_MODEL=compound-beta
```

Keep `backend/.env` private. The app reads the key on startup and never sends it to the browser or writes it to conversation memory.

## Run

```powershell
python backend/ui_server.py
```

Open <http://127.0.0.1:5000>. The desktop-control server binds to localhost only. Typed requests use Gemini first and fall back to Groq when Gemini is unavailable. Groq chat uses `GROQ_MODEL`; live web search requires Compound access through `GROQ_SEARCH_MODEL`. Desktop, screen, and file operations require Gemini and use the registered local tools.

## Voice And Files

Select **MICROPHONE READY** to start a Gemini Live session and allow microphone access. Speak naturally; the session stays open for follow-up turns and uses native audio, server voice-activity detection, and interruption handling. The Live voice mode requires `GEMINI_API_KEY` and `GEMINI_LIVE_MODEL`. Typed replies use Gemini 3.8 TTS with the Charon voice and expressive delivery metadata; pyttsx3 remains the local fallback. Whisper remains available for non-Live transcription.

Uploaded files are sent to Gemini for analysis. Local temporary copies are removed after the request; uploaded Gemini files are deleted after processing where the API allows it. Do not upload private material unless you are comfortable sending it to Google.

Gemini and Groq requests are subject to their respective project limits and billing.

## Automation

Typed requests and Gemini Live voice share the same desktop-action handlers. The expanded tool set includes browser interaction, file management and processing, computer settings, code assistance, game updates, reminders, messaging, YouTube, flight search, and weather lookup. Voice mode supports barge-in, reconnects, saved user facts, opt-in daily topic monitoring, and context-aware check-ins after extended silence. Screen capture and one-frame webcam capture are available; webcam capture releases the device immediately afterward.

Voice starts from the microphone button or **VOICE MODE** control. **AUTO LISTEN** is an explicit opt-in and remembers that choice in the browser; when enabled, it starts Live voice on later dashboard visits if Gemini is configured.

Install the Playwright browser runtime once if browser interactions need it:

```powershell
python -m playwright install chromium
```

Saved facts and monitored topics are stored separately under `backend/mark_actions/data/` and are excluded from version control. Monitoring is opt-in, and financial or crypto topics are blocked.