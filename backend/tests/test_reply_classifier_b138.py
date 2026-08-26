"""B-138: reply_classifier regression — not_interested must not be swallowed by the fact that it
contains the substring "interested". Companion to the unsubscribe-vs-not_interested ordering
tests in test_can_spam_b128.py.

Also covers quote-stripping (strip_quoted_reply / classify_reply's None return): our own CAN-SPAM
"reply STOP" signature (persona_service.STEPAN_SIGNATURE_HTML) gets echoed back in most
reply-all replies, and must not be misread as the contact's own opt-out.
"""

from app.services.persona_service import STEPAN_SIGNATURE_HTML
from app.services.reply_classifier import classify_reply, strip_quoted_reply


def test_classify_reply_no_thanks_not_interested_is_not_interested():
    """Bug as reported: "No thanks, not interested" used to classify as interested."""
    assert classify_reply("No thanks, not interested")["label"] == "not_interested"


def test_classify_reply_sorry_not_interested_at_this_time_is_not_interested():
    """Bug as reported: "Sorry, not interested at this time" used to classify as interested."""
    assert classify_reply("Sorry, not interested at this time")["label"] == "not_interested"


def test_classify_reply_interested_tell_me_more_still_interested():
    """Regression guard: the fix must not break the plain positive case."""
    assert classify_reply("I'm interested, tell me more")["label"] == "interested"


def test_classify_reply_not_really_interested_is_not_interested():
    """Edge case: a word or two between "not" and "interested" must still classify as negative."""
    assert classify_reply("Thanks but not really interested")["label"] == "not_interested"


def test_classify_reply_not_particularly_interested_is_not_interested():
    assert classify_reply("Not particularly interested right now")["label"] == "not_interested"


def test_classify_reply_pass_word_boundary_does_not_false_positive_on_passionate():
    """"pass" must match as a whole word only — "passionate" must not trigger not_interested."""
    result = classify_reply("We're very passionate about this space, sounds good, let's talk")
    assert result["label"] != "not_interested"


# ------------------------------------------------------------------- strip_quoted_reply()

def test_strip_quoted_reply_cuts_at_gmail_quote_marker():
    body = (
        "Sounds great, let's talk!\n\n"
        "> On Mon, Jul 20, 2026 at 9:00 AM Stepan wrote:\n"
        "> Hi there,\n"
        "> reply \"STOP\" and I'll take you off my list."
    )
    assert strip_quoted_reply(body) == "Sounds great, let's talk!"


def test_strip_quoted_reply_cuts_at_on_wrote_marker_without_quote_prefix():
    body = (
        "Sounds great, let's talk!\n\n"
        "On Mon, Jul 20, 2026 at 9:00 AM, Stepan Pakhanov <stepan@alexstaff.agency> wrote:\n"
        "Hi there, reply \"STOP\" and I'll take you off my list."
    )
    assert strip_quoted_reply(body) == "Sounds great, let's talk!"


def test_strip_quoted_reply_cuts_at_original_message_marker():
    body = (
        "Sounds great, let's talk!\n\n"
        "-----Original Message-----\n"
        "reply \"STOP\" and I'll take you off my list."
    )
    assert strip_quoted_reply(body) == "Sounds great, let's talk!"


def test_strip_quoted_reply_cuts_at_outlook_from_sent_header_block():
    body = (
        "Sounds great, let's talk!\n\n"
        "From: Stepan Pakhanov <stepan@alexstaff.agency>\n"
        "Sent: Monday, July 20, 2026 9:00 AM\n"
        "To: contact@example.com\n"
        "Subject: Re: Hello\n\n"
        "reply \"STOP\" and I'll take you off my list."
    )
    assert strip_quoted_reply(body) == "Sounds great, let's talk!"


def test_strip_quoted_reply_cuts_our_signature_fingerprint_even_without_marker():
    """Top-posting client with no ">" and no "On ... wrote:" line at all."""
    body = "Sounds great, let's talk!\nreply \"STOP\" and I'll take you off my list."
    assert strip_quoted_reply(body) == "Sounds great, let's talk!"


def test_strip_quoted_reply_no_quote_returns_body_unchanged():
    assert strip_quoted_reply("I'm interested, tell me more") == "I'm interested, tell me more"


# ------------------------------------------------------------------- classify_reply() + quoting

def test_classify_reply_returns_none_when_body_is_entirely_quoted():
    body = "> reply \"STOP\" and I'll take you off my list."
    assert classify_reply(body) is None


def test_classify_reply_returns_none_when_body_is_only_our_signature():
    """Real production signature text (persona_service.STEPAN_SIGNATURE_HTML) — the fingerprint
    backstop must recognize our own canned wording even with no test fixture involved."""
    assert classify_reply(STEPAN_SIGNATURE_HTML) is None


def test_classify_reply_interested_with_quoted_can_spam_signature_is_not_misread_as_unsubscribe():
    """The bug this fixes: a positive reply-all echoes our own "reply STOP" signature in the
    quoted history below it — must classify by the contact's NEW text, not the quote."""
    body = (
        "This sounds great, let's talk next week!\n\n"
        "On Mon, Jul 20, 2026 at 9:00 AM Stepan Pakhanov <stepan@alexstaff.agency> wrote:\n"
        "> Hi there,\n"
        "> ...\n"
        "> If you'd rather not hear from us, just reply \"STOP\" and I'll take you off my list.\n"
    )
    assert classify_reply(body)["label"] == "interested"


def test_classify_reply_genuine_stop_in_new_text_is_still_unsubscribe():
    """Regression guard the other way: a real opt-out typed above the quote must still work."""
    body = (
        "Please stop emailing me.\n\n"
        "On Mon, Jul 20, 2026 at 9:00 AM Stepan wrote:\n"
        "> reply \"STOP\" and I'll take you off my list."
    )
    assert classify_reply(body)["label"] == "unsubscribe"
