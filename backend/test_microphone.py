import sounddevice as sd

print("Available audio devices:")
print(sd.query_devices())

print("\nDefault input device:")
print(sd.query_devices(kind="input"))