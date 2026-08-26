import json


def _render(task: str, data: dict, rules: list[str], output_schema: dict | None) -> str:
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


def build_prompt(
    task: str,
    data: dict,
    rules: list[str],
    output_schema: dict | None = None,
) -> str:
    return _render(task, data, rules, output_schema)


def build_prompt_split(
    task: str,
    data: dict,
    rules: list[str],
    output_schema: dict | None = None,
    cacheable_prefix: str | None = None,
) -> tuple[str, str]:
    """B-371: same rendered text as build_prompt(task=cacheable_prefix + task, ...), split into a
    cacheable prefix and the rest. The split point is right after `cacheable_prefix` inside the TASK
    section, so `prefix + rest` is byte-identical to what build_prompt would return today — no
    change to what the model sees, only where the Anthropic cache boundary sits."""
    if not cacheable_prefix:
        return "", build_prompt(task, data, rules, output_schema)

    full = build_prompt(cacheable_prefix + task, data, rules, output_schema)
    marker = "TASK:\n"
    split_idx = full.index(marker) + len(marker) + len(cacheable_prefix)
    return full[:split_idx], full[split_idx:]
