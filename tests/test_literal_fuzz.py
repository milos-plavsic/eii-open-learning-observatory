import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from eii.babelbridge import _CODE, _LINK, BabelBridge
from eii.domain import ContentBlock, CourseRelease, SourceLocator, UnitKind
from eii.literal_patterns import NUMBER_PATTERN

WORDS = {
    "en": ("apples", "dogs", "and", "on"),
    "sr": ("jabuka", "psa", "i", "na"),
    "es": ("manzanas", "perros", "y", "en"),
    "pt": ("maçãs", "cães", "e", "em"),
    "ca": ("pomes", "gossos", "i", "a"),
    "hr": ("jabuka", "pasa", "i", "na"),
}
KNOWN_UNITS = ("%", "kg", "km", "ms", "MHz", "MiB", "°C", "Mbps")
PUNCTUATION = ("", ".", ",", ":", ";", "!", "?", ")")


def release(language: str, text: str) -> CourseRelease:
    locator = SourceLocator("test", "repo", f"{language}.md", "count", None)
    block = ContentBlock("count", UnitKind.SECTION, "Count", text, 0, locator, concepts=("count",))
    return CourseRelease(
        f"course:{language}:1",
        "course",
        language,
        "1",
        "Count",
        (block,),
        locator,
        canonical_course_id="course",
    )


@st.composite
def translated_number_prose(draw):
    number = draw(
        st.one_of(
            st.integers(min_value=-10000, max_value=10000).map(str),
            st.tuples(
                st.integers(min_value=0, max_value=999),
                st.sampled_from((".", ",")),
                st.integers(min_value=0, max_value=99),
            ).map(lambda value: f"{value[0]}{value[1]}{value[2]:02d}"),
        )
    )
    left_language, right_language = draw(
        st.sampled_from(tuple((a, b) for a in WORDS for b in WORDS if a < b))
    )
    left_word = draw(st.sampled_from(WORDS[left_language]))
    right_word = draw(st.sampled_from(WORDS[right_language]))
    spacing = draw(st.sampled_from(("", " ", "  ", "\t", "\u00a0", "\u202f")))
    punctuation = draw(st.sampled_from(PUNCTUATION))
    return (
        left_language,
        right_language,
        f"Value ({number}{spacing}{left_word}{punctuation}) remains.",
        f"Value ({number}{spacing}{right_word}{punctuation}) remains.",
    )


class LiteralDetectorFuzzTests(unittest.TestCase):
    @settings(max_examples=250, deadline=None)
    @given(translated_number_prose())
    def test_translated_short_words_never_become_units(self, example):
        left_language, right_language, left, right = example
        result = BabelBridge().analyze(
            (release(left_language, left), release(right_language, right))
        )
        self.assertNotIn(
            "translation.number_or_unit_drift", {item.finding_type for item in result.findings}
        )

    @settings(max_examples=300, deadline=None)
    @given(
        st.integers(min_value=-10000, max_value=10000),
        st.text(
            alphabet=st.characters(whitelist_categories=("Ll", "Lu")),
            min_size=1,
            max_size=16,
        ).filter(lambda word: NUMBER_PATTERN.fullmatch(f"0{word}") is None),
        st.sampled_from(("", " ", "\t", "\u00a0", "\u202f")),
    )
    def test_arbitrary_alphabetic_suffix_is_never_consumed_as_a_unit(self, number, word, space):
        match = NUMBER_PATTERN.search(f"{number}{space}{word}")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertNotIn(word, match.group())

    @settings(max_examples=200, deadline=None)
    @given(
        st.integers(min_value=0, max_value=10000),
        st.sampled_from(KNOWN_UNITS),
        st.sampled_from(("", " ", "\t", "\u00a0")),
    )
    def test_allowlisted_units_are_preserved(self, number, unit, space):
        match = NUMBER_PATTERN.fullmatch(f"{number}{space}{unit}")
        self.assertIsNotNone(match)

    @settings(max_examples=200, deadline=None)
    @given(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789_+-*/() ", min_size=1, max_size=40
        ).filter(lambda value: "`" not in value)
    )
    def test_inline_code_detector_preserves_exact_bounded_payload(self, payload):
        matches = _CODE.findall(f"Translated prose `{payload}` continues.")
        self.assertEqual(matches, [(payload, "")])

    @settings(max_examples=200, deadline=None)
    @given(
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=1, max_size=30),
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789/_-.", min_size=1, max_size=40
        ).filter(lambda value: ")" not in value),
    )
    def test_markdown_link_detector_ignores_translated_label(self, label, target):
        left = _LINK.findall(f"[{label}](https://example.test/{target})")
        right = _LINK.findall(f"[prevedeno](https://example.test/{target})")
        self.assertEqual(left, right)


if __name__ == "__main__":
    unittest.main()
