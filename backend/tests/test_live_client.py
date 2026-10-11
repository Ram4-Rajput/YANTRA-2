import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from live_client import GeminiLiveSessionManager


class LiveClientTests(unittest.TestCase):
    def test_manager_tracks_live_state_and_interrupt(self):
        state_log = []
        manager = GeminiLiveSessionManager(
            model="gemini-live-test",
            on_state=lambda state: state_log.append(state),
        )

        manager.set_state("CONNECTING")
        manager.set_state("CONNECTED")
        manager.set_state("LISTENING")
        manager.interrupt()
        manager.set_state("STOPPED")

        self.assertEqual(state_log[:4], ["CONNECTING", "CONNECTED", "LISTENING", "INTERRUPTED"])
        self.assertIn("STOPPED", state_log)
        self.assertIn(manager.current_state(), "STOPPED")

    def test_manager_exposes_live_lifecycle_methods(self):
        manager = GeminiLiveSessionManager(model="gemini-live-test")

        self.assertTrue(hasattr(manager, "start"))
        self.assertTrue(hasattr(manager, "connect"))
        self.assertTrue(hasattr(manager, "stream_microphone"))
        self.assertTrue(hasattr(manager, "receive_responses"))
        self.assertTrue(hasattr(manager, "play_audio"))
        self.assertTrue(hasattr(manager, "interrupt"))
        self.assertTrue(hasattr(manager, "reconnect"))
        self.assertTrue(hasattr(manager, "stop"))
        self.assertTrue(hasattr(manager, "close"))


if __name__ == "__main__":
    unittest.main()
