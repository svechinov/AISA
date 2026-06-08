import json
import logging
from typing import Any

from app.services.tavily_osint import get_tavily_client, discover_contact_email
from app.services.llm_gateway import complete_prompt_json_object

logger = logging.getLogger(__name__)

def generate_company_leads(company_name: str, website: str, target_roles: str, run_setup=None) -> list[dict[str, Any]]:
    """
    Use Tavily and LLM to find Decision Makers (LPR) for a given company.
    """
    client = get_tavily_client()
    if not client:
        raise ValueError("Tavily API key is not configured. OSINT skipped.")

    site_ctx = f" (website: {website})" if website and website.strip() else ""
    roles_ctx = target_roles if target_roles and target_roles.strip() else "CEO, Founder, HR Director, Sales Head"

    query = (
        f"Find names and linkedin profiles of key decision makers at {company_name}{site_ctx}. "
        f"Target roles: {roles_ctx}. "
        "Also search in Russian: Найти руководителей, имена и фамилии директоров."
    )

    try:
        response = client.search(
            query=query,
            search_depth="advanced",
            include_answer=True,
            max_results=5
        )
    except Exception as e:
        logger.error(f"Tavily search failed for {company_name}: {e}")
        raise ValueError(f"Tavily search failed: {str(e)}")

    context_text = f"Tavily Answer: {response.get('answer', '')}\n\nSources:\n"
    for res in response.get("results", []):
        context_text += f"- {res.get('title', '')} ({res.get('url', '')}): {res.get('content', '')}\n"

    if run_setup and getattr(run_setup, "deep_osint_prompt", None) and run_setup.deep_osint_prompt.strip():
        user_prompt = run_setup.deep_osint_prompt.strip()
        prompt = f"{user_prompt}\n\nCompany: {company_name}{site_ctx}\nRoles: {roles_ctx}\n\nReturn a JSON object matching this schema:\n" + \
        "{\n  \"contacts\": [\n    {\n      \"name\": \"Full Name\",\n      \"role\": \"Exact or inferred role\",\n      \"linkedin\": \"URL if available, or empty string\"\n    }\n  ]\n}\n" + \
        "If no contacts are found, return {\"contacts\": []}.\nOnly include real people found in the text. Ensure names are extracted correctly.\n\n" + \
        f"Context:\n{context_text}"
    else:
        prompt = f"""
    Based on the following OSINT search results for the company '{company_name}'{site_ctx}, extract the list of decision makers (LPR).
    We are looking for roles such as: {roles_ctx}.

    Return a JSON object matching this schema:
    {{
        "contacts": [
            {{
                "name": "Full Name",
                "role": "Exact or inferred role",
                "linkedin": "URL if available, or empty string"
            }}
        ]
    }}

    If no contacts are found, return {{"contacts": []}}.
    Only include real people found in the text. Ensure names are extracted correctly.

    Context:
    {context_text}
    """

    try:
        full_prompt = "You are an expert OSINT data extractor. Extract personnel data accurately into JSON.\n\n" + prompt
        llm_result = complete_prompt_json_object(prompt=full_prompt)
    except Exception as e:
        logger.error(f"LLM JSON extraction failed: {e}")
        raise ValueError(f"Failed to parse OSINT results via LLM: {str(e)}")

    contacts = llm_result.get("contacts", [])
    
    # Optional: discover email
    for c in contacts:
        name = c.get("name", "").strip()
        if name:
            email = discover_contact_email(company_name, website, name)
            c["email"] = email or ""

    return contacts
