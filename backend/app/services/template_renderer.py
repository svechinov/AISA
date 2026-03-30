import re

_PATTERN = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


def render_template(content: str, variables: dict) -> str:
    def replace(match: re.Match) -> str:
        key = match.group(1)
        value = variables.get(key, "")
        return str(value) if value is not None else ""

    return _PATTERN.sub(replace, content)


def personalize_outreach_text(content: str, variables: dict) -> str:
    """Apply {{var}} then single-brace {var} placeholders."""
    s = render_template(content, variables)
    for key, value in variables.items():
        s = s.replace("{" + key + "}", str(value if value is not None else ""))
    return s


def extract_template_variables(content: str) -> list[str]:
    return sorted(set(_PATTERN.findall(content)))
