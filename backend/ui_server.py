"""
YANTRA UI Server
Flask + SocketIO backend — bridges the assistant with the web dashboard.
"""

import asyncio
import mimetypes
import os
import queue
import sys
import threading
import platform
import tempfile
import time
from datetime import datetime
from pathlib import Path

import psutil
from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename

sys.path.insert(0, str(Path(__file__).parent))

from gemini_assistant import DEFAULT_LIVE_MODEL, SYSTEM_INSTRUCTION, _get_live_client, analyze_uploaded_files, build_live_config, run_assistant as run_agent
from execute import execute_command
from live_client import GeminiLiveSessionManager
from memory import add_message, clear_memory, get_recent_memory
from tools.system import get_system_status
from tools.register import get_available_tools
from mark_actions.proactive import ProactiveEngine

# ── Flask / SocketIO setup ─────────────────────────────────────────────────────
app = Flask(
    __name__,
    template_folder=str(Path(__file__).parent / "ui" / "templates"),
    static_folder=str(Path(__file__).parent / "ui" / "static"),
)
app.config["SECRET_KEY"] = os.getenv("YANTRA_SECRET_KEY") or os.urandom(32)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
socketio = SocketIO(
    app,
    cors_allowed_origins=None,
    async_mode="threading",
    logger=False,
    engineio_logger=False,
)

# ── Shared state ───────────────────────────────────────────────────────────────
activity_log: list[dict] = []
assistant_status = "READY"
voice_active = False
voice_starting = False
vision_mode = False
voice_load_lock = threading.Lock()
stop_metrics = threading.Event()
_live_voice_lock = threading.Lock()
_live_voice_loop: asyncio.AbstractEventLoop | None = None
_live_voice_task: asyncio.Task | None = None
_live_voice_output = None
_live_voice_manager: GeminiLiveSessionManager | None = None
_proactive_engine: ProactiveEngine | None = None
_last_live_user_speech = time.monotonic()
_LIVE_OUTPUT_QUEUE_SIZE = 120

# Tracks the currently running assistant text_command thread so we can
# signal it to stop before starting a new one (prevents duplicate responses).
_text_command_lock = threading.Lock()
_active_text_command: threading.Event | None = None   # set() = abort

# ── Helpers ────────────────────────────────────────────────────────────────────
def log_activity(source: str, tag: str, message: str) -> None:
    entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "source": source.upper(),
        "tag":    f"[{tag.upper()}]",
        "message": message,
    }
    activity_log.append(entry)
    if len(activity_log) > 100:
        activity_log.pop(0)
    socketio.emit("activity_log", entry)


def set_status(status: str) -> None:
    global assistant_status
    if assistant_status == status:
        return
    assistant_status = status
    socketio.emit("status_update", {"status": status})


def publish_assistant_result(result: dict) -> str:
    response = result.get("message", "I couldn't complete that request.")
    for action in result.get("actions", []):
        action_result = action.get("result", {})
        log_activity(
            "TOOL",
            "COMPLETE" if action_result.get("success") else "ERROR",
            action_result.get("message", action.get("action", "Tool finished.")),
        )
    socketio.emit("agent_response", {
        "text":    response,
        "sources": result.get("sources", []),
        "success": result.get("success", False),
    })
    if result.get("success", False):
        log_activity("AGENT", "RESPONSE", response)
    else:
        log_activity("YANTRA", "ERROR", response)
    return response


