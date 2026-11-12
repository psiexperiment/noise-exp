'''
Checks of a noise exposure recorded through the loopback.

The exposure is one long burst of frozen bandlimited noise (a
`BandlimitedFIRNoise` in a `Cos2Envelope`) that starts `EXPOSURE_START_DELAY`
s into the experiment, and the monitor microphone hears it through the
loopback. So the exposure is regenerated here with psiaudio from the run's
settings and seed, fit to what the microphone recorded, and then pushed
through the same filters and level calculations as the paradigm's monitor
chain (`noise_exposure.enaml`) to check every level psi reported: the 1 s
levels it saved (`noise_level`), and the running averages and progress it
showed in its status area.

The microphone's calibration is chosen (see `runner.microphone_mv_pa`) so
that it reads back, in dB SPL, the level the speaker's calibration says was
played.
'''
from dataclasses import dataclass
import re

import enaml
import numpy as np
from scipy import signal

from psiaudio import stim
from psi.loopback.fit import db_ratio, find_latency, fit_stimuli, gain_db
from psi.loopback.report import Checks

with enaml.imports():
    from noise_exp.paradigms.noise_exposure import EXPOSURE_START_DELAY


#: Largest acceptable error in level, in dB.
LEVEL_TOLERANCE = 0.1

#: The status labels show one decimal place.
LABEL_TOLERANCE = 0.1

#: How far below the exposure whatever it leaves unexplained must be, over
#: the whole recording and in each block (`CONTINUITY_BLOCK`).
RESIDUAL_LIMIT = -60
BLOCK_RESIDUAL_LIMIT = -50

#: Blocks (s) the recording is compared with the exposure in, to find
#: dropped, repeated or zeroed buffers.
CONTINUITY_BLOCK = 0.05

#: How far either side of where it should be to look for the exposure (s),
#: once the latency has been found.
FIT_SEARCH = 0.002

#: 1 s levels more than this far below the steady exposure (dB) are left out
#: of the level check: they are (mostly) the silence before and after it.
LEVEL_RANGE = 20

#: Longest the experiment may run on once the exposure has finished (s).
MAX_STOP_DELAY = 3

#: The paradigm's monitor chain (`noise_exposure.enaml`): a high-pass, then
#: a band-pass around the exposure band, levels over 1 s blocks, and running
#: averages of the exposure at full level (between its ramps).
HIGHPASS = {'N': 2, 'Wn': 100, 'btype': 'highpass'}
BAND_ORDER = 4
BAND_MARGIN = 0.95
RMS_DURATION = 1

#: Status items the paradigm shows the running averages and progress in.
OVERALL_LABEL = 'Average overall level (dB SPL)'
BAND_LABEL = 'Average level in band (dB SPL)'
PROGRESS = 'Exposure status'


@dataclass
class Analysis:
    checks: Checks
    fs: float
    #: The recording, what it should be, and the fit of one to the other.
    recorded: np.ndarray
    expected: np.ndarray
    fit: object
    #: Start of each continuity block (s) and its residual re the exposure.
    block_times: np.ndarray
    block_residual_db: np.ndarray
    #: The 1 s levels psi saved and what they should be (dB SPL), and the
    #: blocks compared.
    psi_levels: np.ndarray
    expected_levels: np.ndarray
    level_mask: np.ndarray
    #: Running averages psi showed and what they should be (dB SPL).
    averages: dict
    #: Steady-state level of the exposure in the recording (dB SPL).
    steady_level: float


def exposure_template(fs, p, calibration):
    '''
    The exposure psi plays for the settings in `p` (see
    `test_exposure.PARAMETERS`), from its first sample to its last.
    '''
    noise = stim.BandlimitedFIRNoiseFactory(
        fs, p['fl'], p['fh'], p['level'], seed=p['seed'],
        equalize=p['equalize'], max_correction=p['max_correction'],
        calibration=calibration)
    factory = stim.Cos2EnvelopeFactory(fs, p['duration'], p['rise_time'],
                                       noise)
    return factory.get_samples_remaining()


def monitor_filters(fs, p):
    '''
    The paradigm's high-pass and band-pass filters, as psi designs them
    (`psiaudio.pipeline.iirfilter`).
    '''
    highpass = signal.iirfilter(fs=fs, ftype='butter', **HIGHPASS)
    band = (p['fl'] * BAND_MARGIN, p['fh'] / BAND_MARGIN)
    bandpass = signal.iirfilter(BAND_ORDER, band, btype='bandpass',
                                ftype='butter', fs=fs)
    return highpass, bandpass


def block_levels(x, fs, sens, duration=RMS_DURATION):
    '''
    Level (dB SPL) of each whole `duration` block of `x`, as psi's `RMS`
    and `SPL` inputs compute it.
    '''
    n = int(round(fs * duration))
    k = len(x) // n
    rms = np.sqrt(np.mean(x[:k * n].reshape(k, n) ** 2, axis=-1))
    with np.errstate(divide='ignore'):
        return 20 * np.log10(rms) + sens


