from __future__ import annotations

from argparse import Namespace
import unittest

from facet_terminal.pipeline import stages_to_run
from facet_terminal.input_adapters import InputAdapterError, adapt_record
from facet_terminal.stages.convert_input.stage import convert_input_record


class SkillPairInputTest(unittest.TestCase):
    def test_convert_input_record_accepts_exactly_two_skills(self) -> None:
        unit = convert_input_record(
            {
                "pair_id": "pair_demo",
                "skill_ids": ["skill_a", "skill_b"],
                "skill_summaries": ["summary a", "summary b"],
                "scenario_texts": ["initial context", "desired outcome"],
            },
            1,
            "skill_pairs.jsonl",
            {"format": "skill_pair_jsonl"},
        )

        self.assertEqual(unit["pair_id"], "pair_demo")
        self.assertEqual(unit["pair_size"], 2)
        self.assertEqual(unit["skill_ids"], ["skill_a", "skill_b"])

    def test_convert_input_record_rejects_non_pair_input(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly two skill_ids"):
            convert_input_record(
                {"skill_ids": ["skill_a"]},
                1,
                "skill_pairs.jsonl",
                {"format": "skill_pair_jsonl"},
            )

    def test_skill_object_adapter(self) -> None:
        adapted = adapt_record(
            {
                "pair_id": "pair_objects",
                "skills": [
                    {"id": "skill_a", "summary": "summary a"},
                    {"id": "skill_b", "summary": "summary b"},
                ],
                "scenarios": ["scenario"],
            },
            {"format": "skill_objects_jsonl"},
        )
        self.assertEqual(adapted["skill_ids"], ["skill_a", "skill_b"])
        self.assertEqual(adapted["scenario_texts"], ["scenario"])

    def test_mapped_adapter_supports_nested_fields(self) -> None:
        adapted = adapt_record(
            {
                "id": "pair_mapped",
                "payload": {"ids": ["skill_a", "skill_b"], "context": ["scenario"]},
            },
            {
                "format": "mapped_jsonl",
                "field_map": {
                    "pair_id": "id",
                    "skill_ids": "payload.ids",
                    "scenario_texts": "payload.context",
                },
            },
        )
        self.assertEqual(adapted["pair_id"], "pair_mapped")
        self.assertEqual(adapted["skill_ids"], ["skill_a", "skill_b"])

    def test_unknown_adapter_is_rejected(self) -> None:
        with self.assertRaisesRegex(InputAdapterError, "unsupported input format"):
            adapt_record({}, {"format": "unknown_jsonl"})

    def test_forward_is_the_default_core_strategy(self) -> None:
        args = Namespace(stage="all", strategy="FORWARD", from_stage=None)
        stages = stages_to_run(args)

        self.assertEqual(["instruction", "solution", "tests"], stages[7:10])
        self.assertNotIn("reverse_instruction", stages)
        self.assertNotIn("joint", stages)

    def test_experimental_strategies_are_mutually_exclusive(self) -> None:
        reverse = stages_to_run(Namespace(stage="all", strategy="REVERSE", from_stage=None))
        joint = stages_to_run(Namespace(stage="all", strategy="JOINT", from_stage=None))

        self.assertIn("reverse_instruction", reverse)
        self.assertNotIn("joint", reverse)
        self.assertIn("joint", joint)
        self.assertNotIn("reverse_instruction", joint)


if __name__ == "__main__":
    unittest.main()
