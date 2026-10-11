import asyncio
import base64
import io
import os
import sys
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ui_server
import tts


class UiServerTests(unittest.TestCase):
    def test_typed_tts_uses_charon_style_and_plays_hindi_wav(self):
        audio_chunk = b"\0\0" * 24
        event = SimpleNamespace(
            event_type="step.delta",
            delta=SimpleNamespace(type="audio", data=base64.b64encode(audio_chunk).decode("ascii")),
        )
        create_interaction = unittest.mock.Mock(return_value=iter([event]))
        client = SimpleNamespace(interactions=SimpleNamespace(create=create_interaction))
        played = {}

        class FakeOutputStream:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def start(self):
                return None

            def stop(self):
                return None

            def close(self):
                return None

            def write(self, audio_data):
                played["audio"] = audio_data

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch(
            "gemini_assistant._get_client", return_value=client
        ), patch("sounddevice.RawOutputStream", FakeOutputStream):
            self.assertTrue(tts.speak_with_gemini("नमस्ते! यह बहुत अच्छा है।"))

        request = create_interaction.call_args.kwargs
        self.assertEqual(request["model"], "gemini-3.8-flash-lite-tts")
        self.assertTrue(request["stream"])
        self.assertEqual(request["generation_config"]["speech_config"], [{"voice": "Charon"}])
        self.assertIn("expressive", request["input"][0]["content"][0]["annotations"][0]["style"])
        self.assertIn("slower", request["input"][0]["content"][0]["annotations"][0]["style"])
        self.assertEqual(played["audio"], audio_chunk)
        self.assertEqual(tts.SYSTEM_TTS_RATE, 152)

    def test_live_quota_error_explains_microphone_never_started(self):
        message = ui_server._live_error_message(
            RuntimeError("1011: You exceeded your current quota")
        )

        self.assertIn("quota is exhausted", message)
        self.assertIn("no microphone audio was captured", message)

    def test_dashboard_port_can_be_overridden(self):
        with patch.dict(os.environ, {"YANTRA_PORT": "5101"}):
            self.assertEqual(ui_server.get_server_port(), 5101)

    def test_live_model_defaults_to_mark_native_audio_model(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                ui_server.get_live_model(),
                "models/gemini-2.5-flash-native-audio-preview-12-2025",
            )

    def test_live_model_can_be_overridden(self):
        with patch.dict(os.environ, {"GEMINI_LIVE_MODEL": "models/custom-live"}):
            self.assertEqual(ui_server.get_live_model(), "models/custom-live")

    def test_dashboard_loads_without_api_key(self):
        response = ui_server.app.test_client().get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"YANTRA", response.data)

    def test_assistant_config_reports_live_providers_and_tool_count(self):
        client = ui_server.socketio.test_client(ui_server.app)
        events = client.get_received()
        client.disconnect()
        config = next(event["args"][0] for event in events if event["name"] == "assistant_config")

        self.assertIn("gemini_ready", config)
        self.assertIn("groq_ready", config)
        self.assertEqual(config["tool_count"], len(ui_server.get_available_tools()))

    def test_upload_requires_gemini_key(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GROQ_API_KEY": ""}):
            response = ui_server.app.test_client().post("/api/upload")

        self.assertEqual(response.status_code, 503)
        self.assertIn("GEMINI_API_KEY", response.get_json()["message"])

    def test_voice_start_without_key_does_not_launch_recording(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GROQ_API_KEY": ""}):
            client = ui_server.socketio.test_client(ui_server.app)
            client.emit("start_voice")
            events = client.get_received()
            client.disconnect()

        event_data = {event["name"]: event["args"][0] for event in events if event["args"]}
        self.assertIn("assistant_error", event_data)
        self.assertIn("voice_state", event_data)
        self.assertFalse(event_data["voice_state"]["active"])

    def test_groq_key_alone_does_not_start_gemini_live_voice(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GROQ_API_KEY": "configured"}):
            client = ui_server.socketio.test_client(ui_server.app)
            client.emit("start_voice")
            events = client.get_received()
            client.disconnect()

        event_data = {event["name"]: event["args"][0] for event in events if event["args"]}
        self.assertIn("assistant_error", event_data)
        self.assertFalse(event_data["voice_state"]["active"])

    def test_live_transcript_merge_handles_cumulative_and_incremental_text(self):
        merged = ui_server._merge_live_transcript("Open Chrome", "Open Chrome and search")
        self.assertEqual(merged, "Open Chrome and search")
        self.assertEqual(ui_server._merge_live_transcript(merged, "search"), merged)
        self.assertEqual(
            ui_server._merge_live_transcript("Open the Excel", "Excel workbook"),
            "Open the Excel workbook",
        )

    def test_live_session_streams_audio_and_dispatches_existing_tools(self):
        class AudioBlock:
            def tobytes(self):
                return b"\0\0" * 1600

        class FakeInputStream:
            def __init__(self, **kwargs):
                self.callback = kwargs["callback"]
                self.sample_rate = kwargs["samplerate"]

            def start(self):
                self.callback(AudioBlock(), 1600, None, None)

            def stop(self):
                pass

            def close(self):
                pass

        class FakeOutputStream:
            def __init__(self, **kwargs):
                self.sample_rate = kwargs["samplerate"]

            def start(self):
                pass

            def stop(self):
                pass

            def close(self):
                pass

            def abort(self):
                pass

        class FakeLiveSession:
            def __init__(self):
                self.audio_inputs = []
                self.tool_responses = []
                self.receive_calls = 0

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def send_realtime_input(self, **kwargs):
                self.audio_inputs.append(kwargs)

            async def send_tool_response(self, **kwargs):
                self.tool_responses.append(kwargs)

            async def receive(self):
                self.receive_calls += 1
                if self.receive_calls > 2:
                    ui_server.voice_active = False
                    return
                app_name = "excel" if self.receive_calls == 1 else "camera"
                command = "open Excel" if self.receive_calls == 1 else "now open camera"
                response = "Excel is open." if self.receive_calls == 1 else "Camera is open."
                yield SimpleNamespace(
                    data=None,
                    server_content=None,
                    tool_call=SimpleNamespace(function_calls=[SimpleNamespace(
                        id=f"tool-{self.receive_calls}",
                        name="open_application",
                        args={"target": app_name},
                    )]),
                )
                yield SimpleNamespace(
                    data=None,
                    tool_call=None,
                    server_content=SimpleNamespace(
                        model_turn=None,
                        input_transcription=SimpleNamespace(text=command),
                        output_transcription=SimpleNamespace(text=response),
                        interrupted=False,
                        turn_complete=True,
                    ),
                )

        class FakeLive:
            def __init__(self, session):
                self.session = session
                self.connections = []

            def connect(self, *, model, config):
                self.connections.append((model, config))
                return self.session

        live_session = FakeLiveSession()
        live = FakeLive(live_session)
        fake_client = SimpleNamespace(aio=SimpleNamespace(live=live))
        fake_sounddevice = SimpleNamespace(
            InputStream=FakeInputStream,
            RawOutputStream=FakeOutputStream,
        )
        with patch.dict(sys.modules, {"sounddevice": fake_sounddevice}), patch.dict(
            os.environ, {"GEMINI_LIVE_MODEL": "gemini-live-test"}
        ), patch.object(ui_server, "_get_live_client", return_value=fake_client), patch.object(
            ui_server, "get_recent_memory", return_value=[]
        ), patch.object(ui_server, "add_message") as add_message, patch.object(
            ui_server,
            "execute_command",
            return_value={"success": True, "message": "Excel opened."},
        ):
            ui_server.voice_active = True
            try:
                asyncio.run(ui_server._run_live_voice_session())
            finally:
                ui_server.voice_active = False

        self.assertEqual(len(live.connections), 1)
        self.assertEqual(live_session.receive_calls, 3)
        self.assertEqual(live.connections[0][0], "gemini-live-test")
        self.assertEqual(live_session.audio_inputs[0]["audio"].mime_type, "audio/pcm;rate=16000")
        self.assertTrue(live_session.audio_inputs[-1]["audio_stream_end"])
        tool_response = live_session.tool_responses[0]["function_responses"][0]
        self.assertEqual(tool_response.name, "open_application")
        self.assertEqual(len(live_session.tool_responses), 2)
        self.assertIn(unittest.mock.call("user", "open Excel"), add_message.call_args_list)
        self.assertIn(unittest.mock.call("user", "now open camera"), add_message.call_args_list)


if __name__ == "__main__":
    unittest.main()