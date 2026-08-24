from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .domain import freeze_json


@dataclass(frozen=True, slots=True)
class Term:
    concept_id: str
    translations: Mapping[str, tuple[str, ...]]
    forbidden: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        if not self.concept_id.strip() or len(self.concept_id) > 300:
            raise ValueError("glossary concept ids must be bounded non-empty text")
        translations = _validated_languages(self.translations, "translations")
        forbidden = _validated_languages(self.forbidden, "forbidden")
        if not translations:
            raise ValueError("glossary terms require at least one translation")
        for language in set(translations) & set(forbidden):
            if set(map(str.casefold, translations[language])) & set(
                map(str.casefold, forbidden[language])
            ):
                raise ValueError("preferred and forbidden glossary forms must not overlap")
        object.__setattr__(self, "translations", freeze_json(translations))
        object.__setattr__(self, "forbidden", freeze_json(forbidden))


@dataclass(frozen=True, slots=True)
class Glossary:
    id: str
    version: str
    terms: tuple[Term, ...]

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.version.strip():
            raise ValueError("glossary id and version are required")
        concepts = [term.concept_id for term in self.terms]
        if not self.terms or len(concepts) != len(set(concepts)):
            raise ValueError("glossary concepts must be non-empty and unique")

    @classmethod
    def load(cls, path: Path) -> Glossary:
        data = json.loads(path.read_text("utf-8"))
        if not isinstance(data, dict) or set(data) != {"id", "version", "terms"}:
            raise ValueError("glossary document fields do not match schema")
        if not isinstance(data["terms"], list):
            raise ValueError("glossary terms must be an array")
        if any(
            not isinstance(item, dict) or set(item) != {"concept_id", "translations", "forbidden"}
            for item in data["terms"]
        ):
            raise ValueError("glossary term fields do not match schema")
        terms = tuple(
            Term(
                item["concept_id"],
                item["translations"],
                item["forbidden"],
            )
            for item in data["terms"]
        )
        return cls(data["id"], str(data["version"]), terms)

    def expand(
        self,
        query_tokens: tuple[str, ...],
        *,
        target_language: str,
        source_language: str | None = None,
    ) -> tuple[str, ...]:
        """Return target-language tokens for glossary concepts present in a query.

        Matching is phrase-aware and deterministic.  Callers retain the original
        query at full weight and should apply a lower weight to these expansions.
        """
        return self.expand_with_provenance(
            query_tokens,
            target_language=target_language,
            source_language=source_language,
        )[0]

    def expand_with_provenance(
        self,
        query_tokens: tuple[str, ...],
        *,
        target_language: str,
        source_language: str | None = None,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Return expansion tokens and the concept identities that authorized them."""
        from .retrieval import tokenize

        target_language = _language_key(target_language, self)
        source_language = (
            _language_key(source_language, self) if source_language else target_language
        )
        expanded: set[str] = set()
        concepts: set[str] = set()
        for term in self.terms:
            source_forms = {source_language: term.translations.get(source_language, ())}
            matched = any(
                _contains_tokens(query_tokens, tokenize(form))
                for forms in source_forms.values()
                for form in forms
            )
            if matched:
                concepts.add(term.concept_id)
                for form in term.translations.get(target_language, ()):
                    expanded.update(tokenize(form))
        return tuple(sorted(expanded - set(query_tokens))), tuple(sorted(concepts))

    def expansion_trace(
        self,
        query_tokens: tuple[str, ...],
        *,
        target_language: str,
        source_language: str | None = None,
    ) -> tuple[Mapping[str, object], ...]:
        """Disclose the exact forms and languages authorizing each expansion."""
        from .retrieval import tokenize

        target = _language_key(target_language, self)
        source = _language_key(source_language, self) if source_language else target
        records = []
        for term in self.terms:
            matched_forms = tuple(
                sorted(
                    form
                    for form in term.translations.get(source, ())
                    if _contains_tokens(query_tokens, tokenize(form))
                )
            )
            if matched_forms:
                target_forms = tuple(sorted(term.translations.get(target, ())))
                records.append(
                    freeze_json(
                        {
                            "concept_id": term.concept_id,
                            "source_language": source,
                            "matched_forms": matched_forms,
                            "target_language": target,
                            "target_forms": target_forms,
                            "expanded_tokens": tuple(
                                sorted({token for form in target_forms for token in tokenize(form)})
                            ),
                        }
                    )
                )
        return tuple(records)


def _contains_tokens(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    return any(
        haystack[index : index + len(needle)] == needle
        for index in range(len(haystack) - len(needle) + 1)
    )


def _language_key(language: str, glossary: Glossary) -> str:
    available = {key.casefold(): key for term in glossary.terms for key in term.translations}
    normalized = language.replace("_", "-").casefold()
    return available.get(normalized, available.get(normalized.split("-", 1)[0], language))


def _validated_languages(
    values: Mapping[str, tuple[str, ...]], label: str
) -> dict[str, tuple[str, ...]]:
    if not isinstance(values, Mapping):
        raise ValueError(f"glossary {label} must be a language mapping")
    result = {}
    normalized_languages = set()
    for language, forms in values.items():
        normalized = language.replace("_", "-").casefold() if isinstance(language, str) else ""
        if (
            not re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})*", normalized)
            or normalized in normalized_languages
            or not isinstance(forms, (list, tuple))
            or not forms
            or any(
                not isinstance(form, str) or not form.strip() or len(form) > 200 for form in forms
            )
            or len({form.casefold() for form in forms}) != len(forms)
        ):
            raise ValueError(f"glossary {label} contains invalid language forms")
        normalized_languages.add(normalized)
        result[language] = tuple(forms)
    return result
