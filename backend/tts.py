"""
YANTRA TTS — pyttsx3 speech with interrupt/cancel support.
"""
import queue
import threading

TTS_MODEL = "gemini-3.8-flash-lite-tts"
TTS_VOICE = "Charon"
SYSTEM_TTS_RATE = 152
TTS_STYLE = (
    "Warm, expressive conversational delivery at a relaxed pace, slightly slower than brisk speech, "
    "with natural pitch variation, clear emphasis, and short pauses. Match the language and emotion of the text."
)
_activity_logger = None


def set_activity_logger(logger) -> None:
    global _activity_logger
    _activity_logger = logger


def _log_tts(message: str) -> None:
    print(f"[TTS] {message}")
    if _activity_logger is not None:
        try:
            _activity_logger("VOICE", "TTS", message)
        except Exception:
            pass


_speech_queue: queue.Queue = queue.Queue()
_worker_lock = threading.Lock()
_speech_worker: threading.Thread | None = None
_interrupt_event = threading.Event()   # set → stop current speech ASAP
_current_engine = None                 # reference so we can call engine.stop()


def _speak_worker() -> None:
    global _current_engine
    while True:
        job = _speech_queue.get()
        try:
            # Drain any stale jobs that were queued before an interrupt
            if _interrupt_event.is_set():
                continue

            if not speak_with_gemini(job["text"]):
                import pyttsx3
                if _current_engine is None:
                    _current_engine = pyttsx3.init()
                    _current_engine.setProperty("rate", SYSTEM_TTS_RATE)
                    _current_engine.setProperty("volume", 1.0)

                _current_engine.say(job["text"])
                _current_engine.runAndWait()

        except Exception as error:
            job["error"] = error
        finally:
            job["done"].set()
            _speech_queue.task_done()


def speak_with_gemini(text: str) -> bool:
    """Speak with Charon; return False so callers can use local TTS as fallback."""
    import base64
    import os

    if not os.getenv("GEMINI_API_KEY", "").strip():
        _log_tts("Gemini key unavailable; using the system voice for this typed reply.")
        return False

    audio_stream = None
    audio_started = False
    try:
        import sounddevice as sd
        from gemini_assistant import _get_client

        events = _get_client().interactions.create(
            model=TTS_MODEL,
            input=[{
                "type": "user_input",
                "content": [{
                    "type": "text",
                    "text": str(text),
                    "annotations": [{
                        "type": "speech_metadata",
                        "style": TTS_STYLE,
                    }],
                }],
            }],
            response_format={"type": "audio"},
            generation_config={"speech_config": [{"voice": TTS_VOICE}]},
            stream=True,
        )
        for event in events:
            if _interrupt_event.is_set():
                break
            delta = getattr(event, "delta", None)
            if getattr(event, "event_type", None) != "step.delta" or getattr(delta, "type", None) != "audio":
                continue
            audio_data = base64.b64decode(delta.data)
            if audio_stream is None:
                audio_stream = sd.RawOutputStream(
                    samplerate=24000,
                    channels=1,
                    dtype="int16",
                )
                audio_stream.start()
            audio_stream.write(audio_data)
            audio_started = True
        if not audio_started:
            _log_tts("Gemini Charon TTS returned no audio; using system voice.")
            return False
        _log_tts("Typed reply spoken with streaming Gemini Charon TTS.")
        return True
    except Exception as error:
        if audio_started:
            _log_tts(f"Gemini Charon stream ended early ({type(error).__name__}); keeping partial audio.")
            return True
        _log_tts(f"Gemini Charon unavailable; using system voice ({type(error).__name__}).")
        return False
    finally:
        if audio_stream is not None:
            try:
                audio_stream.stop()
            except Exception:
                pass
            try:
                audio_stream.close()
            except Exception:
                pass


def speak(text: str) -> None:
    """Speak text synchronously. Raises RuntimeError if TTS fails."""
    text = str(text or "").strip()
    if not text:
        return

    # Clear any leftover interrupt before speaking
    _interrupt_event.clear()

    global _speech_worker
    with _worker_lock:
        if _speech_worker is None or not _speech_worker.is_alive():
            _speech_worker = threading.Thread(target=_speak_worker, daemon=True)
            _speech_worker.start()

    job: dict = {"text": text, "done": threading.Event(), "error": None}
    _speech_queue.put(job)
    job["done"].wait()
    if job["error"]:
        raise RuntimeError("Text-to-speech failed.") from job["error"]


def interrupt_speech() -> None:
    """Stop current speech immediately and drain the queue."""
    global _current_engine
    _interrupt_event.set()

    # Tell pyttsx3 to stop mid-sentence
    if _current_engine is not None:
        try:
            _current_engine.stop()
        except Exception:
            pass

    # Drain any pending jobs without playing them
    while not _speech_queue.empty():
        try:
            leftover = _speech_queue.get_nowait()
            leftover["done"].set()
            _speech_queue.task_done()
        except queue.Empty:
            break

    # Clear after drain so next speak() works normally
    _interrupt_event.clear()


if __name__ == "__main__":
    speak("Hello. YANTRA is online and ready.")
