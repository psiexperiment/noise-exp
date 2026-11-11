'''
The noise exposure through the loopback.

The speaker (`speaker_1`) is routed in TotalMix to the measurement
microphone the exposure is monitored with (`cal_microphone`), so the
microphone records exactly what the speaker played. The exposure runs to its
end, as it would on the rig, and then:

* the exposure is regenerated with psiaudio from its settings and seed and
  fit to the recording: it must start when psi starts it, at the level its
  settings and the speaker calibration ask for, with nothing missing,
  repeated or added (see `exposure_analysis`);
* every level psi reported from the microphone (the 1 s levels it saved, and
  the running averages and progress it showed while running) must match the
  same level calculations on the regenerated exposure.

The waveform itself is pinned by the golden exposure (`tests/test_golden.py`),
which needs no hardware.
'''
import json
from types import SimpleNamespace

import numpy as np
import pytest

from cftscal.objects import NominalInputCalibration, NominalSpeakerCalibration
from psidata.api import Recording
from psi.loopback.report import write_report
from psi.loopback.runner import log_problems

from exposure_analysis import analyze_exposure
import plots
from rig import INPUT_DBFS, MICROPHONE, SPEAKER
from runner import (MICROPHONE_GAIN, OUTPUT_CAL_DB, exposure_env,
                    measure_run_latency, microphone_mv_pa, require_routes,
                    run_exposure)


#: The exposure's settings: an octave band at a typical exposure level, but
#: only seconds long.
PARAMETERS = {
    'level': 105,
    'fl': 8e3,
    'fh': 16e3,
    # Not the default (1), to check the seed is used.
    'seed': 3,
    'equalize': True,
    'max_correction': 20,
    # Fixed by the paradigm (a value of its token, not a context item), so
    # it is not set, only used to regenerate the exposure.
    'correct_level': True,
    'duration': 10,
    'rise_time': 1,
}

#: The context item each setting is. Settings missing here are fixed by the
#: paradigm.
CONTEXT_NAMES = {
    'level': 'exposure_bandlimited_noise_level',
    'fl': 'exposure_bandlimited_noise_fl',
    'fh': 'exposure_bandlimited_noise_fh',
    'seed': 'exposure_bandlimited_noise_seed',
    'equalize': 'exposure_bandlimited_noise_equalize',
    'max_correction': 'exposure_bandlimited_noise_max_correction',
    'duration': 'exposure_bandlimited_fir_noise_burst_duration',
    'rise_time': 'exposure_bandlimited_fir_noise_burst_rise_time',
}

#: Long enough for psi to start, the exposure, and psi to save and quit.
TIMEOUT = PARAMETERS['duration'] + 120


def context_settings(p):
    '''
    `p` as context settings. The yes/no settings are drop-downs, set by the
    label they show.
    '''
    def setting(value):
        if isinstance(value, bool):
            return 'yes' if value else 'no'
        return value
    return {CONTEXT_NAMES[k]: setting(v) for k, v in p.items()
            if k in CONTEXT_NAMES}


@pytest.fixture(scope='module')
def exposure(routing, results_dir):
    require_routes(routing, {MICROPHONE: [SPEAKER]})
    route = routing.get(SPEAKER, MICROPHONE)
    route_gain_db = route.gain_db
    latency = measure_run_latency(SPEAKER, MICROPHONE)
    mv_pa = microphone_mv_pa(route_gain_db)

    run_dir = results_dir / 'noise_exposure'
    path = run_dir / 'data'
    status_path = run_dir / 'status.jsonl'
    settings = {
        'engine': {'latency_samples': latency},
        'parameters': context_settings(PARAMETERS),
    }
    run = run_exposure(path, settings, exposure_env(mv_pa), status_path,
                       TIMEOUT)
    if not run.completed:
        pytest.fail(run.describe())

    recording = Recording(path)
    microphone = recording.monitor_microphone
    fs = microphone.fs
    x = np.asarray(microphone[:]).ravel()
    psi_levels = np.asarray(recording.noise_level[:]).ravel()
    status = [json.loads(line) for line in
              status_path.read_text().splitlines()] \
        if status_path.exists() else []
    engine, = run.wrapup['engines'].values()

    a = analyze_exposure(
        x, fs, psi_levels, status, PARAMETERS, route_gain_db, INPUT_DBFS,
        MICROPHONE_GAIN, NominalSpeakerCalibration(OUTPUT_CAL_DB).load(),
        NominalInputCalibration(mv_pa).load(), latency, engine)

    problems = log_problems(run.log)
    a.checks.add('no errors logged', not problems,
                 f'{len(problems)} errors' if problems else 'none', 'none',
                 problems[0][:500] if problems else '')

    figures = [
        plots.plot_exposure(a, run_dir / 'exposure.png'),
        plots.plot_levels(a, run_dir / 'levels.png'),
        plots.plot_spectrum(a, PARAMETERS['fl'], PARAMETERS['fh'],
                            run_dir / 'spectrum.png'),
    ]
    p = PARAMETERS
    info = {
        'Paradigm': 'noise_exposure', 'Data': path, 'Log': run.log,
        'Sampling rate': f'{fs:.0f} Hz',
        'Route gain': f'{route_gain_db:.3f} dB (probe blocks within '
                      f'{route.gain_spread_db:.3f} dB)',
        'Speaker calibration': f'{OUTPUT_CAL_DB} dB SPL at 1 Vrms',
        'Microphone': f'{mv_pa:.4g} mV/Pa, {MICROPHONE_GAIN} dB gain',
        'Exposure': f'{p["fl"]:g}–{p["fh"]:g} Hz, seed {p["seed"]}, '
                    f'{p["duration"]:g} s, {p["rise_time"]:g} s ramps',
        # For reading only: the band's transitions and the filter's ripple
        # move the level played a little from the level asked for.
        'Level asked for': f'{p["level"]:g} dB SPL',
        'Level played (steady)': f'{a.steady_level:.2f} dB SPL',
    }
    write_report(run_dir, 'Noise exposure', a.checks, figures, info)
    return SimpleNamespace(checks=a.checks, run=run)


@pytest.fixture
def checks(exposure):
    return exposure.checks


def test_timing(checks):
    checks.assert_passed('engine latency', 'exposure on time')


def test_exposure_played(checks):
    '''
    psi plays the exposure its settings and seed give, at its level.
    '''
    checks.assert_passed('exposure level', 'polarity', 'exposure waveform',
                         'nothing else recorded')


def test_continuous(checks):
    checks.assert_passed('continuous')


def test_runs_to_the_end(checks):
    checks.assert_passed('exposure recorded to the end',
                         'stopped when the exposure ended')


def test_psi_levels(checks):
    '''
    The levels psi saves from the microphone are those of what it recorded.
    '''
    checks.assert_passed('psi levels')


def test_running_averages(checks):
    '''
    The running averages psi shows (what the level of an exposure is read
    from) are those of what the microphone recorded.
    '''
    checks.assert_passed('average overall level', 'average band level')


def test_progress(checks):
    checks.assert_passed('progress')


def test_no_errors_logged(checks):
    checks.assert_passed('no errors logged')
