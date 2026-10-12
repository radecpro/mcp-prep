"""Answer contract tests; --live also exercises local Ollama and real retrieval."""

import argparse
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import answer


class AnswerContractChecks(unittest.TestCase):
    def test_citations_and_missing_context(self):
        valid = {"status": "answered", "claims": [{"text": "Objaw wymaga diagnostyki.", "citations": [1]}], "missing_information": []}
        answer.validate_answer(valid, 2)
        for citations in [[], [0], [3], [True], [1, 1], ["1"]]:
            with self.subTest(citations=citations):
                data = copy.deepcopy(valid)
                data["claims"][0]["citations"] = citations
                with self.assertRaises(ValueError):
                    answer.validate_answer(data, 2)
        answer.validate_answer({"status": "insufficient_context", "claims": [], "missing_information": ["Brak runbooka."]}, 2)
        with self.assertRaises(ValueError):
            answer.validate_answer({"status": "insufficient_context", "claims": valid["claims"], "missing_information": []}, 2)

    def test_complete_section_restores_cut_command(self):
        sources = answer.context_sources([
            {"source": "runbooks/crash-loop-back-off.md", "section": "Diagnostyka tylko do odczytu", "text": "ucięty fragment"},
            {"source": "runbooks/crash-loop-back-off.md", "section": "Diagnostyka tylko do odczytu", "text": "drugi fragment"},
        ])
        self.assertEqual(len(sources), 1)
        self.assertIn("--previous --tail=100 --timestamps", sources[0]["text"])
        self.assertIn("```bash", sources[0]["text"])
        with self.assertRaisesRegex(ValueError, "outside"):
            answer.context_sources([{"source": "../outside.md", "section": "Test"}])

    def test_incomplete_and_invalid_generation_rejected(self):
        results = [{"source": "runbooks/pending-pod.md", "section": "Objawy i znaczenie"}]
        envelopes = [
            {"done": True, "done_reason": "length", "message": {"content": "{}"}},
            {"done": False, "done_reason": "stop", "message": {"content": "{}"}},
            {"done": True, "done_reason": "stop", "message": {"content": json.dumps({"status": "answered", "claims": [{"text": "Fake", "citations": [99]}], "missing_information": []})}},
        ]
        for envelope in envelopes:
            opener = MagicMock()
            opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(envelope).encode()
            with patch.object(answer.rag, "search", return_value=results), patch.object(answer.rag, "load_index"), patch.object(answer, "build_opener", return_value=opener):
                with self.assertRaises(ValueError):
                    answer.ask("Test")

    def test_render_only_used_sources(self):
        result = {"status": "answered", "claims": [{"text": "Hipoteza.", "citations": [2]}], "missing_information": ["Brak eventów."], "sources": [
            {"number": 1, "source": "unused.md", "start_line": 1, "section": "A"},
            {"number": 2, "source": "used.md", "start_line": 10, "section": "B"},
        ]}
        text = answer.render(result)
        self.assertIn("Hipoteza. [2]", text)
        self.assertIn("used.md:10", text)
        self.assertNotIn("unused.md", text)


class ModelSmokeChecks(unittest.TestCase):
    def test_supported_questions(self):
        cases = [
            ("Kontener ma ImagePullBackOff. Event mówi manifest unknown. Co to oznacza i co sprawdzić?", "image-pull-backoff.md", "tag"),
            ("Aplikacja ciągle się restartuje. Jak odczytać logi poprzedniego uruchomienia kontenera?", "crash-loop-back-off.md", "--previous"),
            ("Czy faza Pending zawsze oznacza, że pod nie został przypisany do węzła?", "pending-pod.md", None),
        ]
        for query, expected, phrase in cases:
            with self.subTest(query=query):
                result = answer.ask(query)
                self.assertEqual(result["status"], "answered", result)
                used = {n for claim in result["claims"] for n in claim["citations"]}
                self.assertTrue(any(s["source"] == f"runbooks/{expected}" and s["number"] in used for s in result["sources"]), result)
                if phrase:
                    self.assertIn(phrase, " ".join(c["text"] for c in result["claims"]))
                print(f"\nPASS live: {query}\n{answer.render(result)}", flush=True)

    def test_unrelated_question_abstains(self):
        result = answer.ask("Jak obliczyć podatek VAT od sprzedaży samochodu w Polsce?")
        self.assertEqual(result["status"], "insufficient_context", result)
        self.assertEqual(result["claims"], [])
        print("\nPASS live: unrelated question rejected", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AnswerContractChecks)
    if args.live:
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ModelSmokeChecks))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