# ── Metrics broadcaster ────────────────────────────────────────────────────────
def broadcast_metrics() -> None:
    cpu_history = [0] * 60
    ram_history = [0] * 60
    net_history = [0] * 60
    gpu_history = [0] * 60
    prev_net = psutil.net_io_counters()

    while not stop_metrics.is_set():
        try:
            cpu  = psutil.cpu_percent(interval=None)
            ram  = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            net_now = psutil.net_io_counters()
            net_mb = round(
                (net_now.bytes_sent - prev_net.bytes_sent +
                 net_now.bytes_recv - prev_net.bytes_recv) / 1024 / 1024, 2
            )
            prev_net = net_now

            cpu_history = cpu_history[1:] + [cpu]
            ram_history = ram_history[1:] + [ram.percent]
            net_history = net_history[1:] + [net_mb]
            gpu_history = gpu_history[1:] + [0]

            procs = []
            for p in sorted(
                psutil.process_iter(["name", "cpu_percent"]),
                key=lambda x: x.info["cpu_percent"] or 0,
                reverse=True,
            )[:5]:
                procs.append({
                    "name": p.info["name"] or "?",
                    "cpu":  round(p.info["cpu_percent"] or 0, 1),
                })

            mem = psutil.virtual_memory()
            try:
                net_conns = len(psutil.net_connections())
            except Exception:
                net_conns = 0

            socketio.emit("metrics", {
                "cpu":         cpu,
                "ram":         ram.percent,
                "ram_used":    round(ram.used   / 1024**3, 1),
                "ram_total":   round(ram.total  / 1024**3, 1),
                "disk":        disk.percent,
                "disk_used":   round(disk.used  / 1024**3, 0),
                "disk_total":  round(disk.total / 1024**3, 0),
                "net":         net_mb,
                "cpu_history": cpu_history,
                "ram_history": ram_history,
                "net_history": net_history,
                "gpu_history": gpu_history,
                "processes":   procs,
                "net_conns":   net_conns,
                "mem_short":   round(mem.used  / 1024**2, 1),
                "mem_long":    round(mem.total / 1024**2, 1),
                "time":        datetime.now().strftime("%I:%M:%S %p"),
                "date":        datetime.now().strftime("%a, %d %b %Y").upper(),
                "uptime":      str(datetime.now() -
                                   datetime.fromtimestamp(psutil.boot_time()))[:8],
                "platform":    platform.system() + " " + platform.release(),
                "arch":        platform.machine(),
                "status":      assistant_status,
            })
        except Exception as e:
            print(f"[metrics] {e}")
        time.sleep(1)


def broadcast_monitor_alerts() -> None:
    from mark_actions.state import check_monitored_topics

    while not stop_metrics.is_set():
        try:
            for alert in check_monitored_topics():
                log_activity("MONITOR", "UPDATE", alert)
                socketio.emit("agent_response", {
                    "text": alert,
                    "sources": [],
                    "success": True,
                })
                if not voice_active:
                    try:
                        from tts import speak
                        speak(alert.replace("\n", ". "))
                    except Exception as error:
                        log_activity("MONITOR", "ERROR", f"Voice alert failed: {type(error).__name__}")
        except Exception as error:
            log_activity("MONITOR", "ERROR", f"Topic check failed: {type(error).__name__}")
        if stop_metrics.wait(300):
            return


# ── Voice worker ───────────────────────────────────────────────────────────────
whisper_model   = None
sd_module       = None
np_module       = None


def _get_wasapi_audio_config(sd):
    """Return matching WASAPI input/output devices and shared-mode settings."""
    if not hasattr(sd, "query_hostapis") or not hasattr(sd, "query_devices"):
        return None, None, None

    wasapi_hostapi = next(
        (
            index
            for index, hostapi in enumerate(sd.query_hostapis())
            if str(hostapi.get("name", "")).upper() == "WINDOWS WASAPI"
        ),
        None,
    )
    if wasapi_hostapi is None:
        raise RuntimeError("Windows WASAPI host API is unavailable.")

    default_input, default_output = sd.default.device
    input_name = str(sd.query_devices(default_input).get("name", ""))
    output_name = str(sd.query_devices(default_output).get("name", ""))
    devices = sd.query_devices()

    def find_device(name: str, max_input_channels: bool) -> int:
        candidates = [
            (index, device)
            for index, device in enumerate(devices)
            if device.get("hostapi") == wasapi_hostapi
            and device.get("max_input_channels" if max_input_channels else "max_output_channels", 0) > 0
        ]
        matching = next(
            ((index, device) for index, device in candidates if name and name in str(device.get("name", ""))),
            None,
        )
        if matching is None and candidates:
            matching = candidates[0]
        if matching is None:
            direction = "input" if max_input_channels else "output"
            raise RuntimeError(f"No Windows WASAPI {direction} device is available.")
        return matching[0]

    return (
        find_device(input_name, True),
        find_device(output_name, False),
        lambda: sd.WasapiSettings(exclusive=False, auto_convert=True),
    )


def _get_directsound_audio_config(sd):
    if not hasattr(sd, "query_hostapis") or not hasattr(sd, "query_devices"):
        return None, None, None
    directsound_hostapi = next(
        (
            index
            for index, hostapi in enumerate(sd.query_hostapis())
            if str(hostapi.get("name", "")).upper() == "WINDOWS DIRECTSOUND"
        ),
        None,
    )
    if directsound_hostapi is None:
        return None, None, None
    default_input, default_output = sd.default.device
    input_name = str(sd.query_devices(default_input).get("name", ""))
    output_name = str(sd.query_devices(default_output).get("name", ""))
    devices = sd.query_devices()

    def find_device(name: str, input_device: bool) -> int:
        channel_key = "max_input_channels" if input_device else "max_output_channels"
        candidates = [
            (index, device)
            for index, device in enumerate(devices)
            if device.get("hostapi") == directsound_hostapi and device.get(channel_key, 0) > 0
        ]
        matching = next(
            ((index, device) for index, device in candidates if name and name in str(device.get("name", ""))),
            None,
        )
        return matching[0] if matching else candidates[0][0]

    return find_device(input_name, True), find_device(output_name, False), None


