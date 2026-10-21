"""Input regression tests do not constitute live placement validation."""
import json
from pathlib import Path

import pytest

from app.cli.main import main
from app.cli.saved_inputs import load_saved_input
from app.cli.yaml_io import AnalyzeError
from app.data.loader import load_compute_targets

ROOT = Path(__file__).resolve().parents[2]
WORKLOAD = str(ROOT / 'examples/workload.yaml')


def write(tmp_path, name, raw):
    path = tmp_path / name
    path.write_text(json.dumps(raw))
    return str(path)


def test_multiple_inputs(tmp_path, monkeypatch, capsys):
    import app.cli.main as cli
    from app.core.schemas import PerformanceEvidence
    targets = load_compute_targets()[:2]
    evidence = [PerformanceEvidence(compute_target_id=t.id, workload_id='wl-llama70b-rt',
                benchmark_run_id=f'run-{i}', provenance='MEASURED', confidence=90)
                for i, t in enumerate(targets)]
    real = cli.run_decision
    def capture(*args, **kwargs):
        assert kwargs['targets'] == targets
        assert kwargs['imported_evidence'] == evidence
        return real(*args, **kwargs)
    monkeypatch.setattr(cli, 'run_decision', capture)
    def forbidden():
        pytest.fail('targets-only must not load fixtures or discover')
    monkeypatch.setattr(cli, 'load_compute_targets', forbidden)
    monkeypatch.setattr(cli, 'run_discovery', forbidden)
    argv = ['analyze', WORKLOAD, '--targets-only', '--json']
    for i, t in enumerate(targets):
        argv += ['--target-file', write(tmp_path, f't{i}', t.model_dump(mode='json'))]
    for i, e in enumerate(evidence):
        argv += ['--evidence-file', write(tmp_path, f'e{i}', e.model_dump(mode='json'))]
    assert main(argv) == 0
    assert set(json.loads(capsys.readouterr().out)['evaluated_targets']) == {t.id for t in targets}


@pytest.mark.parametrize('name,latency,throughput', [('nvidia', 2099.08, 60.98), ('amd', 792.8, 161.45)])
def test_saved_measurements(name, latency, throughput):
    e = load_saved_input(str(ROOT / f'results/{name}-run.json'), target=False)
    assert e.metrics['end_to_end_latency_ms'].value == latency
    assert e.metrics['throughput_tokens_per_s_per_replica'].value == throughput
    assert e.provenance == 'MEASURED'


@pytest.mark.parametrize('mutation,message', [
    (lambda r: r.update(schema_version='future'), 'schema_version'),
    (lambda r: r.pop('schema_version'), 'schema_version'),
    (lambda r: r['target'].update(schema_version='future'), 'schema_version'),
    (lambda r: r['performance_evidence'].update(schema_version='future'), 'schema_version'),
    (lambda r: r['performance_evidence'].update(compute_target_id='other'), 'target.id differs'),
    (lambda r: r.update(run_id='other'), 'run_id differs'),
    (lambda r: r['performance_evidence'].update(workload_id=' '), 'nonempty ID'),
])
def test_invalid_envelopes(tmp_path, mutation, message):
    raw = json.loads((ROOT / 'results/amd-run.json').read_text())
    mutation(raw)
    with pytest.raises(AnalyzeError, match=message):
        load_saved_input(write(tmp_path, 'bad', raw), target=False)


