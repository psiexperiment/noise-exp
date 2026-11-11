'''
Run the noise exposure through the Fireface in a subprocess, configured the
way the noise-exp launcher (`src/noise_exp/gui.enaml`) would configure it.
'''
from pathlib import Path

import pytest

from psi.loopback import rig as loopback_rig
from psi.loopback import runner as loopback_runner
from psi.loopback.pytest_plugin import require_routes  # noqa: F401

from rig import INPUT_DBFS, MICROPHONE, RIG, SPEAKER


HERE = Path(__file__).parent

PARADIGM = 'noise_exposure'
PARADIGM_MODULES = ('noise_exp.paradigms',)

#: The speaker's calibration: 1 Vrms is this many dB SPL, at every
#: frequency.
OUTPUT_CAL_DB = 130

#: Gain set on the microphone amplifier (dB). Not 0, so the run checks
#: that psi takes it out of what it records.
MICROPHONE_GAIN = 20

#: Records what the status area showed (see the module).
STATUS_RECORDER = 'status_recorder.StatusRecorder'


def microphone_mv_pa(route_gain_db, gain=MICROPHONE_GAIN, cal_db=OUTPUT_CAL_DB,
                     input_dbfs=INPUT_DBFS):
    '''
    Sensitivity (mV/Pa) that makes the microphone read back, in dB SPL,
    the level the speaker's calibration says was played.

    The speaker plays `x` V for a level of `20 log10(x) + cal_db` dB SPL.
    Through a route of `route_gain_db`, psi records `x` scaled by
    `route_gain_db + input_dbfs - gain` dB (see `total_gain` of psi's
    `SoundcardHardwareAIChannel`), so the microphone has to produce that
    many volts per `10 ** (cal_db / 20) * 20e-6` Pa.
    '''
    v = 10 ** ((route_gain_db + input_dbfs - gain - cal_db) / 20)
    return float(1e3 * v / 20e-6)


def exposure_env(mv_pa, gain=MICROPHONE_GAIN):
    '''
    The environment the launcher sets when it starts an exposure, with a
    nominal (flat) speaker and microphone calibration.
    '''
    key = MICROPHONE.upper()
    return {
        'CFTSCAL_IO': RIG.io_manifest,
        'CFTSCAL_MICROPHONE': MICROPHONE,
        f'CFTSCAL_MICROPHONE_{key}_GAIN': str(gain),
        f'CFTSCAL_MICROPHONE_{key}':
            f'cftscal.objects.NominalInputCalibration::{float(mv_pa)!r}',
        'CFTSCAL_SPEAKER': SPEAKER,
        f'CFTSCAL_SPEAKER_{SPEAKER.upper()}':
            f'cftscal.objects.NominalSpeakerCalibration::{OUTPUT_CAL_DB}',
    }


def run_exposure(path, settings, env, status_path, timeout):
    '''
    Run the exposure until it ends on its own, saving its data to `path`
    and what it showed in its status area to `status_path`.
    '''
    # Without video: it is optional, and the runner enables no optional
    # plugins.
    manifests = {STATUS_RECORDER: {'path': str(status_path)}}
    return loopback_runner.run_paradigm(
        RIG, PARADIGM, path, settings, modules=PARADIGM_MODULES, env=env,
        manifests=manifests, timeout=timeout, cwd=HERE)


def measure_run_latency(output, input):
    try:
        return loopback_rig.measure_run_latency(RIG, output, input)
    except RuntimeError as e:
        pytest.fail(str(e))
