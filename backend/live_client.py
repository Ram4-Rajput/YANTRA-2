from __future__ import annotations

import asyncio
import os
import queue
import threading
from typing import Any, Callable

from gemini_assistant import DEFAULT_LIVE_MODEL, _get_live_client, build_live_config

LIVE_OUTPUT_QUEUE_SIZE = 120

LIVE_STATES = (
    "IDLE",
    "CONNECTING",
    "CONNECTED",
    "LISTENING",
    "THINKING",
    "SPEAKING",
    "INTERRUPTED",
    "RECONNECTING",
    "ERROR",
    "STOPPED",
)


class GeminiLiveSessionManager:
    def __init__(
        self,
        model: str | None = None,
        system_instruction: str | None = None,
        client_factory: Callable[[], Any] | None = None,
        on_state: Callable[[str], None] | None = None,
        on_error: Callable[[Exception, str], None] | None = None,
    ) -> None:
        self.model = (model or os.getenv("GEMINI_LIVE_MODEL") or DEFAULT_LIVE_MODEL).strip()
        self.system_instruction = system_instruction
        self.client_factory = client_factory or _get_live_client
        self.on_state = on_state or (lambda state: None)
        self.on_error = on_error or (lambda error, details: None)

        self.session = None
        self.session_context = None
        self.client = None
        self.connected = False
        self.active = False
        self.state = "IDLE"
        self._input_queue: asyncio.Queue[bytes] | None = None
        self._microphone_stream = None
        self._speaker_stream = None
        self._output_lock = threading.Lock()
        self._pending_output = bytearray()
        self._output_queue: queue.Queue[bytes] = queue.Queue(maxsize=LIVE_OUTPUT_QUEUE_SIZE)
        self._output_drained = threading.Event()
        self._output_drained.set()
        self._interrupt_requested = False

    def current_state(self) -> str:
        return self.state

    def set_state(self, state: str) -> str:
        if state not in LIVE_STATES:
            raise ValueError(f"Unsupported live state: {state!r}")
        if self.state == state:
            return state
        self.state = state
        self.on_state(state)
        return state

    def start(self) -> None:
        self.active = True
        self.set_state("CONNECTING")

    async def connect(self) -> Any:
        if self.connected and self.session is not None:
            return self.session

        self.start()
        self.client = self.client_factory()
        self.session_context = self.client.aio.live.connect(
            model=self.model,
            config=build_live_config(self.system_instruction),
        )
        self.session = await self.session_context.__aenter__()
        self.connected = True
        self.set_state("CONNECTED")
        self.set_state("LISTENING")
        return self.session

    def stream_microphone(self) -> None:
        self.set_state("LISTENING")

    def receive_responses(self) -> None:
        self.set_state("THINKING")

    def play_audio(self, data: bytes) -> None:
        if not data:
            return
        self.set_state("SPEAKING")
        self._output_drained.clear()
        for offset in range(0, len(data), 2400):
            chunk = data[offset:offset + 2400]
            try:
                self._output_queue.put_nowait(chunk)
            except queue.Full:
                try:
                    self._output_queue.get_nowait()
                    self._output_queue.put_nowait(chunk)
                except (queue.Empty, queue.Full):
                    pass

    def interrupt(self) -> None:
        self._interrupt_requested = True
        self.set_state("INTERRUPTED")
        with self._output_lock:
            self._pending_output.clear()
        while True:
            try:
                self._output_queue.get_nowait()
            except queue.Empty:
                break
        self._output_drained.set()
        self._interrupt_requested = False
        self.set_state("LISTENING")

    async def reconnect(self) -> Any:
        self.set_state("RECONNECTING")
        await self.close()
        return await self.connect()

    async def stop(self) -> None:
        self.active = False
        self.set_state("STOPPED")
        await self.close()

    async def close(self) -> None:
        if self.session_context is not None:
            try:
                await self.session_context.__aexit__(None, None, None)
            except Exception:
                pass
        self.session_context = None
        self.session = None
        self.connected = False
        if self._microphone_stream is not None:
            try:
                self._microphone_stream.stop()
            except Exception:
                pass
            try:
                self._microphone_stream.close()
            except Exception:
                pass
            self._microphone_stream = None
        if self._speaker_stream is not None:
            try:
                self._speaker_stream.stop()
            except Exception:
                pass
            try:
                self._speaker_stream.close()
            except Exception:
                pass
            self._speaker_stream = None

    def __repr__(self) -> str:
        return f"GeminiLiveSessionManager(state={self.state}, model={self.model!r})"