@pytest.mark.parametrize('kind', ['missing', 'malformed', 'directory', 'array', 'duplicate-target', 'fixture-collision', 'no-targets', 'wrong-workload', 'unknown-target', 'duplicate-run', 'store-collision', 'blank-target'])
def test_clean_errors(kind, tmp_path, capsys):
    t = load_compute_targets()[0].model_dump(mode='json')
    t['id'] = 'saved'
    target = write(tmp_path, 'target', t)
    e = json.loads((ROOT / 'results/amd-run.json').read_text())['performance_evidence']
    e.update(compute_target_id='saved', workload_id='wl-llama70b-rt')
    argv = ['analyze', WORKLOAD, '--targets-only', '--target-file', target]
    if kind == 'missing': argv += ['--evidence-file', str(tmp_path / 'missing')]
    elif kind == 'malformed':
        (tmp_path / 'bad').write_text('{')
        argv += ['--evidence-file', str(tmp_path / 'bad')]
    elif kind == 'directory': argv += ['--evidence-file', str(tmp_path)]
    elif kind == 'array': argv += ['--evidence-file', write(tmp_path, 'array', [])]
    elif kind == 'duplicate-target': argv += ['--target-file', target]
    elif kind == 'fixture-collision':
        t['id'] = load_compute_targets()[0].id
        write(tmp_path, 'target', t)
        argv.remove('--targets-only')
    elif kind == 'no-targets': argv = ['analyze', WORKLOAD, '--targets-only']
    elif kind == 'blank-target':
        t['id'] = ' '
        write(tmp_path, 'target', t)
    else:
        if kind == 'wrong-workload': e['workload_id'] = 'other'
        if kind == 'unknown-target': e['compute_target_id'] = 'other'
        ep = write(tmp_path, 'e', e)
        argv += ['--evidence-file', ep]
        if kind == 'duplicate-run': argv += ['--evidence-file', ep]
        if kind == 'store-collision':
            from app.core.schemas import PerformanceEvidence
            from app.benchmark.store import save_run
            save_run(PerformanceEvidence.model_validate(dict(e, source='conflicting')))
    assert main(argv) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert 'forgeway analyze:' in captured.err
    assert 'Traceback' not in captured.err


def test_warnings_keep_json_clean(tmp_path, capsys):
    raw = json.loads((ROOT / 'results/nvidia-run.json').read_text())
    path = write(tmp_path, 'target', raw['target'])
    assert main(['analyze', WORKLOAD, '--targets-only', '--target-file', path, '--json']) == 0
    output = capsys.readouterr()
    json.loads(output.out)
    for field in ['memory_gb_per_device', 'supported_precisions', 'runtime_support', 'pricing unavailable']:
        assert field in output.err


def test_additive_targets_and_discovery_collision(tmp_path, monkeypatch, capsys):
    target = load_compute_targets()[0].model_copy(update={'id': 'saved'})
    path = write(tmp_path, 'target', target.model_dump(mode='json'))
    assert main(['analyze', WORKLOAD, '--skip-discovery', '--target-file', path, '--json']) == 0
    evaluated = json.loads(capsys.readouterr().out)['evaluated_targets']
    assert set(evaluated) == {t.id for t in load_compute_targets()} | {'saved'}
    monkeypatch.setattr('app.cli.main.run_discovery', lambda: target)
    assert main(['analyze', WORKLOAD, '--target-file', path]) == 1
    assert 'collides with a saved target' in capsys.readouterr().err


def test_identical_store_evidence_is_accepted(tmp_path):
    from app.benchmark.store import save_run
    from app.cli.saved_inputs import validate_evidence
    e = load_saved_input(str(ROOT / 'results/amd-run.json'), target=False)
    raw = json.loads((ROOT / 'results/amd-run.json').read_text())
    target = load_saved_input(write(tmp_path, 'target', raw['target']), target=True)
    save_run(e)
    validate_evidence([e], [target], e.workload_id)


@pytest.mark.parametrize('envelope', [False, True], ids=['plain', 'envelope'])
@pytest.mark.parametrize('metric,value', [
    ('throughput_tokens_per_s_per_replica', 0),
    ('throughput_tokens_per_s_per_replica', -1),
    ('throughput_tokens_per_s_per_replica', float('nan')),
    ('throughput_tokens_per_s_per_replica', float('inf')),
    ('throughput_tokens_per_s_per_replica', -float('inf')),
    ('p99_latency_ms_per_replica', -1),
    ('p99_latency_ms_per_replica', float('nan')),
    ('p99_latency_ms_per_replica', float('inf')),
    ('p99_latency_ms_per_replica', -float('inf')),
])
def test_invalid_scoring_metrics_report_file_and_metric(tmp_path, capsys, envelope, metric, value):
    raw = json.loads((ROOT / 'results/amd-run.json').read_text())
    raw['performance_evidence']['metrics'][metric]['value'] = value
    path = write(tmp_path, 'invalid.json', raw if envelope else raw['performance_evidence'])
    assert main(['analyze', WORKLOAD, '--skip-discovery', '--evidence-file', path]) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert path in captured.err
    assert f'metrics.{metric}.value' in captured.err
    assert 'finite and' in captured.err
    assert 'Traceback' not in captured.err


