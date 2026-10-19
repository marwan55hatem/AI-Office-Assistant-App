"""A tiny text classifier, trained by us, that tells which question was asked.

It is a "fastText-style" network written directly in PyTorch (no extra
libraries): a sentence is turned into word, word-pair and character n-gram
features, each feature is hashed to one of ``BUCKETS`` slots, the slot vectors
are averaged and two small layers turn that into one score per intent.  Character
n-grams make it tolerant to typos, and it handles Arabic as well as English.

The trained weights (about 1 MB) live next to this file in ``intent_model.pt``;
``train_intent.py`` recreates them in a few seconds.
"""

import os
import re
import unicodedata
import zlib

BUCKETS = 1 << 14          # hashed feature slots
EMBED_DIM = 32
HIDDEN = 64
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "intent_model.pt")

#: Below this probability the question is treated as "unknown".
MIN_CONFIDENCE = 0.40

_TASHKEEL = re.compile("[ً-ٰٟـ]")
_ARABIC_MAP = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا",   # alef variants
    "ى": "ي",                                           # alef maksura -> ya
    "ة": "ه",                                           # ta marbuta -> ha
})


def normalize(text):
    """Lower-case, strip accents / Arabic diacritics, unify letter variants."""
    text = unicodedata.normalize("NFKC", str(text)).lower()
    text = _TASHKEEL.sub("", text).translate(_ARABIC_MAP)
    return text


def tokenize(text):
    """Words of a normalised sentence (letters and digits, any language)."""
    return re.findall(r"\w+", normalize(text), re.UNICODE)


#: How many times a concept feature is repeated (it should outweigh single letters).
CONCEPT_WEIGHT = 3


def features(text):
    """Feature strings: words, word pairs, 3-5 character n-grams per word, and
    one feature per lexicon concept found in the sentence (``k:TEAM`` ...)."""
    from assistant.lexicon import concept_tags

    norm = normalize(text)
    words = re.findall(r"\w+", norm, re.UNICODE)
    feats = ["w:" + word for word in words]
    feats += ["k:" + tag for tag in concept_tags(norm)] * CONCEPT_WEIGHT
    feats += ["b:%s_%s" % pair for pair in zip(words, words[1:])]
    for word in words:
        padded = "<%s>" % word
        for size in (3, 4, 5):
            feats += ["c:" + padded[i:i + size] for i in range(len(padded) - size + 1)]
    return feats


def hash_features(text):
    """Stable bucket ids (``crc32`` -- Python's own ``hash`` changes every run)."""
    return [zlib.crc32(f.encode("utf-8")) % BUCKETS for f in features(text)] or [0]


def _build_network():
    import torch.nn as nn

    class Net(nn.Module):
        """The small fastText-style network: EmbeddingBag -> hidden layer -> intents."""
        def __init__(self, classes):
            super().__init__()
            self.embed = nn.EmbeddingBag(BUCKETS, EMBED_DIM, mode="mean")
            self.head = nn.Sequential(
                nn.Linear(EMBED_DIM, HIDDEN), nn.ReLU(), nn.Dropout(0.2),
                nn.Linear(HIDDEN, classes),
            )

        def forward(self, ids, offsets):
            return self.head(self.embed(ids, offsets))

    return Net


def _batch(texts, drop=0.0, rng=None):
    """Pack several sentences for ``EmbeddingBag`` (flat ids + offsets).

    ``drop`` randomly forgets that share of the features of every sentence (only
    while training): the network cannot lean on any single word or letter group,
    which makes it cope much better with wording it has never seen.
    """
    import torch

    ids, offsets = [], []
    for text in texts:
        offsets.append(len(ids))
        hashed = hash_features(text)
        if drop:
            kept = [h for h in hashed if rng.random() >= drop]
            hashed = kept or hashed[:1]
        ids.extend(hashed)
    return torch.tensor(ids, dtype=torch.long), torch.tensor(offsets, dtype=torch.long)


class IntentClassifier:
    """Load the trained network and classify a sentence."""

    def __init__(self, network, labels):
        self.network = network.eval()
        self.labels = list(labels)

    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls, path=MODEL_PATH):
        """Read ``intent_model.pt``; raises ``FileNotFoundError`` when it is missing."""
        import torch

        data = torch.load(path, map_location="cpu", weights_only=True)
        network = _build_network()(len(data["labels"]))
        network.load_state_dict({k: v.float() for k, v in data["state"].items()})
        return cls(network, data["labels"])

    def probabilities(self, text):
        """``{intent: probability}`` for one sentence."""
        import torch

        ids, offsets = _batch([text])
        with torch.no_grad():
            probs = torch.softmax(self.network(ids, offsets), dim=1)[0]
        return {label: float(p) for label, p in zip(self.labels, probs)}

    def predict(self, text, min_confidence=MIN_CONFIDENCE):
        """``(intent, confidence)``; low confidence gives ``("unknown", confidence)``."""
        if not tokenize(text):
            return "unknown", 1.0
        probs = self.probabilities(text)
        intent = max(probs, key=probs.get)
        confidence = probs[intent]
        if confidence < min_confidence:
            return "unknown", confidence
        return intent, confidence


_shared = None


def get_classifier():
    """The process-wide classifier (loaded on first use)."""
    global _shared
    if _shared is None:
        _shared = IntentClassifier.load()
    return _shared


def train(samples, labels, epochs=40, seed=7, verbose=True, feature_drop=0.25):
    """Train a new network on ``samples = [(sentence, intent), ...]``.

    Returns an :class:`IntentClassifier`.  ``labels`` fixes the class order.
    """
    import random

    import torch
    import torch.nn as nn

    torch.manual_seed(seed)
    rng = random.Random(seed)
    index = {label: i for i, label in enumerate(labels)}
    network = _build_network()(len(labels))
    optimiser = torch.optim.AdamW(network.parameters(), lr=0.01, weight_decay=1e-4)
    loss_fn = nn.CrossEntropyLoss(label_smoothing=0.02)

    data = list(samples)
    for epoch in range(epochs):
        rng.shuffle(data)
        network.train()
        total = 0.0
        for start in range(0, len(data), 64):
            chunk = data[start:start + 64]
            ids, offsets = _batch([text for text, _ in chunk], feature_drop, rng)
            target = torch.tensor([index[intent] for _, intent in chunk])
            optimiser.zero_grad()
            loss = loss_fn(network(ids, offsets), target)
            loss.backward()
            optimiser.step()
            total += float(loss) * len(chunk)
        if verbose and (epoch % 5 == 4 or epoch == epochs - 1):
            print("  epoch %2d/%d  loss %.4f" % (epoch + 1, epochs, total / len(data)))
    return IntentClassifier(network, labels)


def save(classifier, path=MODEL_PATH):
    """Write the weights (half precision) and the label order."""
    import torch

    state = {k: v.half() for k, v in classifier.network.state_dict().items()}
    torch.save({"state": state, "labels": classifier.labels}, path)
    return os.path.getsize(path)
