import json
from ollama import chat


MODEL = "llama3.2"


SYSTEM_PROMPT = """
You are the command parser for a Windows voice automation system.

Your job is to convert the user's natural language command into JSON.

You MUST return ONLY valid JSON.

Supported actions:

1. open_application
2. close_application
3. open_website
4. web_search
5. system_status
6. list_files
7. read_file
8. write_file
9. open_file
10. unknown

JSON format:

{
    "action": "ACTION_NAME",
    "target": "TARGET",
    "query": "QUERY",
    "content": "CONTENT"
}

Rules:

- For open_application:
  target = application name

- For close_application:
  target = application name

- For open_website:
  target = website name or URL

- For web_search:
  query = search query

- For system_status:
  target = cpu, ram, gpu, disk, battery, or all

- For list_files:
  target = directory path

- For read_file:
  target = file path

- For write_file:
  target = file path
  content = exact text that should be written into the file

- For open_file:
  target = file or folder path

- If the command doesn't match a supported action:
  action = unknown

IMPORTANT:

Return null for fields that are not required.

Do not invent file paths.

Do not add explanations.

Do not use markdown.

Return JSON only.
"""


def parse_command(user_text):

    response = chat(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": user_text
            }
        ]
    )

    raw_response = response["message"]["content"].strip()

    try:

        command = json.loads(raw_response)

        return command

    except json.JSONDecodeError:

        return {
            "action": "unknown",
            "target": None,
            "query": None,
            "content": None,
            "raw_response": raw_response
        }


if __name__ == "__main__":

    print("VOICE AUTOMATION COMMAND PARSER")
    print("--------------------------------")

    while True:

        user_text = input("\nCommand: ")

        if user_text.lower() in ["exit", "quit"]:
            break

        command = parse_command(user_text)

        print("\nParsed command:")

        print(
            json.dumps(
                command,
                indent=4
            )
        )