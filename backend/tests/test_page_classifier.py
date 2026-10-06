"""Unit tests for PageClassifier."""

import pytest

from app.services.crawler.classifier import (
    DEFAULT_KEYWORDS,
    RELEVANCE_THRESHOLD,
    PageClassifier,
)


@pytest.fixture
def classifier():
    """Create a PageClassifier with default keywords and some aggregator domains."""
    return PageClassifier(
        aggregator_domains=["mastersportal.com", "hotcoursesabroad.com"]
    )


@pytest.fixture
def bare_classifier():
    """Create a PageClassifier with no aggregator domains."""
    return PageClassifier()


class TestClassifyKeywordThreshold:
    """Tests for keyword-based relevance classification."""

    def test_relevant_with_three_keywords_in_body(self, classifier):
        result = classifier.classify(
            url="https://example.com/page",
            title="Some Page",
            body_text="This page covers visa requirements, immigration rules, and scholarship info.",
        )
        assert result.is_relevant is True
        assert len(result.matched_keywords) >= RELEVANCE_THRESHOLD

    def test_irrelevant_with_fewer_than_three_keywords(self, classifier):
        result = classifier.classify(
            url="https://example.com/page",
            title="Some Page",
            body_text="This page mentions visa only once.",
        )
        assert result.is_relevant is False
        assert len(result.matched_keywords) < RELEVANCE_THRESHOLD

    def test_irrelevant_with_no_keywords(self, classifier):
        result = classifier.classify(
            url="https://example.com/page",
            title="Cooking Recipes",
            body_text="Today we will make a delicious pasta dish with tomato sauce.",
        )
        assert result.is_relevant is False
        assert result.matched_keywords == []

    def test_keywords_in_title_count(self, classifier):
        result = classifier.classify(
            url="https://example.com/page",
            title="Visa Immigration Scholarship",
            body_text="",
        )
        assert result.is_relevant is True