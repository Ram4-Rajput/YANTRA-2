import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gemini_assistant
from tools.vision import capture_screen
from mark_actions import state as mark_state
from mark_actions.proactive import ProactiveEngine
from pathlib import Path
import tempfile
from tools.register import execute_tool


class FakeModels:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def generate_content(self, **kwargs):
        self.requests.append(kwargs)
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        return response


class FakeClient:
    def __init__(self, responses):
        self.models = FakeModels(responses)
        self.files = FakeFiles()


def text_response(text):
    candidate = SimpleNamespace(
        content=SimpleNamespace(parts=[SimpleNamespace(text=text)]),
        grounding_metadata=None,
    )
    return SimpleNamespace(candidates=[candidate])


class FakeFiles:
    def __init__(self):
        self.deleted = []

    def upload(self, file):
        return SimpleNamespace(name="files/test", uri="https://file.invalid/test", mime_type="application/json")

    def delete(self, name):
        self.deleted.append(name)


class GeminiAssistantTests(unittest.TestCase):
    def setUp(self):
        memory_patcher = patch.object(gemini_assistant, "get_recent_memory", return_value=[])
        message_patcher = patch.object(gemini_assistant, "add_message")
        memory_patcher.start()
        message_patcher.start()
        self.addCleanup(memory_patcher.stop)
        self.addCleanup(message_patcher.stop)

    def test_live_config_uses_native_audio_vad_and_existing_tools(self):
        config = gemini_assistant.build_live_config()

        self.assertEqual(config.response_modalities, [gemini_assistant.types.Modality.AUDIO])
        self.assertIsNotNone(config.session_resumption)
        self.assertEqual(
            config.speech_config.voice_config.prebuilt_voice_config.voice_name,
            "Charon",
        )
        self.assertIn("VOICE DELIVERY", config.system_instruction)
        self.assertIn("Support both English and Hindi", config.system_instruction)
        self.assertIn("do not suppress the emotion", config.system_instruction)
        self.assertFalse(config.realtime_input_config.automatic_activity_detection.disabled)
        self.assertEqual(
            config.realtime_input_config.activity_handling,
            gemini_assistant.types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
        )
        declared = {
            declaration.name
            for tool in config.tools
            for declaration in (tool.function_declarations or [])
        }
        self.assertIn("open_application", declared)
        self.assertIn("capture_screen", declared)
        self.assertIn("weather_report", declared)
        self.assertIn("youtube_video", declared)
        self.assertIn("flight_finder", declared)
        self.assertIn("reminder", declared)
        self.assertIn("computer_settings", declared)
        self.assertIn("browser_control", declared)
        self.assertIn("file_controller", declared)
        self.assertIn("code_helper", declared)
        self.assertIn("game_updater", declared)
        self.assertIn("manage_monitor", declared)
        self.assertIn("save_memory", declared)
        self.assertIn("shutdown_yantra", declared)
        self.assertTrue(any(tool.google_search for tool in config.tools))

    def test_live_config_accepts_session_memory_in_system_instruction(self):
        config = gemini_assistant.build_live_config("Recent context: user opened Chrome")

        self.assertEqual(config.system_instruction, "Recent context: user opened Chrome")

    def test_live_config_includes_saved_user_facts(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(mark_state, "MEMORY_PATH", Path(folder) / "long_term.json"):
                mark_state.save_memory({
                    "category": "preferences", "key": "language", "value": "English"
                })
                config = gemini_assistant.build_live_config()

        self.assertIn("preferences/language: English", config.system_instruction)

    def test_typed_request_includes_saved_user_facts(self):
        client = FakeClient([text_response("Hello." )])
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(mark_state, "MEMORY_PATH", Path(folder) / "long_term.json"), patch.dict(
                os.environ, {"GEMINI_API_KEY": "test-key"}
            ), patch.object(gemini_assistant, "FALLBACK_MODELS", []):
                mark_state.save_memory({
                    "category": "preferences", "key": "language", "value": "English"
                })
                result = gemini_assistant.run_assistant("Hello", client=client)

        self.assertTrue(result["success"])
        self.assertIn(
            "preferences/language: English",
            client.models.requests[0]["config"].system_instruction,
        )

    def test_function_tool_schemas_support_typed_and_array_arguments(self):
        tool = gemini_assistant._fn("typed_tool", "A typed test tool.", {
            "count": {"type": "INTEGER", "description": "A count."},
            "enabled": {"type": "BOOLEAN", "description": "Whether it is enabled."},
            "labels": {
                "type": "ARRAY",
                "description": "Labels to apply.",
                "items": {"type": "STRING", "description": "One label."},
            },
        })

        properties = tool.function_declarations[0].parameters.properties
        self.assertEqual(properties["count"].type, gemini_assistant.types.Type.INTEGER)
        self.assertEqual(properties["enabled"].type, gemini_assistant.types.Type.BOOLEAN)
        self.assertEqual(properties["labels"].items.type, gemini_assistant.types.Type.STRING)

    def test_live_client_uses_beta_api_without_changing_typed_client(self):
        fake_client = object()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch.object(
            gemini_assistant.genai, "Client", return_value=fake_client
        ) as client_factory:
            result = gemini_assistant._get_live_client()

        self.assertIs(result, fake_client)
        client_factory.assert_called_once_with(
            api_key="test-key",
            http_options={"api_version": "v1beta"},
        )

    def test_greeting_returns_a_conversational_response(self):
        client = FakeClient([text_response("Good morning. YANTRA is online.")])

        result = gemini_assistant.run_assistant("Hello", client=client)

        self.assertTrue(result["success"])
        self.assertIn("Good morning", result["message"])
        self.assertEqual(result["actions"], [])
        self.assertIsNone(client.models.requests[0]["config"].tools)

    def test_function_call_executes_and_returns_a_final_answer(self):
        tool_call = SimpleNamespace(name="system_status", args={"target": "all"})
        initial = SimpleNamespace(candidates=[SimpleNamespace(
            content=SimpleNamespace(parts=[SimpleNamespace(function_call=tool_call)]),
            grounding_metadata=None,
        )])
        final = text_response("CPU is at 12 percent.")
        client = FakeClient([initial, final])
        with patch.object(
            gemini_assistant,
            "execute_command",
            return_value={"success": True, "message": "CPU: 12%"},
        ) as execute:
            result = gemini_assistant.run_assistant("How is my PC?", client=client)

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "CPU is at 12 percent.")
        execute.assert_called_once_with({"_tool_name": "system_status", "target": "all"})
        function_result = client.models.requests[1]["contents"][-1].parts[0].function_response
        self.assertEqual(function_result.name, "system_status")
        self.assertEqual(function_result.response["message"], "CPU: 12%")

    def test_missing_key_returns_setup_guidance_without_network_call(self):
        with patch.dict(os.environ, {}, clear=True):
            result = gemini_assistant.run_assistant("Hello")

        self.assertFalse(result["success"])
        self.assertIn("GEMINI_API_KEY", result["message"])

    def test_quota_error_is_explained_clearly(self):
        client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=Mock(side_effect=RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded"))
            )
        )

        with patch.dict(os.environ, {"GROQ_API_KEY": ""}), patch.object(
            gemini_assistant, "_get_groq_client", return_value=None
        ):
            result = gemini_assistant.run_assistant("Hello", client=client)

        self.assertFalse(result["success"])
        self.assertIn("project", result["message"])
        self.assertIn("quota", result["message"])
        self.assertIn("same project", result["message"])

    def test_groq_fallback_handles_live_search_after_gemini_quota(self):
        gemini_client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=Mock(side_effect=RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded"))
            )
        )
        message = SimpleNamespace(
            content="Here are the latest headlines.",
            executed_tools=[SimpleNamespace(
                browser_results=[SimpleNamespace(title="News source", url="https://news.invalid/latest")],
                search_results=None,
            )],
        )
        groq_call = Mock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=message)]))
        groq_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=groq_call))
        )

        with patch.dict(os.environ, {
            "GEMINI_API_KEY": "test-gemini-key",
            "GEMINI_MODEL": "gemini-flash-latest",
            "GROQ_API_KEY": "test-groq-key",
            "GROQ_MODEL": "openai/gpt-oss-20b",
            "GROQ_SEARCH_MODEL": "compound-beta",
        }), patch.object(gemini_assistant, "FALLBACK_MODELS", []), patch.object(
            gemini_assistant, "_get_client", return_value=gemini_client
        ), patch.object(gemini_assistant, "_get_groq_client", return_value=groq_client):
            result = gemini_assistant.run_assistant("Tell me the latest news")

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Here are the latest headlines.")
        self.assertEqual(result["sources"][0]["url"], "https://news.invalid/latest")
        request = groq_call.call_args.kwargs
        self.assertEqual(request["model"], "compound-beta")
        self.assertEqual(request["tools"], [{"type": "browser_search"}])
        self.assertEqual(request["tool_choice"], "required")

    def test_groq_search_reports_unavailable_compound_access(self):
        groq_call = Mock(side_effect=RuntimeError("404 model_not_found: groq/compound"))
        groq_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=groq_call))
        )

        with patch.dict(os.environ, {
            "GROQ_API_KEY": "test-groq-key",
            "GROQ_SEARCH_MODEL": "compound-beta",
        }), patch.object(gemini_assistant, "_get_groq_client", return_value=groq_client):
            result = gemini_assistant._run_groq_fallback("Tell me the latest news")

        self.assertFalse(result["success"])
        self.assertIn("Compound model", result["message"])
        self.assertIn("live web search", result["message"])

    def test_excel_workbook_without_path_asks_for_filename(self):
        result = gemini_assistant.run_assistant("open excel file")

        self.assertTrue(result["success"])
        self.assertIn("Which Excel workbook", result["message"])
        self.assertEqual(result["actions"], [])

    def test_unverified_action_claim_is_not_returned_as_success(self):
        response = SimpleNamespace(
            candidates=[SimpleNamespace(content=SimpleNamespace(parts=[
                SimpleNamespace(text="I have located and opened the file for you, sir.")
            ]))]
        )
        client = SimpleNamespace(
            models=SimpleNamespace(generate_content=Mock(return_value=response))
        )

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch.object(
            gemini_assistant, "FALLBACK_MODELS", []
        ):
            result = gemini_assistant.run_assistant("ya try", client=client)

        self.assertFalse(result["success"])
        self.assertIn("I haven't performed that action", result["message"])

    def test_excel_and_camera_are_selected_as_applications(self):
        tool_names = {
            tool.function_declarations[0].name
            for tool in gemini_assistant._select_tools("open Excel")
        }
        self.assertIn("open_application", tool_names)

    def test_mark_integrations_are_selected_for_typed_requests(self):
        requests = {
            "weather_report": "what is the weather in Delhi",
            "youtube_video": "play a YouTube video about Python",
            "flight_finder": "find flights from Delhi to Mumbai",
        }
        for expected_tool, request in requests.items():
            with self.subTest(request=request):
                tool_names = {
                    tool.function_declarations[0].name
                    for tool in gemini_assistant._select_tools(request)
                    if tool.function_declarations
                }
                self.assertIn(expected_tool, tool_names)

    def test_webcam_requests_select_vision_tool(self):
        tool_names = {
            tool.function_declarations[0].name
            for tool in gemini_assistant._select_tools("Take a picture with my webcam")
            if tool.function_declarations
        }
        self.assertIn("capture_screen", tool_names)

    def test_camera_capture_releases_device_after_single_frame(self):
        from types import SimpleNamespace
        camera = SimpleNamespace(
            isOpened=lambda: True,
            read=lambda: (True, object()),
            release=Mock(),
        )
        cv2 = SimpleNamespace(
            VideoCapture=Mock(return_value=camera),
            imwrite=Mock(return_value=True),
        )
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, {"cv2": cv2}):
            result = capture_screen(
                path=Path(folder) / "camera.jpg",
                source="camera",
                camera_index=0,
            )

        self.assertTrue(result["success"])
        camera.release.assert_called_once_with()

    def test_mark_weather_action_routes_through_shared_tool_registry(self):
        with patch("webbrowser.open", return_value=True):
            result = execute_tool({"action": "weather_report", "city": "Delhi"})

        self.assertTrue(result["success"])
        self.assertIn("Delhi", result["message"])

    def test_browser_search_opens_results_in_requested_chrome(self):
        with patch("subprocess.Popen") as popen:
            result = execute_tool({
                "action": "web_search",
                "query": "BMW cars",
                "browser": "chrome",
            })

        self.assertTrue(result["success"])
        command = popen.call_args.args[0]
        self.assertEqual(command[0], r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        self.assertIn("BMW+cars", command[1])

    def test_logged_chrome_search_phrase_executes_open_then_search(self):
        with patch.object(gemini_assistant, "execute_command", side_effect=[
            {"success": True, "message": "Chrome opened."},
            {"success": True, "message": "Search opened."},
        ]) as execute:
            result = gemini_assistant.run_assistant("open chrome and serach cars on it")

        self.assertTrue(result["success"])
        self.assertEqual([item["action"] for item in result["actions"]], [
            "open_application", "web_search"
        ])
        self.assertEqual(execute.call_args_list[1].args[0], {
            "action": "web_search", "query": "cars", "browser": "chrome"
        })

    def test_excel_typo_blank_workbook_request_executes_com_action(self):
        with patch.object(
            gemini_assistant,
            "execute_command",
            return_value={"success": True, "message": "A new blank Excel workbook is open."},
        ) as execute:
            result = gemini_assistant.run_assistant("general excell sheet so that i can work")

        self.assertTrue(result["success"])
        self.assertEqual(execute.call_args.args[0], {"action": "open_blank_excel"})

    def test_khali_sheet_follow_up_opens_excel_when_context_requests_it(self):
        with patch.object(gemini_assistant, "get_recent_memory", return_value=[
            {"role": "user", "content": "open a general Excel sheet"},
            {"role": "assistant", "content": "Would you like a blank sheet?"},
        ]), patch.object(
            gemini_assistant,
            "execute_command",
            return_value={"success": True, "message": "A new blank Excel workbook is open."},
        ) as execute:
            result = gemini_assistant.run_assistant("khali sheet")

        self.assertTrue(result["success"])
        self.assertIn("खाली workbook", result["message"])
        execute.assert_called_once_with({"action": "open_blank_excel"})

    def test_camera_question_captures_frame_and_attaches_it_for_analysis(self):
        client = FakeClient([text_response("I can see one person in the frame.")])
        image_bytes = b"fake-camera-frame"
        with tempfile.TemporaryDirectory() as folder:
            image_path = Path(folder) / "camera.jpg"
            image_path.write_bytes(image_bytes)
            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch.object(
                gemini_assistant, "FALLBACK_MODELS", []
            ), patch.object(
                gemini_assistant,
                "execute_command",
                return_value={"success": True, "message": "Camera frame captured.", "path": str(image_path)},
            ) as execute:
                result = gemini_assistant.run_assistant(
                    "who can you see in front of you check", client=client
                )

        execute.assert_called_once_with({"action": "capture_screen", "source": "camera"})
        self.assertTrue(result["success"])
        self.assertEqual(result["actions"][0]["action"], "capture_screen")
        image_part = client.models.requests[0]["contents"][-1].parts[1]
        self.assertEqual(image_part.inline_data.data, image_bytes)
        self.assertNotIn(
            "capture_screen",
            [declaration.name for tool in (client.models.requests[0]["config"].tools or [])
             for declaration in tool.function_declarations or []],
        )

    def test_blank_excel_action_creates_workbook_through_com(self):
        import types as python_types

        workbook = SimpleNamespace(Activate=Mock())
        excel_app = SimpleNamespace(Visible=False, Workbooks=SimpleNamespace(Add=Mock(return_value=workbook)))
        client_module = python_types.ModuleType("win32com.client")
        client_module.DispatchEx = Mock(return_value=excel_app)
        win32com_module = python_types.ModuleType("win32com")
        win32com_module.client = client_module
        pythoncom_module = SimpleNamespace(CoInitialize=Mock(), CoUninitialize=Mock())
        with patch.dict(sys.modules, {
            "pythoncom": pythoncom_module,
            "win32com": win32com_module,
            "win32com.client": client_module,
        }):
            result = execute_tool({"action": "open_blank_excel"})

        self.assertTrue(result["success"])
        self.assertTrue(excel_app.Visible)
        client_module.DispatchEx.assert_called_once_with("Excel.Application")
        workbook.Activate.assert_called_once_with()

    def test_nested_mark_browser_action_does_not_overwrite_tool_name(self):
        browser_call = Mock(return_value={"success": True, "message": "Searched for cars."})
        fake_module = type("BrowserModule", (), {"browser_control": staticmethod(browser_call)})()
        with patch("mark_actions.adapter._load_action_module", return_value=fake_module):
            result = execute_tool({
                "_tool_name": "browser_control",
                "action": "search",
                "query": "cars",
                "browser": "chrome",
            })

        self.assertTrue(result["success"])
        self.assertEqual(browser_call.call_args.kwargs["parameters"], {
            "action": "search", "query": "cars", "browser": "chrome"
        })

    def test_mark_automation_tools_are_selected_for_typed_requests(self):
        requests = {
            "reminder": "remind me to study tomorrow",
            "browser_control": "click the login button in the browser",
            "file_controller": "delete the file at C:\\temp\\old.txt",
            "computer_settings": "turn the volume down",
            "game_updater": "update my Steam games",
            "code_helper": "debug this Python script",
            "dev_agent": "build a project for tracking expenses",
            "manage_monitor": "monitor AI news developments",
            "shutdown_yantra": "stop YANTRA",
        }
        for expected_tool, request in requests.items():
            with self.subTest(request=request):
                tool_names = {
                    tool.function_declarations[0].name
                    for tool in gemini_assistant._select_tools(request)
                    if tool.function_declarations
                }
                self.assertIn(expected_tool, tool_names)

    def test_mark_saved_memory_and_monitor_topics_use_isolated_storage(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(mark_state, "MEMORY_PATH", Path(folder) / "long_term.json"), patch.object(
                mark_state, "MONITORS_PATH", Path(folder) / "monitors.json"
            ):
                saved = mark_state.save_memory({
                    "category": "preferences", "key": "language", "value": "English"
                })
                added = mark_state.manage_monitor({"action": "add", "topic": "space exploration"})
                listed = mark_state.manage_monitor({"action": "list"})
                blocked = mark_state.manage_monitor({"action": "add", "topic": "bitcoin prices"})

        self.assertTrue(saved["success"])
        self.assertTrue(added["success"])
        self.assertIn("space exploration", listed["message"])
        self.assertFalse(blocked["success"])

    def test_monitored_topic_alerts_once_per_day_for_new_headlines(self):
        with tempfile.TemporaryDirectory() as folder:
            monitor_path = Path(folder) / "monitors.json"
            with patch.object(mark_state, "MONITORS_PATH", monitor_path):
                mark_state.manage_monitor({"action": "add", "topic": "space exploration"})
                search = Mock(return_value=[{
                    "title": "New lunar mission announced",
                    "snippet": "A new mission was announced.",
                    "source": "Example News",
                }])
                module = type("Search", (), {"_ddg_news": staticmethod(search)})()
                with patch("mark_actions.adapter._load_action_module", return_value=module):
                    first_alerts = mark_state.check_monitored_topics()
                    second_alerts = mark_state.check_monitored_topics()

        self.assertEqual(len(first_alerts), 1)
        self.assertIn("New lunar mission announced", first_alerts[0])
        self.assertEqual(second_alerts, [])
        search.assert_called_once_with("space exploration", max_results=5)

    def test_proactive_engine_observes_silence_and_cooldown(self):
        engine = ProactiveEngine(min_silence_secs=10, check_cooldown=20)
        with patch("mark_actions.proactive.time.monotonic", return_value=100):
            self.assertTrue(engine.should_trigger(90))
            engine.mark_triggered()
        with patch("mark_actions.proactive.time.monotonic", return_value=110):
            self.assertFalse(engine.should_trigger(90))

        prompt = engine.build_prompt(
            saved_facts="projects/demo: voice assistant",
            monitors=["space exploration"],
            recent_turns=["user: Make voice assistant reliable."],
        )
        self.assertIn("space exploration", prompt)
        self.assertIn("Make voice assistant reliable", prompt)

        tool_names = {
            tool.function_declarations[0].name
            for tool in gemini_assistant._select_tools("open camera")
        }
        self.assertIn("open_application", tool_names)

    def test_uploaded_json_is_attached_and_cloud_copy_is_deleted(self):
        client = FakeClient([text_response("The file contains a status value.")])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "status.json"
            path.write_text('{"status":"ready"}', encoding="utf-8")
            result = gemini_assistant.analyze_uploaded_files([path], "Summarize this", client=client)

        self.assertTrue(result["success"])
        request = client.models.requests[0]
        self.assertTrue(request["contents"][-1].parts[1].file_data)
        self.assertIn("status.json", request["contents"][-1].parts[0].text)
        self.assertEqual(client.files.deleted, ["files/test"])


if __name__ == "__main__":
    unittest.main()