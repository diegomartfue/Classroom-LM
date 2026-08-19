"""
response_utils.py — helpers for reading Claude Messages API responses.

Claude 4.6+ models (including claude-sonnet-5, the model this backend
uses) have adaptive thinking on by default, so ``response.content`` can
lead with a ThinkingBlock before any TextBlock. Never index
``response.content[0]`` directly to get text — filter by block type.
"""


def extract_text(response) -> str:
    """Concatenate every text block in a Messages API response.

    Skips thinking blocks and any other non-text content (tool_use,
    etc.), so it's safe regardless of what precedes the text in
    ``response.content``.
    """
    return "".join(
        block.text for block in response.content
        if getattr(block, "type", "") == "text"
    )