def load_whisper() -> None:
    global whisper_model, sd_module, np_module
    with voice_load_lock:
        if whisper_model is not None:
            return
        log_activity("YANTRA", "SYSTEM", "Loading Whisper model…")
        from faster_whisper import WhisperModel
        import sounddevice as sd
        import numpy as np
        whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
        sd_module  = sd
        np_module  = np
        log_activity("YANTRA", "SYSTEM", "Whisper model ready.")


def record_audio(duration: float = 5, sample_rate: int = 16000):
    audio = sd_module.rec(
        int(duration * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
    )
    sd_module.wait()
    return np_module.squeeze(audio)


def _wait_for_silence(min_rms: float = 0.01, check_interval: float = 0.2,
                      timeout: float = 3.0, sample_rate: int = 16000) -> None:
    """
    Wait until the microphone input drops below min_rms (speaker finished)
    or until timeout. Prevents recording TTS bleed.
    """
    deadline = time.time() + timeout
    chunk = int(check_interval * sample_rate)
    while time.time() < deadline:
        snippet = sd_module.rec(chunk, samplerate=sample_rate, channels=1, dtype="float32")
        sd_module.wait()
        rms = float(np_module.sqrt(np_module.mean(snippet ** 2)))
        if rms < min_rms:
            return   # mic is quiet — safe to record command
        time.sleep(0.05)


def transcribe_audio(audio) -> str:
    segments, _ = whisper_model.transcribe(
        audio,
        language="en",
        beam_size=5,
        best_of=5,
        temperature=0,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    return " ".join(s.text for s in segments).strip()


def _merge_live_transcript(current: str, fragment: str) -> str:
    fragment = fragment.strip()
    if not fragment:
        return current
    if not current:
        return fragment
    if fragment.startswith(current):
        return fragment
    if current.endswith(fragment):
        return current
    current_words = current.split()
    fragment_words = fragment.split()
    overlap_limit = min(len(current_words), len(fragment_words))
    for overlap in range(overlap_limit, 0, -1):
        current_tail = [word.casefold() for word in current_words[-overlap:]]
        fragment_head = [word.casefold() for word in fragment_words[:overlap]]
        if current_tail == fragment_head:
            return " ".join(current_words + fragment_words[overlap:])
    return f"{current} {fragment}"


def get_live_model() -> str:
    return (os.getenv("GEMINI_LIVE_MODEL") or DEFAULT_LIVE_MODEL).strip()


def _live_error_message(error: Exception) -> str:
    error_text = str(error).lower()
    if any(marker in error_text for marker in ("429", "resource_exhausted", "quota")):
        return (
            "Gemini Live quota is exhausted. The Live connection failed before microphone setup, "
            "so no microphone audio was captured. Check Google AI Studio quota and billing, or "
            "configure a Gemini project with Live API quota. Typed chat can still use Groq if configured."
        )
    if any(marker in error_text for marker in ("401", "403", "unauthorized", "api key", "api_key_invalid")):
        return "Gemini Live could not connect. Check the API key and GEMINI_LIVE_MODEL access."
    return "Gemini Live could not connect. Check the backend activity log for the connection error."


async def _run_live_voice_session() -> None:
    global _live_voice_loop, _live_voice_task, _live_voice_output, voice_active, _live_voice_manager
    global _proactive_engine, _last_live_user_speech
    from google.genai import types
    import sounddevice as sd

    loop = asyncio.get_running_loop()
    with _live_voice_lock:
        _live_voice_loop = loop
        _live_voice_task = asyncio.current_task()

    _live_voice_manager = GeminiLiveSessionManager(
        model=get_live_model(),
        system_instruction=SYSTEM_INSTRUCTION,
        client_factory=_get_live_client,
        on_state=lambda state: (
            log_activity("VOICE", "STATE", f"Gemini Live {state}"),
            set_status(state if state in {"CONNECTING", "CONNECTED", "LISTENING", "THINKING", "SPEAKING", "INTERRUPTED", "RECONNECTING", "ERROR", "STOPPED"} else "READY"),
        ),
        on_error=lambda error, details: log_activity(
            "VOICE",
            "ERROR",
            f"Error type: {type(error).__name__}; message: {error}; details: {details}",
        ),
    )
    _live_voice_manager.set_state("IDLE")
    _proactive_engine = ProactiveEngine()
    _last_live_user_speech = time.monotonic()
    log_activity("VOICE", "STATE", "[VOICE] Starting Gemini Live session...")

    reconnect_attempt = 0
    session_resumption_handle = None
    while voice_active:
        input_stream = None
        output_stream = None
        session_connected = False
        audio_ready = False
        try:
            _live_voice_manager.set_state("CONNECTING")
            set_status("CONNECTING")
            log_activity("VOICE", "STATE", "[VOICE] Gemini Live CONNECTING")
            client = _get_live_client()
            model = get_live_model()
            history = get_recent_memory()[-8:]
            context = "\n".join(
                f"{item.get('role', 'user')}: {str(item.get('content', ''))[:300]}"
                for item in history if isinstance(item, dict) and item.get("content")
            )
            system_instruction = SYSTEM_INSTRUCTION
            if context:
                system_instruction += f"\n\nRecent conversation context (use only when relevant):\n{context}"
            config = build_live_config(system_instruction, session_resumption_handle)

            async with client.aio.live.connect(model=model, config=config) as session:
                session_connected = True
                _live_voice_manager.set_state("CONNECTED")
                log_activity("VOICE", "STATE", "[VOICE] Gemini Live CONNECTED")
                input_audio: asyncio.Queue[bytes] = asyncio.Queue(maxsize=20)
                output_audio: queue.Queue[bytes] = queue.Queue(maxsize=_LIVE_OUTPUT_QUEUE_SIZE)
                pending_output = bytearray()
                output_lock = threading.Lock()
                output_drained = threading.Event()
                output_drained.set()

                def enqueue_input(data: bytes) -> None:
                    if input_audio.full():
                        try:
                            input_audio.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    input_audio.put_nowait(data)

                def input_callback(indata, _frames, _time_info, status) -> None:
                    if status:
                        loop.call_soon_threadsafe(
                            log_activity, "VOICE", "ERROR", f"Microphone status: {status}"
                        )
                    if voice_active:
                        loop.call_soon_threadsafe(enqueue_input, indata.tobytes())

                def output_callback(outdata, frames, _time_info, status) -> None:
                    if status:
                        loop.call_soon_threadsafe(
                            log_activity, "VOICE", "ERROR", f"Speaker status: {status}"
                        )
                    required = frames * 2
                    with output_lock:
                        while len(pending_output) < required:
                            try:
                                pending_output.extend(output_audio.get_nowait())
                            except queue.Empty:
                                break
                        available = min(required, len(pending_output))
                        rendered = bytes(pending_output[:available])
                        del pending_output[:available]
                        outdata[:] = rendered.ljust(required, b"\0")
                        if not pending_output and output_audio.empty():
                            output_drained.set()

                def clear_output() -> None:
                    with output_lock:
                        pending_output.clear()
                    while True:
                        try:
                            output_audio.get_nowait()
                        except queue.Empty:
                            break
                    output_drained.set()

                def enqueue_output(data: bytes) -> None:
                    if not data:
                        return
                    output_drained.clear()
                    for offset in range(0, len(data), 2400):
                        chunk = data[offset:offset + 2400]
                        try:
                            output_audio.put_nowait(chunk)
                        except queue.Full:
                            try:
                                output_audio.get_nowait()
                                output_audio.put_nowait(chunk)
                            except (queue.Empty, queue.Full):
                                pass

                wasapi_config = _get_wasapi_audio_config(sd)
                directsound_config = _get_directsound_audio_config(sd)
                audio_configs = [
                    ("WASAPI", wasapi_config),
                    ("DirectSound fallback", directsound_config),
                ]
                if not any(config[1][0] is not None for config in audio_configs):
                    audio_configs = [("Default audio", (None, None, None))]
                audio_setup_error = None
                for backend_name, (input_device, output_device, settings_factory) in audio_configs:
                    if backend_name != "Default audio" and (input_device is None or output_device is None):
                        continue
                    if settings_factory is not None:
                        log_activity(
                            "VOICE",
                            "STATE",
                            f"{backend_name} audio enabled (input {input_device}, output {output_device})",
                        )
                    input_options = {}
                    output_options = {}
                    if input_device is not None and output_device is not None:
                        input_options["device"] = input_device
                        output_options["device"] = output_device
                    if settings_factory is not None:
                        input_options["extra_settings"] = settings_factory()
                        output_options["extra_settings"] = settings_factory()
                    for setup_attempt in range(1, 4):
                        input_stream = None
                        output_stream = None
                        try:
                            input_stream = sd.InputStream(
                                samplerate=16000,
                                channels=1,
                                dtype="int16",
                                blocksize=1600,
                                callback=input_callback,
                                **input_options,
                            )
                            output_stream = sd.RawOutputStream(
                                samplerate=24000,
                                channels=1,
                                dtype="int16",
                                blocksize=1200,
                                callback=output_callback,
                                **output_options,
                            )
                            with _live_voice_lock:
                                _live_voice_output = output_stream
                            input_stream.start()
                            output_stream.start()
                            audio_setup_error = None
                            break
                        except Exception as error:
                            audio_setup_error = error
                            log_activity(
                                "VOICE",
                                "ERROR",
                                f"{backend_name} startup attempt {setup_attempt}/3 failed: "
                                f"{type(error).__name__}: {error}",
                            )
                            with _live_voice_lock:
                                _live_voice_output = None
                            for stream in (output_stream, input_stream):
                                if stream is not None:
                                    try:
                                        stream.stop()
                                    except Exception:
                                        pass
                                    try:
                                        stream.close()
                                    except Exception:
                                        pass
                            if setup_attempt < 3:
                                await asyncio.sleep(0.75)
                    if audio_setup_error is None:
                        break
                if audio_setup_error is not None:
                    raise audio_setup_error
                audio_ready = True
                reconnect_attempt = 0
                socketio.emit("waveform_active", {"active": True})
                _live_voice_manager.stream_microphone()
                _live_voice_manager.set_state("LISTENING")
                set_status("LISTENING")
                log_activity("VOICE", "STATE", "[VOICE] Microphone STREAMING")
                log_activity("YANTRA", "SYSTEM", "Gemini Live connected. Listening continuously.")

                async def send_microphone() -> None:
                    while voice_active:
                        try:
                            chunk = await asyncio.wait_for(input_audio.get(), timeout=1.0)
                        except asyncio.TimeoutError:
                            if (
                                _proactive_engine is not None
                                and output_drained.is_set()
                                and _proactive_engine.should_trigger(_last_live_user_speech)
                            ):
                                from mark_actions.state import format_saved_memory, get_monitored_topics
                                turns = [
                                    f"{item.get('role', 'user')}: {item.get('content', '')}"
                                    for item in get_recent_memory()[-6:]
                                    if isinstance(item, dict) and item.get("content")
                                ]
                                prompt = _proactive_engine.build_prompt(
                                    saved_facts=format_saved_memory(),
                                    monitors=get_monitored_topics(),
                                    recent_turns=turns,
                                )
                                _proactive_engine.mark_triggered()
                                await session.send_client_content(
                                    turns={"parts": [{"text": prompt}]},
                                    turn_complete=True,
                                )
                            continue
                        await session.send_realtime_input(
                            audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
                        )

                async def receive_live() -> None:
                    global _last_live_user_speech
                    nonlocal session_resumption_handle
                    while voice_active:
                        input_text = ""
                        output_text = ""
                        interrupted = False
                        audio_logged = False
                        async for message in session.receive():
                            resumption_update = getattr(message, "session_resumption_update", None)
                            new_handle = getattr(resumption_update, "newHandle", None)
                            if new_handle:
                                session_resumption_handle = new_handle
                            audio_data = getattr(message, "data", None)
                            server_content = getattr(message, "server_content", None)
                            if not audio_data and server_content and server_content.model_turn:
                                for part in server_content.model_turn.parts or []:
                                    if part.inline_data and part.inline_data.data:
                                        audio_data = part.inline_data.data
                                        enqueue_output(audio_data)
                            elif audio_data:
                                enqueue_output(audio_data)
                            if audio_data:
                                _live_voice_manager.play_audio(audio_data)
                                if not audio_logged:
                                    log_activity("VOICE", "STATE", "[VOICE] Native audio playback started")
                                    audio_logged = True

                            if server_content:
                                if server_content.input_transcription and server_content.input_transcription.text:
                                    _last_live_user_speech = time.monotonic()
                                    _live_voice_manager.set_state("THINKING")
                                    set_status("THINKING")
                                    input_text = _merge_live_transcript(
                                        input_text, server_content.input_transcription.text
                                    )
                                if server_content.output_transcription and server_content.output_transcription.text:
                                    output_text = _merge_live_transcript(
                                        output_text, server_content.output_transcription.text
                                    )
                                if server_content.interrupted:
                                    interrupted = True
                                    clear_output()
                                    _live_voice_manager.interrupt()
                                    _live_voice_manager.set_state("INTERRUPTED")
                                    set_status("INTERRUPTED")
                                    log_activity("VOICE", "STATE", "[VOICE] User interrupted Gemini")
                                    log_activity("YANTRA", "INTERRUPT", "Assistant audio stopped for the new user turn.")
                                if server_content.turn_complete:
                                    if input_text:
                                        add_message("user", input_text)
                                        log_activity("USER", "COMMAND", input_text)
                                        socketio.emit("user_command", {"text": input_text})
                                    if output_text and not interrupted:
                                        add_message("assistant", output_text)
                                        publish_assistant_result({
                                            "success": True,
                                            "message": output_text,
                                            "sources": [],
                                            "actions": [],
                                        })

                                    async def mark_listening_after_playback() -> None:
                                        deadline = loop.time() + 12.0
                                        while voice_active and not output_drained.is_set() and loop.time() < deadline:
                                            await asyncio.sleep(0.05)
                                        if voice_active:
                                            _live_voice_manager.set_state("LISTENING")
                                            set_status("LISTENING")
                                            log_activity("VOICE", "STATE", "[VOICE] Listening for next user turn")

                                    asyncio.create_task(mark_listening_after_playback())
                                    break

                            tool_call = getattr(message, "tool_call", None)
                            if tool_call:
                                set_status("THINKING")
                                responses = []
                                for call in tool_call.function_calls:
                                    arguments = dict(call.args or {})
                                    result = await asyncio.to_thread(
                                        execute_command,
                                        {"_tool_name": call.name, **arguments},
                                    )
                                    if not isinstance(result, dict):
                                        result = {"success": False, "message": "The action returned an invalid result."}
                                    log_activity(
                                        "TOOL",
                                        "COMPLETE" if result.get("success") else "ERROR",
                                        result.get("message", call.name),
                                    )
                                    parts = []
                                    image_path = result.get("path") if call.name == "capture_screen" else None
                                    if result.get("success") and image_path:
                                        path = Path(image_path)
                                        if path.is_file() and path.stat().st_size <= 20_000_000:
                                            mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
                                            parts.append(types.Part.from_bytes(
                                                data=path.read_bytes(), mime_type=mime_type
                                            ))
                                    responses.append(types.FunctionResponse(
                                        id=call.id,
                                        name=call.name,
                                        response=result,
                                        parts=parts or None,
                                    ))
                                await session.send_tool_response(function_responses=responses)
                        if not voice_active:
                            break
                tasks = [asyncio.create_task(send_microphone()), asyncio.create_task(receive_live())]
                try:
                    done, pending = await asyncio.wait(
                        tasks,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in done:
                        task.result()
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    try:
                        await session.send_realtime_input(audio_stream_end=True)
                    except Exception:
                        pass
        except asyncio.CancelledError:
            break
        except Exception as error:
            if not voice_active:
                break
            print(f"[YANTRA] Gemini Live session failed: {type(error).__name__}: {error}")
            if session_connected and not audio_ready:
                log_activity(
                    "VOICE",
                    "ERROR",
                    f"Audio device setup failed: {type(error).__name__}: {error}",
                )
                socketio.emit("assistant_error", {
                    "message": "Could not start microphone or speaker audio. Check device availability and microphone permissions."
                })
                voice_active = False
                break
            if _live_voice_manager is not None:
                _live_voice_manager.set_state("RECONNECTING")
            log_activity("VOICE", "ERROR", f"Live connection interrupted ({type(error).__name__}); reconnecting.")
            log_activity("VOICE", "ERROR", f"Error type: {type(error).__name__}; message: {error}")
            error_text = str(error).lower()
            if any(marker in error_text for marker in (
                "401", "403", "429", "unauthorized", "api key", "api_key_invalid",
                "resource_exhausted", "quota", "model_not_found", "invalid_argument",
            )):
                message = _live_error_message(error)
                if "quota is exhausted" in message:
                    log_activity(
                        "VOICE", "ERROR",
                        "Gemini Live quota exhausted before microphone setup; no microphone audio was captured.",
                    )
                socketio.emit("assistant_error", {
                    "message": message
                })
                voice_active = False
                break
            if _live_voice_manager is not None:
                _live_voice_manager.set_state("CONNECTING")
            set_status("CONNECTING")
            reconnect_attempt = min(reconnect_attempt + 1, 5)
            await asyncio.sleep(min(2 ** reconnect_attempt, 16))
        finally:
            for stream in (input_stream, output_stream):
                if stream is not None:
                    try:
                        stream.stop()
                    except Exception:
                        pass
                    try:
                        stream.close()
                    except Exception:
                        pass
            with _live_voice_lock:
                _live_voice_output = None
            socketio.emit("waveform_active", {"active": False})

    with _live_voice_lock:
        _live_voice_loop = None
        _live_voice_task = None
        _live_voice_output = None
    if _live_voice_manager is not None:
        _live_voice_manager.set_state("STOPPED")
        await _live_voice_manager.close()
        _live_voice_manager = None


def run_voice_loop() -> None:
    try:
        asyncio.run(_run_live_voice_session())
    finally:
        socketio.emit("waveform_active", {"active": False})
        set_status("READY")


def start_voice_worker() -> None:
    global voice_active, voice_starting
    voice_starting = False
    if voice_active:
        try:
            run_voice_loop()
        except Exception as error:
            log_activity("VOICE", "ERROR", f"Live voice stopped: {type(error).__name__}")
            socketio.emit("assistant_error", {
                "message": "Gemini Live voice stopped unexpectedly. Check the backend connection and audio devices."
            })
        finally:
            voice_active = False
            voice_starting = False
            socketio.emit("voice_state", {"active": False})


# ── Socket events ──────────────────────────────────────────────────────────────
@socketio.on("connect")
def on_connect():
    log_activity("YANTRA", "SYSTEM", "UI client connected.")
    emit("activity_history", activity_log)
    emit("assistant_config", {
        "assistant_ready": bool(
            os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GROQ_API_KEY", "").strip()
        ),
        "gemini_ready": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "groq_ready": bool(os.getenv("GROQ_API_KEY", "").strip()),
        "model": os.getenv("GEMINI_MODEL", "gemini-flash-latest"),
        "live_model": get_live_model(),
        "tool_count": len(get_available_tools()),
    })


@socketio.on("disconnect")
def on_disconnect(_reason=None):
    global voice_active
    if voice_active:
        _stop_voice_safely()
        log_activity("VOICE", "INPUT", "Voice stopped — dashboard disconnected.")


@socketio.on("text_command")
def on_text_command(data: dict):
    """
    Handle a text command from the UI.
    If a previous command is still running, signal it to abort first so we
    never have two assistant responses racing each other.
    """
    command = data.get("text", "").strip()
    if not command:
        return

    global _active_text_command

    # Cancel the previous in-flight request
    with _text_command_lock:
        if _active_text_command is not None:
            _active_text_command.set()   # signal old thread to stop
        abort_event = threading.Event()
        _active_text_command = abort_event

    log_activity("USER", "COMMAND", command)
    set_status("THINKING")
    log_activity("AGENT", "THINKING", "Analyzing…")

    def _run(abort: threading.Event) -> None:
        global _active_text_command
        try:
            result = run_agent(
                command,
                inspect_screen=bool(data.get("inspect_screen", vision_mode)),
            )

            # If a newer command was issued while we were thinking, discard this result
            if abort.is_set():
                log_activity("YANTRA", "INTERRUPT", "Stale response discarded.")
                return

            response = publish_assistant_result(result)
            set_status("SPEAKING")

            from tts import speak, interrupt_speech, set_activity_logger
            set_activity_logger(log_activity)
            if abort.is_set():
                return
            speak(response)

        except Exception as error:
            if not abort.is_set():
                log_activity("YANTRA", "ERROR", f"Request failed: {type(error).__name__}")
                socketio.emit("agent_response", {
                    "text":    "Something went wrong. Please try again.",
                    "sources": [],
                    "success": False,
                })
        finally:
            set_status("READY")
            with _text_command_lock:
                # Clear the slot only if we're still the active command
                if _active_text_command is abort:
                    _active_text_command = None

    threading.Thread(target=_run, args=(abort_event,), daemon=True).start()


@socketio.on("start_voice")
def on_start_voice():
    global voice_active, voice_starting
    if voice_active or voice_starting:
        return
    if not os.getenv("GEMINI_API_KEY", "").strip():
        socketio.emit("assistant_error", {
            "message": "Gemini Live voice mode requires GEMINI_API_KEY in backend/.env."
        })
        socketio.emit("voice_state", {"active": False})
        return
    voice_active   = True
    voice_starting = True
    socketio.emit("voice_state", {"active": True})
    threading.Thread(target=start_voice_worker, daemon=True).start()
    log_activity("VOICE", "STATE", "[VOICE] Starting Gemini Live session...")
    log_activity("VOICE", "INPUT", "Voice mode activated. Waiting for Gemini Live connection...")


@socketio.on("stop_voice")
def on_stop_voice():
    _stop_voice_safely()
    log_activity("VOICE", "INPUT", "Voice mode deactivated.")


@socketio.on("interrupt")
def on_interrupt():
    """
    User pressed Escape or clicked Interrupt.
    Stop current TTS immediately, abort any in-flight text command,
    and reset status.
    """
    _stop_voice_safely()

    # 2. Signal in-flight text command to abort
    global _active_text_command
    with _text_command_lock:
        if _active_text_command is not None:
            _active_text_command.set()
            _active_text_command = None

    log_activity("YANTRA", "INTERRUPT", "Interrupted by user.")


@socketio.on("clear_memory")
def on_clear_memory():
    clear_memory()
    log_activity("MEMORY", "UPDATE", "Conversation memory cleared.")


@socketio.on("set_vision_mode")
def on_set_vision_mode(data: dict):
    global vision_mode
    vision_mode = bool(data.get("enabled", False))
    log_activity(
        "YANTRA", "VISION",
        "Vision mode enabled." if vision_mode else "Vision mode disabled.",
    )


# ── Internal helper ────────────────────────────────────────────────────────────
def _stop_voice_safely() -> None:
    global voice_active
    voice_active = False
    with _live_voice_lock:
        live_loop = _live_voice_loop
        live_task = _live_voice_task
        live_output = _live_voice_output
    if _live_voice_manager is not None:
        _live_voice_manager.interrupt()
    if live_output is not None:
        try:
            live_output.abort()
        except Exception:
            pass
    if live_loop is not None and live_task is not None and live_loop.is_running():
        live_loop.call_soon_threadsafe(live_task.cancel)
    try:
        from tts import interrupt_speech
        interrupt_speech()
    except Exception:
        pass
    socketio.emit("waveform_active", {"active": False})
    socketio.emit("voice_state",     {"active": False})
    set_status("READY")


# ── Routes ─────────────────────────────────────────────────────────────────────
ALLOWED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".wav", ".mp3", ".m4a",
    ".mp4", ".txt", ".md", ".csv", ".json", ".py", ".js", ".html", ".css",
}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def upload_files():
    if not os.getenv("GEMINI_API_KEY", "").strip():
        return jsonify({
            "success": False,
            "message": "Set GEMINI_API_KEY in backend/.env before analyzing files.",
            "sources": [],
        }), 503

    files = request.files.getlist("files")
    if not files or not any(f.filename for f in files):
        return jsonify({"success": False, "message": "Choose at least one file."}), 400

    temp_paths: list[Path] = []
    set_status("THINKING")
    try:
        for uploaded in files:
            filename = secure_filename(uploaded.filename or "")
            suffix   = Path(filename).suffix.lower()
            if not filename or suffix not in ALLOWED_EXTENSIONS:
                return jsonify({
                    "success": False,
                    "message": f"Unsupported file type: {filename or 'unknown'}",
                    "sources": [],
                }), 400
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                uploaded.save(tmp)
                temp_paths.append(Path(tmp.name))

        result = analyze_uploaded_files(temp_paths, request.form.get("prompt", ""))
        return jsonify(result), 200 if result.get("success") else 502

    except Exception as error:
        log_activity("YANTRA", "UPLOAD", f"File analysis failed: {type(error).__name__}")
        return jsonify({
            "success": False,
            "message": "File analysis failed. Check the file and Gemini config.",
            "sources": [],
        }), 502
    finally:
        for p in temp_paths:
            p.unlink(missing_ok=True)
        set_status("READY")


@app.errorhandler(413)
def upload_too_large(_error):
    return jsonify({"success": False, "message": "Uploads are limited to 25 MB."}), 413


def get_server_port() -> int:
    return int(os.getenv("YANTRA_PORT", "5000"))


# ── Boot ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    server_port = get_server_port()
    log_activity("YANTRA", "SYSTEM", "System initialized successfully.")
    threading.Thread(target=broadcast_metrics, daemon=True).start()
    threading.Thread(target=broadcast_monitor_alerts, daemon=True).start()
    print("\n" + "=" * 50)
    print("   YANTRA AI DASHBOARD")
    print("=" * 50)
    print(f"  Open: http://localhost:{server_port}")
    print("=" * 50 + "\n")
    socketio.run(
        app,
        host="127.0.0.1",
        port=server_port,
        debug=False,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )
