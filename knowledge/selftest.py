"""Self-test of the knowledge base:  python -m knowledge.selftest

Uses a throw-away database.  Checks chunking, BM25 search, that questions the
documents do not answer return nothing, and that manager-only documents can never
be found by an employee.  No Qt, no model.
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_manager import DatabaseManager  # noqa: E402
from knowledge.store import KnowledgeBase, KnowledgeError, format_passages, read_text_file, sources_of  # noqa: E402
from knowledge.text import split_document, stem, tokens  # noqa: E402

RESULTS = []


def check(label, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + label + ((" | " + str(detail)[:300].replace("\n", " / ")) if not ok and detail else ""))


CNN = """# Convolutional neural networks

A convolutional neural network (CNN) is a neural network designed for images. It learns filters that slide
over the picture and detect edges, textures and shapes.

## Convolution layers

A convolution layer applies a small filter (for example 3x3) to every position of the input and produces a
feature map. Many filters produce many feature maps. The filter weights are learned during training.

## Pooling layers

Pooling reduces the size of the feature maps. Max pooling keeps the largest value in each window, which makes
the network less sensitive to small shifts of the object and cuts the amount of computation.

## Building a CNN in PyTorch

To build a CNN in PyTorch, define a class that inherits from nn.Module, stack Conv2d, ReLU and MaxPool2d layers,
flatten the result and finish with a Linear layer.

```python
import torch.nn as nn

class SmallCNN(nn.Module):

    def __init__(self):
        super().__init__()
        self.features = nn.Sequential(nn.Conv2d(1, 16, 3), nn.ReLU(), nn.MaxPool2d(2))
        self.classifier = nn.Linear(16 * 13 * 13, 10)

    def forward(self, x):
        return self.classifier(self.features(x).flatten(1))
```

Train it with a loss such as CrossEntropyLoss and an optimizer such as Adam.
"""

OVERFIT = """# Overfitting and regularization

Overfitting happens when a model memorises the training data instead of learning the pattern, so it does well on
the training set but badly on new data.

## How to prevent overfitting

Use more training data, data augmentation, dropout, weight decay, early stopping and a smaller model. Always watch
the validation loss: when it rises while the training loss keeps falling, the model is overfitting.
"""

RAG = """# Retrieval-augmented generation

RAG gives a language model documents to read before it answers. The documents are cut into passages, the passages
that match the question are retrieved, and they are placed in the prompt so the answer is grounded in real text.
"""

ARABIC = """# الشبكات العصبية

الشبكة العصبية هي نموذج حسابي يتعلم من البيانات. التعلم العميق يستخدم شبكات عصبية بطبقات كثيرة.
"""

POLICY = """# Expense policy

Employees can claim travel expenses within 14 days. Receipts are required for every claim above 20 dollars.
"""

SALARY = """# Confidential salary bands

