from ollama import chat

response = chat(
    model="llama3.2",
    messages=[
        {
            "role": "user",
            "content": "Say hello and tell me you are ready to assist me."
        }
    ]
)

print("\nAI:")
print(response["message"]["content"])