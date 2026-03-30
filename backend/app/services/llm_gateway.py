import json


def _stub_master_variant_a() -> dict[str, str]:
    return {
        "subject": "Quick note — possible fit",
        "body": (
            "We are writing with a focused reason to connect: there is a plausible overlap between "
            "what you are building and an initiative we are running now.\n\n"
            "In practical terms, we can explain the fit in a short call or share a tight written "
            "summary — whichever you prefer — and we will keep jargon to a minimum.\n\n"
            "If this is useful, reply with one line about the best next step; if not, feel free to "
            "ignore and we will not follow up repeatedly.\n\n"
            "Thanks for your time."
        ),
    }


def _stub_master_variant_b() -> dict[str, str]:
    return {
        "subject": "Timing check on a narrow partnership angle",
        "body": (
            "I want to see whether this week is a sensible moment for a short conversation about a "
            "specific partnership angle.\n\n"
            "The background is straightforward: we line up a small set of counterparties where the fit "
            "is testable without a long procurement cycle.\n\n"
            "You can steer the format — written bullets first or a brief call — and we will keep the "
            "first exchange lightweight.\n\n"
            "If the topic is not relevant, a quick “pass” is enough; we will not re-litigate by email.\n\n"
            "Appreciated either way."
        ),
    }


def _stub_master_variant_c() -> dict[str, str]:
    return {
        "subject": "Direct note — working together",
        "body": (
            "This email is intentionally direct: we are deciding whether to include your organization "
            "in a short list for a concrete pilot.\n\n"
            "The pilot has a bounded scope, a clear success signal, and no open-ended “explore” phase "
            "without a decision point.\n\n"
            "If you want to qualify in or out, tell us what evidence would help on your side and we "
            "will mirror that level of detail.\n\n"
            "If you already know this is not a priority, one line is sufficient — we will stop there.\n\n"
            "We can also share a one-page scope note if that is easier than a live conversation on the first pass.\n\n"
            "Best regards"
        ),
    }


def generate_json(prompt: str, model: str = "stub", task_kind: str | None = None) -> dict:
    """
    Temporary stub. Replace with real provider later.
    Must always return parsed dict or raise ValueError.
    """
    if task_kind == "master_email":
        a, b, c = _stub_master_variant_a(), _stub_master_variant_b(), _stub_master_variant_c()
        return {"variants": [a, b, c]}

    prompt_lower = prompt.lower()

    # Order matters: later-step prompts embed earlier JSON (e.g. find_contacts INPUT contains "companies").
    if '"emails"' in prompt_lower or "outreach email" in prompt_lower:
        return {
            "emails": [
                {
                    "company": "Acme Corp",
                    "to": "contact@acme.example",
                    "subject": "Outreach — Acme Corp",
                    "body": "Hi,\n\nShort note relevant to your organization.\n\nBest regards",
                }
            ]
        }

    if '"contacts"' in prompt_lower or "decision makers" in prompt_lower or "target roles" in prompt_lower:
        return {
            "contacts": [
                {
                    "company": "Acme Corp",
                    "website": "https://acme.example",
                    "name": "Alex Morgan",
                    "role": "Head of Partnerships",
                    "email": "alex.morgan@acme.example",
                },
                {
                    "company": "Globex LLC",
                    "website": "https://globex.example",
                    "name": "Jamie Lee",
                    "role": "Business Development",
                    "email": "jamie.lee@globex.example",
                },
            ]
        }

    if '"companies"' in prompt_lower:
        return {
            "companies": [
                {"name": "Acme Partner Co", "website": "https://example.com"},
                {"name": "Globex LLC", "website": "https://globex.example"},
                {"name": "Initech", "website": "https://initech.example"},
            ]
        }

    raise ValueError("Stub LLM could not match prompt type")


def parse_json_text(text: str) -> dict:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON returned by model: {e}") from e

    if not isinstance(parsed, dict):
        raise ValueError("Model output must be a JSON object")

    return parsed
