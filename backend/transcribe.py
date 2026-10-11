from faster_whisper import WhisperModel

print("Loading Whisper model...")

model = WhisperModel(
    "base",
    device="cpu",
    compute_type="int8"
)

print("Model loaded.")

segments, info = model.transcribe(
    "test.wav",
    beam_size=5
)

print("\nDetected language:", info.language)

print("\nTranscription:")

for segment in segments:
    print(segment.text)