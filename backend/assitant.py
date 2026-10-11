import sounddevice as sd
from scipy.io.wavfile import write
from faster_whisper import WhisperModel

SAMPLE_RATE = 16000
DURATION = 5

model = WhisperModel(
    "base",
    device="cpu",
    compute_type="int8"
)

print("================================")
print("     VOICE AUTOMATION SYSTEM")
print("================================")

while True:

    input("\nPress ENTER to speak...")

    print("🎤 Listening...")

    audio = sd.rec(
        int(DURATION * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16"
    )

    sd.wait()

    write("temp.wav", SAMPLE_RATE, audio)

    print("🧠 Processing...")

    segments, info = model.transcribe(
        "temp.wav",
        beam_size=5
    )

    text = ""

    for segment in segments:
        text += segment.text

    print(f"\nYou: {text}")
    