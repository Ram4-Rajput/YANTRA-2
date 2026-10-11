import numpy as np
import sounddevice as sd

from faster_whisper import WhisperModel

from gemini_assistant import run_assistant as run_agent
from tts import speak


# ============================================================
# CONFIGURATION
# ============================================================

SAMPLE_RATE = 16000

WAKE_DURATION = 3

COMMAND_DURATION = 5

WAKE_WORDS = [
    "hey assistant",
    "assistant",
    "computer",
    "pragati",
]


# ============================================================
# WHISPER
# ============================================================

print(
    "\nLoading Whisper model..."
)

whisper_model = WhisperModel(
    "base",
    device="cpu",
    compute_type="int8"
)

print(
    "Whisper loaded."
)


# ============================================================
# RECORD AUDIO
# ============================================================

def record_audio(
    duration
):

    print(
        f"\n🎤 Listening for {duration} seconds..."
    )

    audio = sd.rec(
        int(
            duration * SAMPLE_RATE
        ),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32"
    )

    sd.wait()

    return np.squeeze(
        audio
    )


# ============================================================
# TRANSCRIBE
# ============================================================

def transcribe(
    audio
):

    try:

        segments, info = whisper_model.transcribe(
            audio,
            language="en",
            task="transcribe",
            beam_size=5,
            best_of=5,
            temperature=0,
            vad_filter=True,
            condition_on_previous_text=False,
            initial_prompt=(
                "Hey assistant. "
                "Open Chrome. "
                "Open Notepad. "
                "Look at my screen. "
                "Search Google. "
                "Check my computer."
            )
        )

        text = " ".join(
            segment.text
            for segment in segments
        ).strip()

        return text

    except Exception as e:

        print(
            f"❌ Transcription error: {e}"
        )

        return ""


# ============================================================
# WAKE WORD
# ============================================================

def wake_detected(
    text
):

    text = text.lower().strip()

    for wake_word in WAKE_WORDS:

        if wake_word in text:

            return True

    return False


# ============================================================
# LISTEN FOR WAKE WORD
# ============================================================

def listen_for_wake_word():

    audio = record_audio(
        WAKE_DURATION
    )

    text = transcribe(
        audio
    )

    if text:

        print(
            f"👂 Heard: {text}"
        )

    return wake_detected(
        text
    )


# ============================================================
# LISTEN FOR COMMAND
# ============================================================

def listen_for_command():

    audio = record_audio(
        COMMAND_DURATION
    )

    text = transcribe(
        audio
    )

    if text:

        print(
            f"🗣 Command: {text}"
        )

    return text


# ============================================================
# PROCESS COMMAND
# ============================================================

def process_command(
    text
):

    if not text:

        return

    try:

        result = run_agent(
            text
        )

        response = result.get(
            "message",
            "I couldn't complete that."
        )

        print()
        print(
            f"🤖 Assistant: {response}"
        )

        speak(
            response
        )

    except Exception as e:

        print(
            f"❌ Command processing error: {e}"
        )

        speak(
            "I encountered an error while processing that request."
        )


# ============================================================
# MAIN LOOP
# ============================================================

def main():

    print()
    print(
        "========================================"
    )

    print(
        "      DESKTOP AI ASSISTANT"
    )

    print(
        "========================================"
    )

    print()
    print(
        "Wake words:"
    )

    print(
        ", ".join(
            WAKE_WORDS
        )
    )

    print()
    print(
        "Assistant is ready."
    )

    print(
        "Press Ctrl+C to stop."
    )

    while True:

        try:

            detected = listen_for_wake_word()

            if not detected:

                continue

            print()
            print(
                "🔔 Wake word detected."
            )

            speak(
                "Yes?"
            )

            command = listen_for_command()

            if not command:

                continue

            process_command(
                command
            )

        except KeyboardInterrupt:

            print()
            print(
                "Assistant stopped."
            )

            break

        except Exception as e:

            print()
            print(
                f"❌ Main loop error: {e}"
            )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()