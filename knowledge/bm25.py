"""BM25 ranking over passages (Okapi BM25, written out in a few lines -- no library)."""

import math
from collections import Counter, namedtuple
from typing import List

from knowledge.text import tokens

K1 = 1.5
B = 0.75
#: Floor of a term's weight, so that in a very small collection a word that every passage
#: contains still counts as much as it deserves when the question is checked for coverage.
MIN_IDF = 0.5

#: A passage must cover at least this share (by importance) of the question's words.
MIN_COVERAGE = 0.5
#: ...and score at least this share of the best passage, to be returned next to it.
MIN_RELATIVE_SCORE = 0.4

Hit = namedtuple("Hit", "doc_id filename heading text score coverage")


class BM25Index:
    """Index of :class:`knowledge.text.Chunk` objects.  Build once, search many times."""

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self._terms = []            # per chunk: Counter of terms
        self._lengths = []
        df = Counter()
        for chunk in self.chunks:
            # the heading and the file name help to find a passage, so they count as text too
            counts = Counter(tokens(chunk.heading + " " + chunk.filename.rsplit(".", 1)[0] + " " + chunk.text))
            self._terms.append(counts)
            self._lengths.append(sum(counts.values()))
            df.update(counts.keys())
        self._df = df
        self._n = len(self.chunks)
        self._avg = (sum(self._lengths) / self._n) if self._n else 0.0

    def idf(self, term: str) -> float:
        """How rare a term is.  A term in no passage at all is the rarest of all."""
        n = self._df.get(term, 0)
        return max(MIN_IDF, math.log(1.0 + (self._n - n + 0.5) / (n + 0.5)))

    def search(self, query: str, k: int = 3) -> List[Hit]:
        """The best ``k`` passages for ``query`` (a question in plain words), best first.

        Passages that cover too little of what was asked are left out, so a question the
        documents do not answer returns ``[]`` instead of a random best-of-bad passage.
        """
        terms = list(dict.fromkeys(tokens(query)))
        if not terms or not self._n:
            return []
        total_weight = sum(self.idf(t) for t in terms)
        scored = []
        for index, counts in enumerate(self._terms):
            score, matched_weight = 0.0, 0.0
            norm = K1 * (1 - B + B * self._lengths[index] / (self._avg or 1.0))
            for term in terms:
                tf = counts.get(term, 0)
                if tf:
                    idf = self.idf(term)
                    score += idf * tf * (K1 + 1) / (tf + norm)
                    matched_weight += idf
            coverage = matched_weight / total_weight if total_weight else 0.0
            if score > 0 and coverage >= MIN_COVERAGE:
                scored.append((score, coverage, index))
        scored.sort(key=lambda row: -row[0])
        if not scored:
            return []
        best = scored[0][0]
        hits = []
        for score, coverage, index in scored[:k]:
            if score >= best * MIN_RELATIVE_SCORE:
                chunk = self.chunks[index]
                hits.append(Hit(chunk.doc_id, chunk.filename, chunk.heading, chunk.text, round(score, 3), round(coverage, 2)))
        return hits
