"""Provider-neutral retrieval with a deterministic BM25 baseline and evaluation."""

from __future__ import annotations

import math
import re
from collections import Counter, OrderedDict
from dataclasses import dataclass
from threading import RLock
from typing import Protocol

from .domain import CourseRelease
from .glossary import Glossary
from .safety_types import RetrievedEvidence


def tokenize(value: str) -> tuple[str, ...]:
    """Return deterministic Unicode words, code tokens, and CJK bigrams."""
    normalized = value.casefold()
    words = re.findall(r"c\+\+|c#|[\w]+(?:[.+#-][\w]+)*", normalized, re.UNICODE)
    cjk_runs = re.findall(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+", normalized)
    bigrams = [run[index : index + 2] for run in cjk_runs for index in range(len(run) - 1)]
    return tuple(words + bigrams)


class Retriever(Protocol):
    def retrieve(
        self,
        course: CourseRelease,
        query: str,
        *,
        limit: int = 4,
        activity_id: str | None = None,
    ) -> tuple[RetrievedEvidence, ...]: ...


class BM25Retriever:
    """Small deterministic BM25 implementation with concept/activity boosts."""

    def __init__(
        self,
        *,
        k1: float = 1.2,
        b: float = 0.75,
        cache_size: int = 8,
        glossary: Glossary | None = None,
        query_language: str | None = None,
        expansion_weight: float = 0.35,
    ):
        if k1 <= 0 or not 0 <= b <= 1 or cache_size < 1 or not 0 < expansion_weight < 1:
            raise ValueError("BM25 requires positive k1/cache size and b between zero and one")
        self.k1, self.b = k1, b
        self.cache_size = cache_size
        self.glossary = glossary
        self.query_language = query_language
        self.expansion_weight = expansion_weight
        self._indexes: OrderedDict[str, BM25Index] = OrderedDict()
        self._lock = RLock()

    def index(self, course: CourseRelease) -> BM25Index:
        with self._lock:
            cached = self._indexes.pop(course.hash, None)
            if cached is None:
                cached = BM25Index(course, k1=self.k1, b=self.b)
            self._indexes[course.hash] = cached
            while len(self._indexes) > self.cache_size:
                self._indexes.popitem(last=False)
            return cached

    def retrieve(
        self,
        course: CourseRelease,
        query: str,
        *,
        limit: int = 4,
        activity_id: str | None = None,
    ) -> tuple[RetrievedEvidence, ...]:
        if limit < 1 or limit > 100:
            raise ValueError("retrieval limit must be between 1 and 100")
        terms = tokenize(query)
        expanded = (
            self.glossary.expand(
                terms,
                target_language=course.language,
                source_language=self.query_language,
            )
            if self.glossary
            else ()
        )
        weights = dict.fromkeys(terms, 1.0)
        weights.update({term: self.expansion_weight for term in expanded if term not in weights})
        return self.index(course).retrieve(
            query,
            limit=limit,
            activity_id=activity_id,
            term_weights=weights,
        )

    def query_plan(self, course: CourseRelease, query: str) -> dict[str, object]:
        """Explain deterministic glossary expansion without exposing course or learner secrets."""
        original = tokenize(query)
        expanded: tuple[str, ...] = ()
        concepts: tuple[str, ...] = ()
        if self.glossary:
            expanded, concepts = self.glossary.expand_with_provenance(
                original,
                target_language=course.language,
                source_language=self.query_language,
            )
        trace = (
            self.glossary.expansion_trace(
                original,
                target_language=course.language,
                source_language=self.query_language,
            )
            if self.glossary
            else ()
        )
        return {
            "original_terms": original,
            "expanded_terms": expanded,
            "glossary_concept_ids": concepts,
            "glossary_matches": trace,
            "target_language": course.language,
            "source_language": self.query_language,
            "original_weight": 1.0,
            "expansion_weight": self.expansion_weight,
            "algorithm": "bm25-glossary-expansion-v1",
        }


class BM25Index:
    """Immutable precomputed index suitable for repeated retrieval over one release."""

    def __init__(self, course: CourseRelease, *, k1: float = 1.2, b: float = 0.75):
        if k1 <= 0 or not 0 <= b <= 1:
            raise ValueError("BM25 requires positive k1 and b between zero and one")
        self.course, self.k1, self.b = course, k1, b
        self.documents = tuple(
            tokenize(
                " ".join((block.title, block.text, *block.concepts, *block.learning_objectives))
            )
            for block in course.blocks
        )
        self.frequencies = tuple(Counter(document) for document in self.documents)
        self.average_length = sum(map(len, self.documents)) / max(1, len(self.documents))
        vocabulary = set().union(*(set(document) for document in self.documents))
        self.document_frequency = {
            term: sum(term in document for document in self.documents) for term in vocabulary
        }

    def retrieve(
        self,
        query: str,
        *,
        limit: int = 4,
        activity_id: str | None = None,
        term_weights: dict[str, float] | None = None,
    ) -> tuple[RetrievedEvidence, ...]:
        if limit < 1 or limit > 100:
            raise ValueError("retrieval limit must be between 1 and 100")
        terms = tokenize(query)
        if not terms:
            return ()
        weights = term_weights or dict.fromkeys(terms, 1.0)
        scored: list[tuple[float, int]] = []
        for index, (block, document, frequencies) in enumerate(
            zip(self.course.blocks, self.documents, self.frequencies, strict=True)
        ):
            score = 0.0
            for term, weight in weights.items():
                frequency = frequencies[term]
                if not frequency:
                    continue
                frequency_in_documents = self.document_frequency[term]
                inverse_frequency = math.log(
                    1
                    + (len(self.documents) - frequency_in_documents + 0.5)
                    / (frequency_in_documents + 0.5)
                )
                denominator = frequency + self.k1 * (
                    1 - self.b + self.b * len(document) / max(1.0, self.average_length)
                )
                score += weight * inverse_frequency * frequency * (self.k1 + 1) / denominator
            concept_terms = set(tokenize(" ".join(block.concepts)))
            score += 0.75 * len(set(terms) & concept_terms)
            if activity_id and (
                block.id == activity_id
                or block.parent_id == activity_id
                or block.locator.path == activity_id
            ):
                score += 1.0
            if score > 0:
                scored.append((score, index))
        scored.sort(key=lambda item: (-item[0], self.course.blocks[item[1]].order))
        return tuple(
            RetrievedEvidence(block.id, block.hash, block.text, round(score, 8))
            for score, index in scored[:limit]
            for block in (self.course.blocks[index],)
        )


@dataclass(frozen=True, slots=True)
class RetrievalFixture:
    query: str
    expected_block_ids: frozenset[str]
    activity_id: str | None = None


@dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    fixture_count: int
    recall_at_k: float
    precision_at_k: float
    hit_rate_at_k: float
    mean_reciprocal_rank: float
    ndcg_at_k: float


def evaluate_retriever(
    retriever: Retriever,
    course: CourseRelease,
    fixtures: tuple[RetrievalFixture, ...],
    *,
    limit: int = 4,
) -> RetrievalMetrics:
    if not fixtures or any(not fixture.expected_block_ids for fixture in fixtures):
        raise ValueError("retrieval evaluation requires fixtures with expected block IDs")
    known = {block.id for block in course.blocks}
    if any(not fixture.expected_block_ids <= known for fixture in fixtures):
        raise ValueError("retrieval fixture references an unknown block")
    recalls: list[float] = []
    precisions: list[float] = []
    hits: list[float] = []
    reciprocal_ranks: list[float] = []
    normalized_gains: list[float] = []
    for fixture in fixtures:
        results = retriever.retrieve(
            course, fixture.query, limit=limit, activity_id=fixture.activity_id
        )
        ids = [result.block_id for result in results]
        relevant = set(ids) & fixture.expected_block_ids
        recalls.append(len(relevant) / len(fixture.expected_block_ids))
        precisions.append(len(relevant) / limit)
        hits.append(float(bool(relevant)))
        rank = next(
            (
                index
                for index, block_id in enumerate(ids, start=1)
                if block_id in fixture.expected_block_ids
            ),
            None,
        )
        reciprocal_ranks.append(1 / rank if rank else 0.0)
        gain = sum(
            1 / math.log2(index + 1)
            for index, block_id in enumerate(ids, start=1)
            if block_id in fixture.expected_block_ids
        )
        ideal = sum(
            1 / math.log2(index + 1)
            for index in range(1, min(limit, len(fixture.expected_block_ids)) + 1)
        )
        normalized_gains.append(gain / ideal)
    return RetrievalMetrics(
        len(fixtures),
        sum(recalls) / len(recalls),
        sum(precisions) / len(precisions),
        sum(hits) / len(hits),
        sum(reciprocal_ranks) / len(reciprocal_ranks),
        sum(normalized_gains) / len(normalized_gains),
    )
