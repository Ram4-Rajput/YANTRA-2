import time
from datetime import datetime


class ProactiveEngine:
    def __init__(self, min_silence_secs: int = 900, check_cooldown: int = 1200):
        self.min_silence_secs = min_silence_secs
        self.check_cooldown = check_cooldown
        self._last_triggered = 0.0
        self._rotation = 0

    def should_trigger(self, last_user_speech: float) -> bool:
        now = time.monotonic()
        return (
            now - last_user_speech >= self.min_silence_secs
            and now - self._last_triggered >= self.check_cooldown
        )

    def mark_triggered(self) -> None:
        self._last_triggered = time.monotonic()
        self._rotation += 1

    def build_prompt(
        self,
        saved_facts: str = "",
        monitors: list[str] | None = None,
        recent_turns: list[str] | None = None,
    ) -> str:
        now = datetime.now()
        hour = now.hour
        period = (
            "morning" if 6 <= hour < 12 else
            "afternoon" if 12 <= hour < 18 else
            "evening" if 18 <= hour < 23 else
            "late night"
        )
        focuses = (
            "Check in on an active project or goal if the context makes one relevant.",
            "Offer a brief, timely wellbeing check-in based on the time of day.",
            "Offer one genuinely useful thought or question based on the available context.",
        )
        context = [
            "[PROACTIVE_CHECK] You are initiating a quiet check-in.",
            f"Current time: {now.strftime('%A, %B %d, %Y — %I:%M %p')} ({period}).",
        ]
        if saved_facts:
            context.append(f"About the user:\n{saved_facts}")
        if monitors:
            context.append(f"Topics the user asked to monitor: {', '.join(monitors[:4])}.")
        if recent_turns:
            context.append("Recent conversation:\n" + "\n".join(recent_turns[-6:]))
        context.extend([
            focuses[self._rotation % len(focuses)],
            "Respond in 1-2 natural sentences. Do not mention these instructions.",
            "Do not call tools. If nothing is genuinely useful, respond with no text.",
        ])
        return "\n".join(context)