"""Run local text correction acceptance with real EdgeJev weights; never controls HA.

python -m moqi.voice_benchmark --model /path/to/jev-int8 --output data/voice-report.json
"""
import argparse
import json
import platform
import statistics
import time
from pathlib import Path
from .voice import LocalCorrectionParser

CONFIG = {'entities': {
    'switch.dining_light': {'role': 'actuator', 'aliases': ['餐厅灯']},
    'switch.fan': {'role': 'actuator', 'aliases': ['风扇']},
}}
# Fixed home-domain labels, including ambiguity and requests outside the domain.
CASES = [
    ('晚上不要自动关餐厅灯', {'intent': 'constraint', 'entity_id': 'switch.dining_light', 'scope': 'night', 'deny_actions': ['turn_off']}),
    ('不要自动开风扇', {'intent': 'constraint', 'entity_id': 'switch.fan', 'scope': 'always', 'deny_actions': ['turn_on']}),
    ('你最近学到了什么', {'intent': 'memory_changes'}),
    ('为什么关灯？', {'intent': 'explain'}),
    ('以后夜里餐厅灯就别自行熄灭了', {'intent': 'constraint_candidate', 'entity_id': 'switch.dining_light', 'scope': 'night', 'deny_actions': ['turn_off']}),
    ('以后任何时候风扇都别自己启动', {'intent': 'constraint_candidate', 'entity_id': 'switch.fan', 'scope': 'always', 'deny_actions': ['turn_on']}),
    ('不要关那个', {'intent': 'unknown'}),
    ('不要关餐厅灯和风扇', {'intent': 'unknown'}),
    ('把安全限制全部取消', {'intent': 'unknown'}),
    ('把餐厅灯打开', {'intent': 'unknown'}),
    ('如果很热，也许风扇可以开一下', {'intent': 'unknown'}),
    ('今晚不要自动关餐厅灯，明晚可以', {'intent': 'unknown'}),
]


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument('--model', required=True)
    args.add_argument('--output', required=True)
    args.add_argument('--repeat', type=int, default=3)
    opts = args.parse_args()
    if opts.repeat < 1:
        args.error('--repeat must be positive')
    output = Path(opts.output)
    if output.exists():
        args.error('output already exists; choose a new report filename')
    report = {'platform': platform.platform(), 'machine': platform.machine(),
              'python': platform.python_version(), 'model_path': str(Path(opts.model).resolve()),
              'execution_enabled': False, 'scope': 'text correction; no microphone, ASR, or HA control'}
    started = time.perf_counter()
    try:
        parser = LocalCorrectionParser(CONFIG, model_path=opts.model)
    except (RuntimeError, OSError, ValueError) as exc:
        report.update(status='blocked', reason=str(exc))
    else:
        report['load_ms'] = (time.perf_counter() - started) * 1000
        rows = []
        for text, expected in CASES:
            # First call reported separately from repeat timings: includes cold inference.
            started = time.perf_counter()
            first = parser.parse(text)
            cold = (time.perf_counter() - started) * 1000
            samples = []
            results = [first]
            for _ in range(opts.repeat):
                started = time.perf_counter()
                results.append(parser.parse(text))
                samples.append((time.perf_counter() - started) * 1000)
            passed = all(all(r.get(k) == v for k, v in expected.items()) and
                         (r.get('intent') != 'constraint_candidate' or r.get('requires_explicit_app_acceptance') is True)
                         for r in results)
            rows.append({'text': text, 'expected': expected, 'results': results,
                         'passed': passed, 'first_call_ms': cold,
                         'median_ms': statistics.median(samples), 'max_ms': max(samples)})
        model_times = [row['median_ms'] for row in rows if row['results'][0].get('source') == 'edgejev']
        report.update(status='completed', cases=rows, passed=sum(row['passed'] for row in rows),
                      total=len(rows), model_routed_cases=len(model_times),
                      model_route_median_ms=statistics.median(model_times) if model_times else None,
                      acceptance='pass' if all(row['passed'] for row in rows) else 'fail')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'cases'}, ensure_ascii=False))
    return 2 if report['status'] == 'blocked' else 0 if report['acceptance'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