The salary band for a senior engineer is level L5 with a bonus multiplier of 1.4. This document is for managers only.
"""


def main():
    # ---------------- text helpers ----------------
    check("stemming joins word forms", len({stem(w) for w in ("overfitting", "overfit", "overfits")}) == 1
          and stem("layers") == stem("layer") and stem("pooling") == stem("pool") and stem("convolutional") == stem("convolution"),
          [stem(w) for w in ("overfitting", "overfit", "layers", "pooling")])
    check("stopwords are dropped", tokens("How do I build a CNN?") == ["build", "cnn"], tokens("How do I build a CNN?"))
    chunks = split_document(1, "cnn.md", CNN)
    check("a document is cut at its headings", [c.heading for c in chunks][:4] == ["Convolutional neural networks", "Convolution layers", "Pooling layers", "Building a CNN in PyTorch"], [c.heading for c in chunks])
    code = [c for c in chunks if "class SmallCNN" in c.text]
    check("a code block stays whole in one passage", len(code) == 1 and "def forward" in code[0].text and code[0].text.count("```") == 2)
    long_text = "# Long\n\n" + " ".join("Sentence number %d is here." % i for i in range(200))
    parts = split_document(1, "long.md", long_text)
    check("a very long paragraph is cut at sentence ends", len(parts) > 1 and all(len(p.text.split()) < 260 for p in parts) and all(p.text.rstrip().endswith(".") for p in parts), [len(p.text.split()) for p in parts])
    check("plain .txt without headings is cut into passages", len(split_document(1, "a.txt", "\n\n".join("Paragraph %d " % i + "word " * 70 for i in range(6)))) >= 3)

    with tempfile.TemporaryDirectory() as folder:
        db = DatabaseManager(os.path.join(folder, "k.db"))
        manager = db.get_user("manager", "1234", "manager")["id"]
        kb = KnowledgeBase(db)
        for name, text, vis in (("cnn_basics.md", CNN, "everyone"), ("overfitting.md", OVERFIT, "everyone"), ("rag.md", RAG, "everyone"),
                                ("arabic_notes.md", ARABIC, "everyone"), ("expense_policy.txt", POLICY, "everyone"),
                                ("salary_bands.md", SALARY, "managers")):
            kb.add_text(name, text, vis, manager)

        def top(question, mgr=False):
            hits = kb.search(question, mgr)
            return (hits[0].filename, hits[0].heading) if hits else None

        # ---------------- finds the right file ----------------
        check("CNN how-to -> cnn_basics.md, the PyTorch section", top("How do I build a CNN model in PyTorch?") == ("cnn_basics.md", "Building a CNN in PyTorch"), top("How do I build a CNN model in PyTorch?"))
        check("'what is pooling' -> the pooling section", top("What is pooling?") == ("cnn_basics.md", "Pooling layers"), top("What is pooling?"))
        check("'prevent overfitting' -> overfitting.md", top("How can I prevent overfitting?") == ("overfitting.md", "How to prevent overfitting"), top("How can I prevent overfitting?"))
        check("'what is overfitting' -> overfitting.md", top("what is overfitting")[0] == "overfitting.md")
        check("'what is RAG' -> rag.md", top("What is RAG?")[0] == "rag.md")
        check("'give a language model documents' -> rag.md", top("how do you give a language model documents to read")[0] == "rag.md")
        check("Arabic question -> the Arabic note", top("ما هي الشبكة العصبية")[0] == "arabic_notes.md", top("ما هي الشبكة العصبية"))
        check("a policy question -> the policy file", top("how many days to claim travel expenses")[0] == "expense_policy.txt")
        hits = kb.search("convolution filters feature maps pooling", False, k=3)
        check("several passages come back, best first, from the right file", len(hits) >= 2 and all(h.filename == "cnn_basics.md" for h in hits) and hits[0].score >= hits[-1].score)
        check("sources_of lists each file once", sources_of(hits + hits) == ["cnn_basics.md"])
        check("quoted reply names the file and ends with Sources", "From cnn_basics.md" in format_passages(hits) and format_passages(hits).endswith("Sources: cnn_basics.md"))

        # ---------------- says nothing when the documents do not answer ----------------
        for q in ("What is the capital of Japan?", "who won the world cup", "write a poem about the sea", "hello", "what is a transformer in electricity"):
            check("no passage for a question the documents do not answer: %s" % q, kb.search(q, True) == [], kb.search(q, True)[:1])

        # ---------------- privacy ----------------
        q = "What is the salary band for a senior engineer?"
        check("manager finds the manager-only document", top(q, True) == ("salary_bands.md", "Confidential salary bands"), top(q, True))
        check("employee gets nothing for it", kb.search(q, False) == [])
        employee_text = " ".join(h.text for qq in (q, "bonus multiplier L5", "confidential salary bands", "managers only") for h in kb.search(qq, False))
        check("no word of the manager-only document ever reaches an employee", "L5" not in employee_text and "multiplier" not in employee_text.lower())
        check("employee's document list hides it", "salary_bands.md" not in [d["filename"] for d in kb.documents(False)] and "salary_bands.md" in [d["filename"] for d in kb.documents(True)])
        doc = next(d for d in kb.documents(True) if d["filename"] == "salary_bands.md")
        db.set_knowledge_visibility(doc["id"], "everyone")
        check("making it public makes it findable (index rebuilt)", top(q, False) is not None and top(q, False)[0] == "salary_bands.md")
        db.set_knowledge_visibility(doc["id"], "managers")
        check("making it private again hides it at once", kb.search(q, False) == [])

        # ---------------- replace / remove ----------------
        doc_id, created = kb.add_text("CNN_Basics.MD", "# Replaced\n\nThis note now only talks about zebras and stripes.", "everyone", manager)
        check("same file name (any case) replaces the document", not created and len([d for d in kb.documents(True) if d["filename"].lower() == "cnn_basics.md"]) == 1)
        check("search sees the new text, not the old", top("zebras stripes")[0] == "CNN_Basics.MD" or top("zebras stripes")[0] == "cnn_basics.md")
        check("the old text is gone", kb.search("pooling feature maps", False) == [])
        check("remove deletes it", kb.remove(doc_id) and not any("zebra" in d.get("content", "") for d in kb.documents(True)) and kb.search("zebras stripes", True) == [])
        check("removing an unknown id is harmless", kb.remove(99999) is False)

        # ---------------- files ----------------
        def write(name, data):
            path = os.path.join(folder, name)
            with open(path, "wb") as handle:
                handle.write(data)
            return path

        def rejects(name, data, word):
            try:
                read_text_file(write(name, data))
                return False
            except KnowledgeError as error:
                return word in str(error)

        check("a .pdf is refused with a clear message", rejects("x.pdf", b"%PDF", "only .txt and .md"))
        check("an empty file is refused", rejects("e.txt", b"   \n", "empty"))
        check("a binary file is refused", rejects("b.txt", b"abc\x00\x01", "not a text file"))
        check("a file over 2 MB is refused", rejects("big.txt", b"a" * (2 * 1024 * 1024 + 1), "too large"))
        name, text = read_text_file(write("u.md", "﻿# Title\r\nمرحبا بالعالم".encode("utf-8")))
        check("UTF-8 with BOM and CRLF is read cleanly", text == "# Title\nمرحبا بالعالم", repr(text))
        name, text = read_text_file(write("w.txt", "مرحبا".encode("cp1256")))
        check("an old Windows Arabic file (cp1256) is read", text == "مرحبا", repr(text))
        doc_id, created = kb.add_file(write("from_disk.md", b"# Disk note\n\nGradient descent updates the weights step by step."), "everyone", manager)
        check("add_file stores the document", created and top("what is gradient descent")[0] == "from_disk.md")

        # ---------------- speed ----------------
        for i in range(300):
            kb.add_text("bulk_%d.md" % i, "\n\n".join("# Section %d\n\n%s" % (j, ("word%d token%d filler text about topic%d " % (i, j, i * j)) * 25) for j in range(8)), "everyone", manager)
        start = time.perf_counter(); kb.search("warm up", True); build = time.perf_counter() - start
        start = time.perf_counter()
        for _ in range(20):
            kb.search("topic12 token3 filler", True)
        per = (time.perf_counter() - start) / 20
        check("index of %d passages builds in %.2f s, a search takes %.1f ms" % (len(kb._index(True).chunks), build, per * 1000), per < 0.05 and build < 10)
        check("no Qt was imported", not any(m.startswith("PyQt5") for m in sys.modules))
        db.close()

    print("\nSUMMARY %d / %d passed" % (sum(RESULTS), len(RESULTS)))
    return all(RESULTS)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
