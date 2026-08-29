import unittest

from app.services.assistant import build_fallback_answer
from app.services.sentiment import _lexicon_sentiment, _demo_review_seed, analyze_reviews


class AssistantAndSentimentTests(unittest.TestCase):
    def test_lexicon_sentiment_works(self):
        self.assertEqual(_lexicon_sentiment("excellent battery and fast charging"), "positive")
        self.assertEqual(_lexicon_sentiment("broken screen and worst quality"), "negative")
        self.assertEqual(_lexicon_sentiment("okay product and average performance"), "neutral")

    def test_fallback_seed_uses_real_review_count_and_product_context(self):
        reviews_a = _demo_review_seed("Dell XPS 13", 523)
        reviews_b = _demo_review_seed("HP Pavilion 15", 523)
        result_a = analyze_reviews(reviews_a, product_context="Dell XPS 13", total_review_count=523)
        result_b = analyze_reviews(reviews_b, product_context="HP Pavilion 15", total_review_count=523)
        self.assertEqual(len(reviews_a), 523)
        self.assertEqual(len(reviews_b), 523)
        self.assertNotEqual(result_a["positive_pct"], result_b["positive_pct"]) 
        self.assertNotEqual(result_a["summary_text"], result_b["summary_text"])
    def test_fallback_answer_includes_product_context(self):
        answer = build_fallback_answer(
            "Which model is best for gaming?",
            "PRODUCT: ASUS TUF A15\nSpecs: GPU: RTX 4060, RAM: 16GB\nReview excerpts: (positive) Great gaming performance | (negative) battery drains quickly",
            ["ASUS TUF A15"],
        )
        self.assertIn("ASUS TUF A15", answer)
        self.assertIn("gaming", answer.lower())
        self.assertIn("battery", answer.lower())


if __name__ == "__main__":
    unittest.main()
