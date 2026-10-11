import sounddevice as sd
from faster_whisper import WhisperModel

from gemini_assistant import run_assistant as run_agent
from tts import speak


SAMPLE_RATE = 16000
DURATION = 5


def main():
    print("Loading Whisper...")
    whisper = WhisperModel("base", device="cpu", compute_type="int8")
    print("YANTRA voice interface ready. Press Enter, then speak.")
    speak("YANTRA voice interface ready. Press Enter, then speak.")

    while True:
        input("\nPress ENTER to speak, or Ctrl+C to exit...")
        print("Listening...")
        audio = sd.rec(
            int(DURATION * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
        )
        sd.wait()
        segments, _ = whisper.transcribe(
            audio,
            language="en",
            task="transcribe",
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        if not text:
            print("I didn't hear anything.")
            continue

        print(f"You: {text}")
        result = run_agent(text)
        response = result.get("message", "I couldn't complete that request.")
        print(f"YANTRA: {response}")
        speak(response)


if __name__ == "__main__":
    main()

