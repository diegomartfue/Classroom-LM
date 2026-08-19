"""
TEST GROUP 2 — document extraction name-collision regression.

document_store.py has its OWN extract_text(filename, data) (extracts text from
an uploaded FILE) and separately needs the response helper. Before the fix, the
imported response helper was shadowed by the local function, so _response_text()
raised `TypeError: extract_text() missing 1 required positional argument: 'data'`.
"""
import inspect

import document_store
from conftest import FakeTextBlock, FakeThinkingBlock, FakeResponse


def test_module_extract_text_is_the_file_extractor():
    # The public document_store.extract_text must be the (filename, data) file
    # extractor, not the 1-arg response helper.
    params = list(inspect.signature(document_store.extract_text).parameters)
    assert params == ["filename", "data"], params


def test_response_text_uses_the_response_helper_not_the_file_extractor():
    # Regression: this call previously raised TypeError. It must now return the
    # concatenated text of the response's text blocks.
    resp = FakeResponse([FakeThinkingBlock(), FakeTextBlock("  transcribed text  ")])
    assert document_store._response_text(resp) == "transcribed text"


def test_response_helper_alias_is_distinct_from_file_extractor():
    # The alias points at response_utils.extract_text (1 arg 'response').
    assert list(inspect.signature(document_store.extract_response_text).parameters) == ["response"]
