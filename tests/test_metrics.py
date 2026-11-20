"""
Testes unitários para o módulo puro core.analytics.metrics.
"""

import time
import unittest

from core.analytics.metrics import calculate_analytics_metrics


class TestAnalyticsMetrics(unittest.TestCase):
    def test_empty_history(self):
        metrics = calculate_analytics_metrics([])
        self.assertEqual(metrics["total_prompts"], 0)
        self.assertEqual(metrics["total_words"], 0)
        self.assertEqual(metrics["words_today"], 0)
        self.assertEqual(metrics["saved_hours"], 0)
        self.assertEqual(metrics["saved_minutes"], 0)
        self.assertEqual(metrics["avg_wpm"], 0)
        self.assertEqual(metrics["peak_hour"], "--")
        self.assertEqual(metrics["top_keywords"], [])
        self.assertEqual(metrics["favorite_mode"], "Ditado PT")

    def test_calculation_with_entries(self):
        hoje = time.strftime("%d/%m/%Y")
        history = [
            {
                "text": "arquitetura modular e de software python",
                "words": 6,
                "timestamp": f"{hoje} 14:30:00",
                "mode": "transcribe"
            },
            {
                "text": "software python arquitetura robusta",
                "words": 4,
                "timestamp": f"{hoje} 14:45:00",
                "mode": "transcribe"
            },
            {
                "text": "yesterday meeting notes",
                "words": 3,
                "timestamp": "01/01/2026 10:00:00",
                "mode": "translate"
            }
        ]

        metrics = calculate_analytics_metrics(history)
        self.assertEqual(metrics["total_prompts"], 3)
        self.assertEqual(metrics["total_words"], 13)
        self.assertEqual(metrics["words_today"], 10)
        self.assertEqual(metrics["avg_wpm"], 0, "sem duração gravada não há velocidade medida")
        self.assertEqual(metrics["peak_hour"], "14:00 - 15:00")
        self.assertEqual(metrics["modes_count"]["transcribe"], 2)
        self.assertEqual(metrics["modes_count"]["translate"], 1)

        # Palavras-chave: stopwords removidas, capitalizadas
        self.assertIn("Arquitetura", metrics["top_keywords"])
        self.assertIn("Software", metrics["top_keywords"])
        self.assertIn("Python", metrics["top_keywords"])
        self.assertNotIn("De", metrics["top_keywords"])
        self.assertNotIn("E", metrics["top_keywords"])

    def test_favorite_mode_detection(self):
        # Mais translate do que transcribe
        history = [
            {"text": "hello world", "words": 2, "timestamp": "01/01/2026 10:00:00", "mode": "translate"},
            {"text": "good morning", "words": 2, "timestamp": "01/01/2026 11:00:00", "mode": "translate"},
            {"text": "bom dia", "words": 2, "timestamp": "01/01/2026 12:00:00", "mode": "transcribe"}
        ]
        metrics = calculate_analytics_metrics(history)
        self.assertEqual(metrics["favorite_mode"], "Tradução EN")

        # Mais meeting do que transcribe
        history = [
            {"text": "reuniao de alinhamento", "words": 3, "timestamp": "01/01/2026 10:00:00", "mode": "meeting"},
            {"text": "pauta discutida", "words": 2, "timestamp": "01/01/2026 11:00:00", "mode": "meeting"}
        ]
        metrics = calculate_analytics_metrics(history)
        self.assertEqual(metrics["favorite_mode"], "Reunião")

        # Mais prompt do que transcribe (AUD-015)
        history = [
            {"text": "criar prompt estruturado", "words": 3, "timestamp": "01/01/2026 10:00:00", "mode": "prompt"},
            {"text": "outro prompt", "words": 2, "timestamp": "01/01/2026 11:00:00", "mode": "prompt"},
            {"text": "ditado simples", "words": 2, "timestamp": "01/01/2026 12:00:00", "mode": "transcribe"},
        ]
        self.assertEqual(calculate_analytics_metrics(history)["favorite_mode"], "Prompt")

        # Mais transform do que transcribe (AUD-015)
        history = [
            {"text": "texto transformado um", "words": 3, "timestamp": "01/01/2026 10:00:00", "mode": "transform"},
            {"text": "texto transformado dois", "words": 3, "timestamp": "01/01/2026 11:00:00", "mode": "transform"},
            {"text": "ditado simples", "words": 2, "timestamp": "01/01/2026 12:00:00", "mode": "transcribe"},
        ]
        self.assertEqual(calculate_analytics_metrics(history)["favorite_mode"], "Transformar")

    def test_iso_timestamp_counts_words_today_and_peak_hour(self):
        """AUD-014: timestamps em formato ISO (YYYY-MM-DD HH:MM[:SS]) devem contabilizar words_today e peak_hour."""
        hoje_iso = time.strftime("%Y-%m-%d")
        history = [
            {"text": "ditado iso com segundos", "words": 4, "timestamp": f"{hoje_iso} 09:15:30", "mode": "transcribe"},
            {"text": "ditado iso sem segundos", "words": 3, "timestamp": f"{hoje_iso} 09:45", "mode": "transcribe"},
        ]
        metrics = calculate_analytics_metrics(history)
        self.assertEqual(metrics["words_today"], 7)
        self.assertEqual(metrics["peak_hour"], "09:00 - 10:00")


if __name__ == "__main__":
    unittest.main()

