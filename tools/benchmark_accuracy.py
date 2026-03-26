#!/usr/bin/env python3
import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine import enumerator


@dataclass
class CaseResult:
    platform: str
    username: str
    expected_exists: bool
    predicted_exists: bool | None
    status: str
    detection_method: str
    http_status: int
    error: str


def _load_dataset(path: Path) -> List[Dict[str, Any]]:
    with path.open('r', encoding='utf-8') as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError('Dataset must be a JSON array')
    validated = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f'Entry {index} must be an object')
        platform = str(item.get('platform', '')).strip()
        username = str(item.get('username', '')).strip()
        expected_exists = item.get('expected_exists', None)
        if not platform or not username or not isinstance(expected_exists, bool):
            raise ValueError(f'Entry {index} missing required fields: platform, username, expected_exists(bool)')
        validated.append(
            {
                'platform': platform,
                'username': username,
                'expected_exists': expected_exists,
                'notes': str(item.get('notes', '')),
            }
        )
    return validated


def _predict_exists(status: str, exists: bool) -> bool | None:
    if status == 'Found':
        return True
    if status == 'Not Found':
        return False
    if status in {'Uncertain', 'Unsupported'}:
        return None
    return True if exists else False


def _evaluate_cases(cases: List[Dict[str, Any]]) -> List[CaseResult]:
    results: List[CaseResult] = []
    if hasattr(enumerator, '_RESULT_CACHE'):
        enumerator._RESULT_CACHE.clear()

    for case in cases:
        probe = enumerator.real_platform_check(case['username'], case['platform'], is_variant=False)
        predicted = _predict_exists(probe.status, probe.exists)
        results.append(
            CaseResult(
                platform=case['platform'],
                username=case['username'],
                expected_exists=case['expected_exists'],
                predicted_exists=predicted,
                status=probe.status,
                detection_method=probe.detection_method,
                http_status=probe.http_status,
                error=probe.error,
            )
        )
    return results


def _safe_div(n: float, d: float) -> float:
    return n / d if d else 0.0


def _f1(precision: float, recall: float) -> float:
    return _safe_div(2 * precision * recall, precision + recall)


def _metrics_for_group(group: List[CaseResult]) -> Dict[str, Any]:
    tp = fp = tn = fn = abstain = 0
    for row in group:
        if row.predicted_exists is None:
            abstain += 1
            continue
        if row.predicted_exists and row.expected_exists:
            tp += 1
        elif row.predicted_exists and (not row.expected_exists):
            fp += 1
        elif (not row.predicted_exists) and (not row.expected_exists):
            tn += 1
        else:
            fn += 1

    covered = len(group) - abstain
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    accuracy = _safe_div(tp + tn, covered)
    coverage = _safe_div(covered, len(group))
    f1 = _f1(precision, recall)

    return {
        'total': len(group),
        'covered': covered,
        'abstain': abstain,
        'tp': tp,
        'fp': fp,
        'tn': tn,
        'fn': fn,
        'precision': round(precision, 4),
        'recall': round(recall, 4),
        'accuracy': round(accuracy, 4),
        'coverage': round(coverage, 4),
        'f1': round(f1, 4),
        'score_10': round(10 * f1 * coverage, 2),
    }


def _build_report(rows: List[CaseResult]) -> Dict[str, Any]:
    by_platform: Dict[str, List[CaseResult]] = {}
    for row in rows:
        by_platform.setdefault(row.platform, []).append(row)

    platform_metrics = {platform: _metrics_for_group(group) for platform, group in sorted(by_platform.items())}
    overall = _metrics_for_group(rows)

    return {
        'overall': overall,
        'platforms': platform_metrics,
        'cases': [asdict(row) for row in rows],
    }


def _print_report(report: Dict[str, Any]) -> None:
    overall = report['overall']
    print('=== Accuracy Benchmark ===')
    print(f"Overall score (/10): {overall['score_10']}")
    print(
        f"Overall: f1={overall['f1']} coverage={overall['coverage']} "
        f"precision={overall['precision']} recall={overall['recall']} accuracy={overall['accuracy']}"
    )
    print('')
    print('Per-platform:')
    for platform, metrics in report['platforms'].items():
        print(
            f"- {platform}: score={metrics['score_10']}/10 "
            f"f1={metrics['f1']} coverage={metrics['coverage']} "
            f"(tp={metrics['tp']} fp={metrics['fp']} tn={metrics['tn']} fn={metrics['fn']} abstain={metrics['abstain']})"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description='Run username detection accuracy benchmark')
    parser.add_argument(
        '--dataset',
        default='benchmarks/username_ground_truth.sample.json',
        help='Path to JSON benchmark dataset',
    )
    parser.add_argument(
        '--platform',
        action='append',
        default=[],
        help='Filter by one or more platform names (repeatable)',
    )
    parser.add_argument('--max-cases', type=int, default=0, help='Limit number of cases for quick smoke runs')
    parser.add_argument('--output', default='', help='Optional output path for JSON report')
    parser.add_argument('--fail-below', type=float, default=-1.0, help='Exit non-zero if overall score_10 is below this value')
    parser.add_argument('--max-abstain-rate', type=float, default=-1.0, help='Exit non-zero if overall abstain/total exceeds this value (0-1)')
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        raise FileNotFoundError(f'Dataset not found: {dataset_path}')

    dataset = _load_dataset(dataset_path)

    if args.platform:
        allowed = {name.strip().lower() for name in args.platform if name.strip()}
        dataset = [item for item in dataset if item['platform'].lower() in allowed]

    if args.max_cases and args.max_cases > 0:
        dataset = dataset[: args.max_cases]

    if not dataset:
        raise ValueError('No benchmark cases selected after filters')

    rows = _evaluate_cases(dataset)
    report = _build_report(rows)
    _print_report(report)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(f'\nWrote JSON report: {output_path}')

    overall = report['overall']
    score_10 = float(overall.get('score_10', 0.0))
    abstain_rate = (overall.get('abstain', 0) / overall.get('total', 1)) if overall.get('total', 0) else 0.0

    if args.fail_below >= 0.0 and score_10 < args.fail_below:
        print(f'\nFAIL: overall score {score_10} is below target {args.fail_below}')
        return 2

    if args.max_abstain_rate >= 0.0 and abstain_rate > args.max_abstain_rate:
        print(f'\nFAIL: abstain rate {abstain_rate:.4f} exceeds max {args.max_abstain_rate}')
        return 3

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