def test_zero_latency_and_positive_throughput_are_valid(tmp_path):
    raw = json.loads((ROOT / 'results/amd-run.json').read_text())['performance_evidence']
    raw['metrics']['p99_latency_ms_per_replica']['value'] = 0
    raw['metrics']['throughput_tokens_per_s_per_replica']['value'] = 0.01
    e = load_saved_input(write(tmp_path, 'valid.json', raw), target=False)
    assert e.metrics['p99_latency_ms_per_replica'].value == 0
    assert e.metrics['throughput_tokens_per_s_per_replica'].value == 0.01


@pytest.mark.parametrize('conflict_first', [True, False], ids=['conflict-first', 'conflict-last'])
def test_cli_checks_all_stored_records_with_same_run_id(tmp_path, capsys, conflict_first):
    from app.benchmark.store import results_dir
    raw = json.loads((ROOT / 'results/amd-run.json').read_text())
    evidence = raw['performance_evidence']
    evidence['workload_id'] = 'wl-llama70b-rt'
    conflicting = dict(evidence, source='Synthetic conflicting record')
    directory = results_dir()
    directory.mkdir()
    records = [conflicting, evidence] if conflict_first else [evidence, conflicting]
    for i, record in enumerate(records):
        write(directory, f'{i}.json', record)
    target_path = write(tmp_path, 'target.json', raw['target'])
    evidence_path = write(tmp_path, 'import.json', evidence)
    assert main(['analyze', WORKLOAD, '--targets-only', '--target-file', target_path,
                 '--evidence-file', evidence_path]) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert evidence['benchmark_run_id'] in captured.err
    assert 'collides with different evidence' in captured.err


