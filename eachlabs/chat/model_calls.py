"""Calling the language model: reply caps per model, retries on 502-504, models that need reasoning, cut-off replies."""

from dataclasses import dataclass

from ..api_client import ApiError


BUSY = "The model is busy, try again in a moment."



@dataclass(frozen=True)
class ReplyCap:
    tokens: int  # max_tokens of every call; it also counts the model's hidden reasoning
    lines: int  # the step size the instructions ask for, so a step fits in the cap with its reasoning



# The Eachlabs chat API ends a call at 60 s, so a full-length reply must fit in about 35 s.
# Replies that hit a 5000 cap took 28-35 s (144-179 tokens/s). Anthropic models write 90-130 tokens/s, so
# their cap is 3000 (25-35 s), with shorter steps. The first matching id prefix wins; others get the default.
MAX_TOKENS = 5000
STEP_LINES = 80
REPLY_CAPS = (("anthropic/", ReplyCap(3000, 50)),)
DEFAULT_CAP = ReplyCap(MAX_TOKENS, STEP_LINES)



def reply_cap(model):
    """The ``ReplyCap`` of a model id."""
    model = (model or "").strip().lower()
    return next((cap for prefix, cap in REPLY_CAPS if model.startswith(prefix)), DEFAULT_CAP)



def step_size(text, lines):
    """``text`` with its step size ("about 80 lines") set to ``lines``."""
    return text.replace("about %d lines" % STEP_LINES, "about %d lines" % lines)



RETRY_STATUS = (502, 503, 504)  # a model call that failed with one of these is sent once more
RETRY_AFTER = 2.0  # seconds



def _looks_like_code(text):
    """True when a text reply carries a step of code, as a fenced block or as an ``import bpy`` line."""
    return "```" in text or any(line.strip().startswith(("import bpy", "from bpy")) for line in text.splitlines())



# Models whose reasoning cannot be turned off: they answer {"enabled": false} with HTTP 400 "Reasoning is
# mandatory", so asking would cost a wasted call per run.
REASONING_REQUIRED = ("anthropic/",)



def reasoning_optional(model):
    """False for a model that refuses a request for no hidden reasoning, so the request is never sent."""
    model = (model or "").strip().lower()
    return not model.startswith(REASONING_REQUIRED)



class WithoutReasoning:
    """``call(messages, tools, reasoning)`` as an ``llm(messages, tools)`` that asks for no hidden reasoning. When the
    endpoint refuses that with HTTP 400, the call is sent again without it, and so is every later call of the run.
    ``accepted=False`` never asks, for a model known to refuse."""

    def __init__(self, call, accepted=True):
        self.call = call
        self.accepted = accepted

    def __call__(self, messages, tools):
        if self.accepted:
            try:
                return self.call(messages, tools, False)
            except ApiError as exc:
                if exc.status != 400 or exc.rate_limited:
                    raise
                self.accepted = False
        return self.call(messages, tools, True)



def _cut_off(reply, cap=MAX_TOKENS):
    """True when the reply ended at the token cap ``cap``. The endpoint can report ``tool_calls`` for a call whose
    arguments the cap cut off, so a reply that used every token counts too."""
    if reply["choices"][0].get("finish_reason") == "length":
        return True
    usage = reply.get("usage")
    tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
    return isinstance(tokens, int) and tokens >= cap



def _retryable(exc):
    return isinstance(exc, ApiError) and exc.status in RETRY_STATUS



def retried(llm, cancel):
    """``llm`` sent once more after ``RETRY_AFTER`` when it fails with 502, 503 or 504, as the stage loop does; Stop
    during the wait raises ``RuntimeError``. For Code check, whose own failures already refuse the step."""
    def call(messages, tools):
        try:
            return llm(messages, tools)
        except Exception as exc:
            if not _retryable(exc):
                raise
            if cancel.wait(RETRY_AFTER):
                raise RuntimeError("The chat was stopped.") from None
            return llm(messages, tools)
    return call



def _llm_error(exc):
    """The line the bar shows when the model call failed."""
    if isinstance(exc, ApiError):
        return BUSY if exc.rate_limited else exc.message
    return "The model call failed: %s" % (str(exc) or type(exc).__name__)
