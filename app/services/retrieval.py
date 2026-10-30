"""Tiny TF-IDF keyword search used to shortlist docs/meetings before the AI picks links."""
import math
import re
from collections import Counter

_WORD = re.compile(r"[a-z][a-z0-9\-]{2,}")
_STOP = set("""the and for with that this from have has are was were will would can could should into onto about
our your their them they you its it's not but all any per via use used using also than then there here what when
who why how which been being one two new next last week team need needs make made get got let lets please
meeting meetings item items notes action""".split())


def tokenize(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP]


def rank(query: str, docs: dict[str, str], top_k: int) -> list[tuple[str, float, list[str]]]:
    """Return (doc_key, score, shared_keywords) for the top_k docs by cosine similarity of TF-IDF vectors."""
    tokenized = {key: Counter(tokenize(text)) for key, text in docs.items()}
    n = len(tokenized) or 1
    df = Counter(word for counts in tokenized.values() for word in counts)
    idf = {word: math.log((1 + n) / (1 + count)) + 1 for word, count in df.items()}

    def vector(counts: Counter) -> dict[str, float]:
        return {w: c * idf.get(w, 1.0) for w, c in counts.items()}

    q_counts = Counter(tokenize(query))
    q_vec = vector(q_counts)
    q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1.0
    results = []
    for key, counts in tokenized.items():
        d_vec = vector(counts)
        d_norm = math.sqrt(sum(v * v for v in d_vec.values())) or 1.0
        shared = set(q_vec) & set(d_vec)
        score = sum(q_vec[w] * d_vec[w] for w in shared) / (q_norm * d_norm)
        if score > 0:
            keywords = sorted(shared, key=lambda w: q_vec[w] * d_vec[w], reverse=True)[:6]
            results.append((key, score, keywords))
    results.sort(key=lambda r: r[1], reverse=True)
    return results[:top_k]
