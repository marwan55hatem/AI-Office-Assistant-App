"""The document search: chunking, BM25 ranking, "no answer" and visibility."""

import pytest

from knowledge.store import KnowledgeBase, KnowledgeError, format_passages, read_text_file, sources_of
from knowledge.text import split_document, stem, tokens

CNN = """# CNN

## Pooling layers

Max pooling keeps the largest value of each window and shrinks the feature maps.

## Building a CNN in PyTorch

Define a class that inherits from nn.Module and stack Conv2d, ReLU and MaxPool2d layers.

```python
import torch.nn as nn

class Net(nn.Module):
    pass
```
"""


@pytest.fixture
def kb(db, manager):
    base = KnowledgeBase(db)
    base.add_text("cnn.md", CNN, "everyone", manager["id"])
    base.add_text("overfitting.md", "# Overfitting\n\nThe model memorises the training data.\n\n## How to prevent overfitting\n\nUse dropout and early stopping.", "everyone", manager["id"])
    base.add_text("salary.md", "# Salary bands\n\nSenior engineers are level L5.", "managers", manager["id"])
    return base


def test_stemming_joins_word_forms():
    assert stem("pooling") == stem("pool") and stem("layers") == stem("layer")
    assert stem("overfitting") == stem("overfit") and stem("convolutional") == stem("convolution")


def test_stopwords_are_dropped_from_questions():
    assert tokens("How do I build a CNN?") == ["build", "cnn"]


def test_documents_are_cut_at_headings_and_code_stays_whole():
    chunks = split_document(1, "cnn.md", CNN)
    assert [c.heading for c in chunks] == ["Pooling layers", "Building a CNN in PyTorch"]
    code = [c for c in chunks if "class Net" in c.text]
    assert len(code) == 1 and code[0].text.count("```") == 2


def test_a_very_long_paragraph_is_cut_at_sentence_ends():
    text = "# Long\n\n" + " ".join("Sentence %d is here." % i for i in range(200))
    chunks = split_document(1, "long.md", text)
    assert len(chunks) > 1 and all(c.text.rstrip().endswith(".") for c in chunks)


@pytest.mark.parametrize("question, filename, heading", [
    ("How do I build a CNN model in PyTorch?", "cnn.md", "Building a CNN in PyTorch"),
    ("What is pooling?", "cnn.md", "Pooling layers"),
    ("How can I prevent overfitting?", "overfitting.md", "How to prevent overfitting"),
])
def test_the_right_passage_comes_first(kb, question, filename, heading):
    hit = kb.search(question, is_manager=False)[0]
    assert (hit.filename, hit.heading) == (filename, heading)


@pytest.mark.parametrize("question", ["What is the capital of Japan?", "hello", "write a poem about the sea"])
def test_a_question_the_documents_do_not_answer_returns_nothing(kb, question):
    assert kb.search(question, is_manager=True) == []


def test_how_many_questions_still_match_a_one_document_collection(db, manager):
    """'how many' is question filler, not content (regression for a one-document collection)."""
    base = KnowledgeBase(db)
    base.add_text("policy.md", "# Expenses\n\nTravel claims within 14 days.", "everyone", manager["id"])
    assert base.search("How many days for travel claims?", is_manager=False)[0].filename == "policy.md"


def test_manager_only_documents_are_found_by_managers_only(kb):
    question = "What is the salary band of senior engineers?"
    assert [h.filename for h in kb.search(question, is_manager=True)] == ["salary.md"]
    assert kb.search(question, is_manager=False) == []


def test_changing_visibility_takes_effect_at_once(kb, db):
    doc = next(d for d in kb.documents(True) if d["filename"] == "salary.md")
    kb.set_visibility(doc["id"], "everyone")
    assert kb.search("salary band senior engineers", is_manager=False)
    kb.set_visibility(doc["id"], "managers")
    assert kb.search("salary band senior engineers", is_manager=False) == []


def test_the_same_file_name_replaces_the_document(kb, manager):
    _id, created = kb.add_text("CNN.MD", "# New\n\nOnly about zebras.", "everyone", manager["id"])
    assert not created
    assert kb.search("zebras", False) and kb.search("pooling feature maps", False) == []


def test_removing_a_document_removes_it_from_search(kb):
    doc = next(d for d in kb.documents(True) if d["filename"] == "overfitting.md")
    assert kb.remove(doc["id"])
    assert kb.search("prevent overfitting", True) == []
    assert not kb.remove(doc["id"])


def test_quoted_reply_names_the_sources(kb):
    hits = kb.search("convolution pooling feature maps", False)
    assert sources_of(hits + hits) == ["cnn.md"]
    assert format_passages(hits).endswith("Sources: cnn.md")


@pytest.mark.parametrize("name, data, word", [
    ("slides.pdf", b"%PDF", "only .txt and .md"),
    ("empty.txt", b"  \n", "empty"),
    ("binary.txt", b"abc\x00def", "not a text file"),
])
def test_bad_files_are_refused_with_a_reason(tmp_path, name, data, word):
    path = tmp_path / name
    path.write_bytes(data)
    with pytest.raises(KnowledgeError, match=word):
        read_text_file(str(path))


def test_files_in_common_encodings_are_read(tmp_path):
    bom = tmp_path / "a.md"
    bom.write_bytes("﻿# عنوان\r\nنص".encode("utf-8"))
    assert read_text_file(str(bom))[1] == "# عنوان\nنص"
    windows_arabic = tmp_path / "b.txt"
    windows_arabic.write_bytes("مرحبا".encode("cp1256"))
    assert read_text_file(str(windows_arabic))[1] == "مرحبا"


def test_arabic_questions_find_arabic_notes(db, manager):
    base = KnowledgeBase(db)
    base.add_text("ar.md", "# الشبكات العصبية\n\nالشبكة العصبية نموذج حسابي يتعلم من البيانات.", "everyone", manager["id"])
    assert base.search("ما هي الشبكة العصبية", False)[0].filename == "ar.md"
