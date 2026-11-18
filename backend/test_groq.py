import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

api_key = os.getenv("GROQ_API_KEY")

if not api_key:
    print("ERROR: GROQ_API_KEY not found in .env")
    raise SystemExit(1)

client = Groq(api_key=api_key)

try:
    response = client.chat.completions.create(
        model=os.getenv("GROQ_TRANSLATION_MODEL", "openai/gpt-oss-20b"),
        messages=[
            {
                "role": "user",
                "content": "Translate Hello into Hindi. Return only the translation."
            }
        ],
        max_completion_tokens=100,
    )

    print("SUCCESS: Groq API is working!")
    print("Response:", response.choices[0].message.content)

except Exception as e:
    print("FAILED")
    print("Error type:", type(e).__name__)
    print("HTTP status:", getattr(e, "status_code", "N/A"))
    print("Check the provider error details locally.")