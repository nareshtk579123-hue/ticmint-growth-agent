"""
Precision & Quality Evaluation Script for Ticmint Growth Agent.
Evaluates the agent's classification, scoring rubric, and priority tiers
against the 32-record ground truth dataset in data/labeled_evaluation_set.json.
Calculates High-Priority Precision, Overall Accuracy, and False Positive/Negative rates.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List
from app.config import config
from app.llm import LLMAnalyzer
from app.models import RawSignal
from app.scoring import LeadScorer


def run_evaluation(dataset_path: Path = config.LABELED_SET_PATH):
    print("=" * 78)
    print("      TICMINT GROWTH AGENT - LEAD QUALIFICATION PRECISION AUDIT")
    print("=" * 78)

    if not dataset_path.exists():
        print(f"Error: Dataset not found at {dataset_path}")
        return

    with open(dataset_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    print(f"Loaded {len(records)} benchmark evaluation records with ground-truth labels.\n")

    analyzer = LLMAnalyzer()

    total_records = len(records)
    true_high_priority_detected = 0
    false_high_priority_detected = 0
    predicted_high_priority_count = 0
    actual_high_priority_count = 0

    true_positives_qualified = 0
    false_positives_qualified = 0
    true_negatives_disqualified = 0
    false_negatives_disqualified = 0

    category_confusion: Dict[str, Dict[str, int]] = {}

    for item in records:
        text = item["text"]
        author = item.get("author", "eval_user")
        url = item.get("url", "https://example.com/eval")
        published_at = item.get("published_at", "2026-10-18T12:00:00Z")
        gt = item["ground_truth"]

        sig = RawSignal(
            source="evaluation",
            source_id=item["id"],
            author=author,
            text=text,
            url=url,
            canonical_url=url,
            published_at=published_at,
        )

        analysis = analyzer.analyze_signal(sig)
        score_breakdown = LeadScorer.score_signal(sig, analysis)

        pred_priority = score_breakdown.priority.value
        gt_priority = gt["ground_truth_priority"]
        pred_is_qualified = score_breakdown.total_score >= 50
        gt_is_qualified = gt["is_qualified"]

        # Track High Priority Precision
        if pred_priority == "HIGH":
            predicted_high_priority_count += 1
            if gt_priority == "HIGH":
                true_high_priority_detected += 1
            else:
                false_high_priority_detected += 1

        if gt_priority == "HIGH":
            actual_high_priority_count += 1

        # Track General Qualification (Confusion Matrix)
        if pred_is_qualified and gt_is_qualified:
            true_positives_qualified += 1
        elif pred_is_qualified and not gt_is_qualified:
            false_positives_qualified += 1
        elif not pred_is_qualified and not gt_is_qualified:
            true_negatives_disqualified += 1
        else:
            false_negatives_disqualified += 1

    # Metrics
    high_priority_precision = (
        (true_high_priority_detected / predicted_high_priority_count * 100)
        if predicted_high_priority_count > 0 else 0.0
    )
    high_priority_recall = (
        (true_high_priority_detected / actual_high_priority_count * 100)
        if actual_high_priority_count > 0 else 0.0
    )
    overall_accuracy = (
        (true_positives_qualified + true_negatives_disqualified) / total_records * 100
    )

    print(f"Total Evaluated Records:           {total_records}")
    print(f"Ground Truth High Priority Count:  {actual_high_priority_count}")
    print(f"Predicted High Priority Count:     {predicted_high_priority_count}")
    print(f"True High Priority (Correct):      {true_high_priority_detected}")
    print(f"False High Priority (False Alarm): {false_high_priority_detected}")
    print("-" * 78)
    print(f"High-Priority Precision:           {high_priority_precision:.1f}%  (Target: >= 80.0%)")
    print(f"High-Priority Recall:              {high_priority_recall:.1f}%")
    print(f"Overall Classification Accuracy:   {overall_accuracy:.1f}%\n")

    print("CONFUSION MATRIX (Qualified vs Disqualified):")
    print(f"  True Positives  (Correctly Qualified):     {true_positives_qualified}")
    print(f"  True Negatives  (Correctly Disqualified):   {true_negatives_disqualified}")
    print(f"  False Positives (Incorrectly Qualified):   {false_positives_qualified}")
    print(f"  False Negatives (Missed Qualified):        {false_negatives_disqualified}")
    print("=" * 78)

    status = "PASSED ACCEPTANCE TARGET" if high_priority_precision >= 80.0 else "NEEDS REFINEMENT"
    print(f"VERDICT: {status} ({high_priority_precision:.1f}% >= 80.0%)\n")
    return high_priority_precision


if __name__ == "__main__":
    run_evaluation()
