def classify_reply(body: str) -> dict:
    text = (body or "").lower()

    if any(x in text for x in ["interested", "let's talk", "sounds good", "tell me more"]):
        return {
            "label": "interested",
            "confidence": "high",
            "reason": "positive intent keywords",
        }

    if any(x in text for x in ["not interested", "no thanks", "pass"]):
        return {
            "label": "not_interested",
            "confidence": "high",
            "reason": "negative intent keywords",
        }

    if any(x in text for x in ["later", "not now", "follow up"]):
        return {
            "label": "ask_later",
            "confidence": "medium",
            "reason": "delay intent",
        }

    if any(x in text for x in ["more info", "details", "send more"]):
        return {
            "label": "need_more_info",
            "confidence": "medium",
            "reason": "request for more info",
        }

    return {
        "label": "unclear",
        "confidence": "low",
        "reason": "no clear signal",
    }