@pytest.mark.parametrize('p99_limit', [2500, 1000], ids=['baseline', 'tightened'])
def test_cli_scores_complete_synthetic_evidence_and_withholds_for_unknown_price(
    tmp_path, monkeypatch, capsys, p99_limit,
):
    import app.cli.main as cli
    from app.benchmark.store import results_dir
    from app.qualification.store import qualifications_dir
    from app.core.schemas import ComputeTarget, Metric, PerformanceEvidence
    from app.cli.yaml_io import load_workload_yaml

    assert results_dir().is_relative_to(tmp_path) and not results_dir().exists()
    assert qualifications_dir().is_relative_to(tmp_path) and not qualifications_dir().exists()
    workload = load_workload_yaml(Path(WORKLOAD)).model_dump(mode='json')
    workload.update(
        id='synthetic-saved-cli-workload', name='Synthetic offline CLI replay',
        model_family='Synthetic model', model_params_billion=1.5,
        workload_class='batch-inference', precision='bf16',
        weights_footprint_gb=4, kv_cache_overhead_gb=2, baseline_concurrency=1,
        slo={'p99_latency_ms': p99_limit, 'min_throughput_tokens_per_s': 50, 'availability_pct': 99.9},
        policy={'allowed_vendors': ['nvidia', 'amd'], 'allowed_regions': ['synthetic-region'],
                'budget_ceiling_per_hr': 0},
        current_placement={'target_id': 'synthetic-baseline', 'replica_count': 1,
                           'measured_p99_latency_ms': 0, 'measured_throughput_tokens_per_s_per_replica': 0,
                           'cost_per_hr': 0, 'provenance': 'MODELED', 'source': 'Synthetic schema placeholder'},
        objective_weights={'cost': 0, 'performance': 1, 'headroom': 0}, min_confidence_pct=70,
    )
    argv = ['analyze', write(tmp_path, 'workload.json', workload), '--targets-only', '--json']
    expected = {}
    for vendor, latency, throughput in [('nvidia', 2000, 60), ('amd', 800, 160)]:
        target_id = f'synthetic-saved-{vendor}'
        target = ComputeTarget(
            id=target_id, vendor=vendor, model=f'Synthetic {vendor} GPU', tier='lab',
            location='synthetic-region', architecture='synthetic', memory_gb_per_device=16,
            interconnect='synthetic single device', supported_precisions=['bf16'], runtime_support=['vllm'],
            capacity_units_total=1, capacity_units_allocated=0,
            price_per_hr_per_unit=Metric(value=0, confidence=0, provenance='MODELED', source='Pricing unavailable'),
            status='healthy',
        )
        run_id = f'synthetic-run-{vendor}'
        evidence = PerformanceEvidence(
            compute_target_id=target_id, workload_id=workload['id'], benchmark_run_id=run_id,
            provenance='MEASURED', confidence=95, source='Synthetic test data, not hardware measurements',
            metrics={
                'p99_latency_ms_per_replica': Metric(value=latency, confidence=95, provenance='MEASURED', source='synthetic'),
                'throughput_tokens_per_s_per_replica': Metric(value=throughput, confidence=95, provenance='MEASURED', source='synthetic'),
            },
        )
        argv += ['--target-file', write(tmp_path, f'{vendor}-target.json', target.model_dump(mode='json')),
                 '--evidence-file', write(tmp_path, f'{vendor}-evidence.json', evidence.model_dump(mode='json'))]
        expected[target_id] = (run_id, latency, throughput)

    def forbidden():
        pytest.fail('targets-only must exclude fixture targets and discovery')
    monkeypatch.setattr(cli, 'load_compute_targets', forbidden)
    monkeypatch.setattr(cli, 'run_discovery', forbidden)
    # Disable fixture evidence so missing imports cannot be masked by fallback.
    fixture_lookups = []
    def no_fixture(workload_id, target_id):
        assert workload_id == workload['id'] and target_id in expected
        fixture_lookups.append(target_id)
        return None
    monkeypatch.setattr('app.engine.evidence_gateway.get_performance_profile', no_fixture)
    records = []
    real = cli.run_decision
    def capture(*args, **kwargs):
        record = real(*args, **kwargs)
        records.append(record)
        return record
    monkeypatch.setattr(cli, 'run_decision', capture)

    assert main(argv) == 0
    captured = capsys.readouterr()
    decision = json.loads(captured.out)
    assert set(decision['evaluated_targets']) == set(expected)
    assert set(decision['feasible_targets']) == set(expected)
    assert decision['recommended_target_id'] is None
    assert decision['score_breakdown'] == {}
    assert decision['improvement_vs_current_placement'] is None
    assert set(fixture_lookups) == set(expected)
    assert len(records) == 1
    record = records[0]
    assert record.recommended_target_id is None and record.split_allocation == []
    assert 'Recommendation withheld' in record.reasoning
    for c in record.candidates:
        run_id, latency, throughput = expected[c.target_id]
        prediction = c.raw_prediction
        assert c.feasible and prediction is not None
        assert prediction.latency_p99_ms.value == latency
        assert prediction.throughput_tokens_per_s.value == throughput
        assert prediction.latency_p99_ms.evidence_reference == run_id
        assert prediction.throughput_tokens_per_s.evidence_reference == run_id
        assert prediction.latency_p99_ms.confidence == 95
        assert prediction.throughput_tokens_per_s.confidence == 95
        assert prediction.cost_per_hr.confidence == 0
        assert c.confidence_pct == 0
        assert c.predicted.meets_slo is (latency <= p99_limit)
        assert c.rank is None and c.weighted_score is None
        if latency <= p99_limit:
            assert c.meets_confidence_requirement is False
            assert '0% confidence is below the 70%' in c.why_not_chosen
        else:
            assert c.meets_confidence_requirement is None
            assert any('exceeds' in reason for reason in c.slo_violations)