def running_level(x, fs, sens, start, end):
    '''
    Level (dB SPL) of `x` from `start` to `end` s, which is what the
    paradigm's `running_rms` shows once all of `x` has been through it.
    '''
    x = x[round(start * fs):round(end * fs)]
    return 20 * np.log10(np.sqrt(np.mean(x ** 2))) + sens


def last_status(status):
    '''
    The last value recorded for each (status item, attribute).
    '''
    last = {}
    for line in status:
        last[line['item'], line['attr']] = line['value']
    return last


def label_level(text):
    '''
    The level in a status label ('105.3 dB SPL'), or None if it shows none.
    '''
    match = re.match(r'\s*(-?[\d.]+|-?inf|nan) dB SPL', text or '')
    return float(match.group(1)) if match else None


def analyze_exposure(x, fs, psi_levels, status, p, route_gain_db,
                     input_dbfs, microphone_gain, speaker_calibration,
                     microphone_calibration, latency, engine):
    '''
    Parameters
    ----------
    x : array
        What the monitor microphone recorded (V, as psi saved it).
    psi_levels : array
        The 1 s levels psi saved (`noise_level`, dB SPL).
    status : list of dict
        What the status area showed (see `status_recorder.enaml`).
    p : dict
        The exposure's settings (see `test_exposure.PARAMETERS`).
    route_gain_db : float
        Gain of the route from the speaker to the microphone input.
    input_dbfs, microphone_gain : float
        Full-scale level of the input, and the gain set on the microphone.
    speaker_calibration, microphone_calibration : psiaudio calibrations
        What the exposure ran with.
    latency : int
        Latency measured just before the run.
    engine : dict
        The sound card engine's settings as the run recorded them.
    '''
    checks = Checks()
    sens = microphone_calibration.get_sens(1e3)
    template = exposure_template(fs, p, speaker_calibration)
    gain = 10 ** ((route_gain_db + input_dbfs - microphone_gain) / 20)
    onset = int(round(EXPOSURE_START_DELAY * fs))
    end = onset + len(template)

    checks.add('engine latency', engine['latency_samples'] == latency,
               f'latency_samples {engine["latency_samples"]} at '
               f'{engine["fs"]} Hz, blocksize {engine["blocksize"]}',
               f'{latency} (measured just before the run)')

    stop_delay = (len(x) - end) / fs
    checks.add('exposure recorded to the end', stop_delay >= 0,
               f'recording ends {stop_delay * 1e3:.0f} ms after the exposure',
               '≥ 0 ms',
               'The experiment stops when the exposure ends (exposure_end). '
               'If it stops before the end of the exposure has come back '
               'through the sound card, the end was not recorded (or not '
               'played).')
    checks.add('stopped when the exposure ended', stop_delay <= MAX_STOP_DELAY,
               f'{stop_delay:.2f} s after', f'≤ {MAX_STOP_DELAY} s')

    # Fit as much of the exposure as was recorded, so a recording cut short
    # (checked above) doesn't fail every other check too. `fit_stimuli`
    # needs its search margin past the end of the template.
    delay = find_latency(x, fs, [EXPOSURE_START_DELAY], [template])
    margin = int(FIT_SEARCH * fs)
    n_fit = max(0, min(len(template), len(x) - onset - delay - margin))
    fit = fit_stimuli(x, fs, [EXPOSURE_START_DELAY], [template[:n_fit]],
                      latency=delay, search=FIT_SEARCH)
    e = fit.epochs.iloc[0]
    found = not np.isnan(e.gain)
    lag = delay + e.lag if found else np.nan
    checks.add('exposure on time', found and abs(lag) <= 1,
               f'{lag:.0f} samples ({lag / fs * 1e3:.2f} ms)'
               if found else 'not found', '0 ± 1 samples',
               f'Start of the exposure in the recording re '
               f'{EXPOSURE_START_DELAY} s, when psi starts it. Nonzero means '
               f'the engine\'s latency_samples is wrong, or the exposure '
               f'started late.')
    level_error = gain_db(e.gain) - gain_db(gain) if found else np.nan
    checks.add('exposure level', abs(level_error) <= LEVEL_TOLERANCE,
               f'{level_error:+.3f} dB', f'± {LEVEL_TOLERANCE} dB',
               'Level of the exposure in the recording re the level its '
               'settings and the speaker calibration ask for, through the '
               'route.')
    checks.add('polarity', found and e.gain > 0,
               'inverted' if found and e.gain < 0 else 'as played', 'as played')
    checks.add('exposure waveform', e.residual_db <= RESIDUAL_LIMIT,
               f'{e.residual_db:.1f} dB', f'≤ {RESIDUAL_LIMIT} dB',
               'What the regenerated exposure leaves unexplained in the '
               'recording, re the recording. Above the limit, psi played '
               'other noise than its settings and seed give.')
    # Outside the exposure, as found in the recording, there should be
    # nothing at all (a digital loopback is silent).
    first = onset + (int(lag) if found else 0)
    outside = np.concatenate([x[:max(first, 0)], x[first + len(template):]])
    with np.errstate(divide='ignore'):
        outside_db = 10 * np.log10(np.sum(outside ** 2)
                                   / np.sum((gain * template) ** 2))
    checks.add('nothing else recorded', outside_db <= RESIDUAL_LIMIT,
               f'{outside_db:.1f} dB', f'≤ {RESIDUAL_LIMIT} dB',
               'Energy in the recording before and after the exposure, re '
               'the exposure.')

    # What the recording should be: the exposure, through the route, where
    # psi says it played it.
    expected = np.zeros_like(x)
    n = max(0, min(len(template), len(x) - onset))
    expected[onset:onset + n] = template[:n] * gain

    # Dropped, repeated or zeroed buffers, block by block over the fitted
    # exposure (the quietest ends of the ramps are left out).
    block = int(round(CONTINUITY_BLOCK * fs))
    starts = np.arange(first, first + n_fit - block + 1, block)
    if found and len(starts):
        error = np.stack([x[s:s + block] - fit.reconstructed[s:s + block]
                          for s in starts])
        fitted = np.stack([fit.reconstructed[s:s + block] for s in starts])
        block_db = db_ratio(error, fitted)
        level = 20 * np.log10(np.sqrt(np.mean(fitted ** 2, axis=-1)))
        loud = level > level.max() - LEVEL_RANGE
        worst = np.max(block_db[loud])
        n_bad = int(np.sum(block_db[loud] > BLOCK_RESIDUAL_LIMIT))
    else:
        starts, block_db = np.array([]), np.array([])
        loud = np.array([], dtype=bool)
        worst, n_bad = np.nan, None
    checks.add('continuous', n_bad == 0,
               f'{n_bad} of {int(np.sum(loud))} blocks bad, worst '
               f'{worst:.1f} dB' if n_bad is not None
               else 'exposure not found',
               f'≤ {BLOCK_RESIDUAL_LIMIT} dB in every '
               f'{CONTINUITY_BLOCK * 1e3:.0f} ms block',
               'A dropped, repeated or zeroed buffer leaves the exposure '
               'unexplained in the blocks it touches.')

    # The paradigm's monitor chain, applied to what the recording should be.
    highpass, bandpass = monitor_filters(fs, p)
    filtered = signal.lfilter(*highpass, expected)
    band_filtered = signal.lfilter(*bandpass, filtered)

    expected_levels = block_levels(filtered, fs, sens)
    k = min(len(expected_levels), len(psi_levels))
    expected_levels = expected_levels[:k]
    psi_levels = np.asarray(psi_levels[:k], dtype=float)
    steady_level = np.max(expected_levels) if k else np.nan
    level_mask = expected_levels > steady_level - LEVEL_RANGE
    if np.any(level_mask):
        error = psi_levels[level_mask] - expected_levels[level_mask]
        worst = np.max(np.abs(error))
    else:
        worst = np.nan
    checks.add('psi levels', worst <= LEVEL_TOLERANCE,
               f'worst 1 s level off by {worst:.3f} dB over '
               f'{int(np.sum(level_mask))} s', f'± {LEVEL_TOLERANCE} dB',
               'The levels psi saved (noise_level) re the levels of the '
               'exposure through the route, high-passed as psi does.')

    # The averages are of the exposure at full level, between its ramps.
    steady_start = EXPOSURE_START_DELAY + p['rise_time']
    steady_end = EXPOSURE_START_DELAY + p['duration'] - p['rise_time']
    last = last_status(status)
    averages = {}
    for name, label, y in (('overall', OVERALL_LABEL, filtered),
                           ('band', BAND_LABEL, band_filtered)):
        shown = label_level(last.get((label, 'text')))
        should = running_level(y, fs, sens, steady_start, steady_end)
        averages[name] = (shown, should)
        ok = shown is not None and abs(shown - should) <= LABEL_TOLERANCE
        checks.add(f'average {name} level', ok,
                   f'shows {shown} dB SPL' if shown is not None
                   else 'shows nothing',
                   f'{should:.2f} ± {LABEL_TOLERANCE} dB SPL',
                   f'What "{label}" showed when the experiment ended, re the '
                   f'level of the exposure at full level, from '
                   f'{steady_start:g} s (the end of its onset ramp) to '
                   f'{steady_end:g} s (the start of its offset ramp).')

    # `configure_experiment` sizes the bar to the end of the exposure (in
    # samples at the output's rate, the same as the microphone's here), and
    # `update_progress` adds every block the microphone records.
    value = last.get((PROGRESS, 'value'))
    maximum = last.get((PROGRESS, 'maximum'))
    expected_maximum = int(round((EXPOSURE_START_DELAY + p['duration']) * fs))
    checks.add('progress', value is not None and value == maximum
               and maximum == expected_maximum,
               f'{value} of {maximum}',
               f'{expected_maximum} of {expected_maximum}',
               'The progress bar should be full when the exposure ends: it '
               'counts the samples the microphone records, up to the end '
               'of the exposure.')

    return Analysis(checks, fs, x, expected, fit, starts / fs, block_db,
                    psi_levels, expected_levels, level_mask, averages,
                    steady_level)
