"""Manual Groq smoke script. Importing this module must never call Groq."""

import argparse
import os

from dotenv import load_dotenv
from groq import Groq


def main(*, live: bool = False) -> int:
    """Run one explicitly requested live translation; no CI test imports may bill."""

    if not live:
        print("REFUSED: pass --live to allow one billable Groq request")
        return 2
    load_dotenv()
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("ERROR: GROQ_API_KEY is not configured")
        return 1

    try:
        with Groq(api_key=api_key) as client:
            response = client.chat.completions.create(
                model=os.getenv("GROQ_TRANSLATION_MODEL", "openai/gpt-oss-20b"),
                messages=[
                    {"role": "user", "content": "Translate Hello into Hindi. Return only the translation."}
                ],
                max_completion_tokens=100,
            )
        print("SUCCESS: Groq API is working!")
        print("Response:", response.choices[0].message.content)
        return 0
    except Exception as exc:
        print("FAILED")
        print("Error type:", type(exc).__name__)
        print("HTTP status:", getattr(exc, "status_code", "N/A"))
        print("Check the provider error details locally.")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Allow one billable Groq translation request")
    args = parser.parse_args()
    raise SystemExit(main(live=args.live))
