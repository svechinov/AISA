import json


def build_prompt(
    task: str,
    data: dict,
    rules: list[str],
    output_schema: dict | None = None,
) -> str:
    rules_block = "\n".join(f"- {rule}" for rule in rules) if rules else "- No additional rules"
    data_block = json.dumps(data, ensure_ascii=False, indent=2)

    schema_block = ""
    if output_schema:
        schema_block = (
            "\nOUTPUT JSON SCHEMA:\n"
            f"{json.dumps(output_schema, ensure_ascii=False, indent=2)}\n"
        )

    return f"""
You are executing one structured workflow step.

RULES:
{rules_block}

TASK:
{task}

INPUT DATA:
{data_block}
{schema_block}
Return only valid JSON.
Do not add markdown.
Do not add explanations.
""".strip()
