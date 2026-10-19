"""The safe Markdown subset used to show model replies."""

import pytest

from ui import markdown


def test_text_and_code_are_separated_in_order():
    parts = markdown.split_segments("Intro.\n\n```python\nprint(1)\n```\n\nAfter.")
    assert [p.kind for p in parts] == ["text", "code", "text"]
    assert parts[1].lang == "python" and parts[1].text == "print(1)" and parts[1].closed


def test_an_unfinished_fence_is_open_code_while_streaming():
    parts = markdown.split_segments("Start\n```python\nimport torch\nclass A:")
    assert parts[-1].kind == "code" and not parts[-1].closed and parts[-1].text == "import torch\nclass A:"


def test_plain_text_is_a_single_part_and_empty_text_none():
    assert len(markdown.split_segments("just words")) == 1
    assert markdown.split_segments("") == []


def test_two_code_blocks():
    assert [p.kind for p in markdown.split_segments("```\na\n```\nmid\n```js\nb\n```")] == ["code", "text", "code"]


def test_bold_headings_bullets_and_inline_code():
    html = markdown.to_html("# Title\n**Bold** and `code`\n- item\n  - nested\nSources: a.md")
    assert "<b>Title</b>" in html and "<b>Bold</b>" in html and "Consolas" in html
    assert "•&nbsp;item" in html and "&nbsp;&nbsp;•&nbsp;nested" in html
    assert "<i>Sources: a.md</i>" in html


@pytest.mark.parametrize("attack", [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "<a href='http://evil'>click</a>",
    "</span><b>x</b>",
])
def test_html_in_a_reply_is_shown_as_text_never_interpreted(attack):
    html = markdown.to_html(attack)
    assert "<script" not in html and "<img" not in html and "<a " not in html and "&lt;" in html


def test_bold_markers_inside_inline_code_are_left_alone():
    html = markdown.to_html("use `a ** b` here")
    assert "**" in html and "<b>" not in html
