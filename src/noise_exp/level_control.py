'''
Feedback loop that holds the exposure's level at its target, measured in the
exposure band or overall (at exposure levels, ambient sound adds little to
the overall level).

The exposure's level through the speaker calibration is set by psiaudio, but
the monitor microphone (the ground truth) sits elsewhere in the booth, so it
can read a few dB off target, and the level can drift during an exposure.
This adjusts the exposure's gain from the microphone's band level:

* After the first `window` seconds at full level, a one-off *trim* brings the
  band level to the target (at most `max_trim` dB).
* From then on, a slow integral loop corrects *drift* (at most `max_drift` dB
  on top of the trim), half the remaining error at a time.

Each decision uses only seconds of the recording during which the exposure
was played at the gain the loop last set (see `psiaudio.gain.GainSchedule`).
The output buffers seconds of samples ahead of what is playing, so a change
takes that long to reach the microphone; judging seconds played at an older
gain would correct the same error twice, which is how such loops oscillate.

Runaway is guarded against by:

* bounding the correction (`max_trim`, `max_drift`) and each step
  (`MAX_STEP`), so the loop can never push the level far;
* freezing (holding the gain, and reporting it) when the band level is far
  below target (`LOW_FAULT`, e.g., a microphone unplugged or covered), so a
  failed measurement is never answered by turning the exposure up;
* freezing when the drift correction stays at its limit (`LIMIT_UPDATES`
  decisions in a row), since that means something physical has changed;
* a trip, independent of the loop, that turns the exposure down by the full
  range of the correction and freezes when the level is far above target
  (`TRIP_LEVEL`) for `TRIP_SECONDS` seconds;
* taking the median of the window's 1 s levels, so brief noises (an animal
  vocalizing, the cage rattling) do not move the gain.
'''
import logging
log = logging.getLogger(__name__)

from math import ceil, floor

import numpy as np

from atom.api import Bool, Callable, Float, Typed, set_default
from enaml.core.api import d_

from psiaudio.gain import GainSchedule
from psiaudio.pipeline import coroutine

from psi.controller.api import ContinuousInput


#: Fraction of the remaining error corrected at each decision. Stable for any
#: value below 2 (here, with no delay in the loop); 0.5 halves the error each
#: time and tolerates the level changing at up to 4x the gain's change.
LOOP_GAIN = 0.5

#: Errors smaller than this (dB) are left alone.
DEADBAND = 0.2

#: Largest change (dB) of the drift correction at one decision.
MAX_STEP = 0.5

#: A startup trim larger than this (dB) is reported: the calibration may
#: need redoing.
WARN_TRIM = 3

#: Freeze if the band level is this far (dB) below target.
LOW_FAULT = 10

#: Trip if the band level is this far (dB) above target ...
TRIP_LEVEL = 6

#: ... for this many seconds in a row.
TRIP_SECONDS = 3

#: Freeze if the drift correction is at its limit for this many decisions in
#: a row.
LIMIT_UPDATES = 5

#: Duration (s) of the gain's ramp from one value to the next.
RAMP_TIME = 0.1

#: Time (s) allowed, after the end of a gain's ramp, before the microphone is
#: taken to hear only that gain: the converters' filter delays and the sound's
#: travel time (ms) and the settling of the band filter (tens of ms).
GUARD = 0.25


class LevelController:
    '''
    The decisions of the loop, given the band level it measures.

    The gain (dB) it asks for is `trim + drift`. Call `check_second` with
    each 1 s band level, and `update` with the median of each window of them
    measured at the gain it last asked for. Each returns None when there is
    nothing to do, or a record of what it decided, whose `gain` is the gain
    to apply (None to leave the gain as it is).
    '''
    def __init__(self, target, max_trim=6, max_drift=2):
        self.target = target
        self.max_trim = max_trim
        self.max_drift = max_drift
        #: None until the first window has been measured.
        self.trim = None
        self.drift = 0.0
        self.frozen = False
        self._at_limit = 0
        self._over = 0

    @property
    def gain(self):
        return (self.trim or 0.0) + self.drift

    @property
    def min_gain(self):
        return -(self.max_trim + self.max_drift)

    def _record(self, action, level, message='', gain=None):
        return {
            'action': action,
            'level': level,
            'target': self.target,
            'trim': self.trim if self.trim is not None else 0.0,
            'drift': self.drift,
            'gain': gain,
            'message': message,
        }

    def _freeze(self, level, message, gain=None):
        self.frozen = True
        log.warning('Level control frozen: %s', message)
        return self._record('freeze', level, message, gain)

    def check_second(self, level):
        '''
        Check a 1 s band level against the trip, which acts even when frozen.
        '''
        if level > self.target + TRIP_LEVEL:
            self._over += 1
        else:
            self._over = 0
        if self._over == TRIP_SECONDS:
            gain = self.min_gain
            self.trim = gain
            self.drift = 0.0
            m = (f'band level {level:.1f} dB SPL, more than {TRIP_LEVEL} dB '
                 f'above target for {TRIP_SECONDS} s: exposure turned down '
                 f'{-gain:.1f} dB. Check the speaker and microphone.')
            record = self._freeze(level, m, gain)
            record['action'] = 'trip'
            return record
        return None

    def update(self, level):
        '''
        Decide on the gain from the median band level of a window measured
        at the gain last asked for.
        '''
        if self.frozen:
            return None
        if level < self.target - LOW_FAULT:
            m = (f'band level {level:.1f} dB SPL, more than {LOW_FAULT} dB '
                 'below target: check the microphone. The gain is held.')
            return self._freeze(level, m)

        error = self.target - level
        if self.trim is None:
            wanted = self.gain + error
            self.trim = float(np.clip(wanted, -self.max_trim, self.max_trim))
            message = ''
            if abs(wanted) > self.max_trim:
                message = (f'{wanted:+.1f} dB needed, more than the '
                           f'{self.max_trim} dB allowed: check the '
                           'calibrations.')
                log.warning('Level control trim: %s', message)
            elif abs(self.trim) > WARN_TRIM:
                message = (f'trim {self.trim:+.1f} dB: the speaker '
                           'calibration may need redoing.')
                log.warning('Level control trim: %s', message)
            return self._record('trim', level, message, self.gain)

        if abs(error) <= DEADBAND:
            return self._record('hold', level)

        step = float(np.clip(LOOP_GAIN * error, -MAX_STEP, MAX_STEP))
        wanted = self.drift + step
        drift = float(np.clip(wanted, -self.max_drift, self.max_drift))
        self._at_limit = self._at_limit + 1 if drift != wanted else 0
        if drift == self.drift:
            record = self._record('limit', level)
        else:
            self.drift = drift
            record = self._record('adjust', level, gain=self.gain)
        if self._at_limit >= LIMIT_UPDATES:
            m = (f'drift correction at its {self.max_drift} dB limit for '
                 f'{LIMIT_UPDATES} decisions: check the speaker, microphone '
                 'and animals. The gain is held.')
            return self._freeze(level, m, record['gain'])
        return record


def describe(controller, enabled=True):
    '''
    Short status of the loop for the operator.
    '''
    if not enabled:
        return 'off'
    if controller.trim is None:
        return 'measuring'
    state = 'FROZEN' if controller.frozen else 'holding'
    return f'{controller.gain:+.1f} dB ({state})'


@coroutine
def running_median(n, target):
    '''
    Send `target` the median of each value and the `n - 1` values before it
    (fewer at the start), each at the time of the newest value.

    For plotting the 1 s levels as the loop judges them: it takes the median
    of each window of `n` of them (see `control_level`). This slides by one
    level rather than jumping a window at a time, so it is a running picture
    of the loop's input rather than its exact decisions.
    '''
    n = max(int(round(n)), 1)
    history = None
    while True:
        data = (yield)
        x = np.asarray(data)
        if history is None:
            history = x[..., :0]
        x = np.concatenate((history, x), axis=-1)
        offset = x.shape[-1] - data.shape[-1]
        # A copy of the block keeps its times (`s0`, `fs`).
        result = data.copy()
        for i in range(data.shape[-1]):
            j = offset + i + 1
            result[..., i] = np.median(x[..., max(j - n, 0):j], axis=-1)
        history = x[..., x.shape[-1] - (n - 1):]
        target(result)


@coroutine
def control_level(schedule, controller, sens, start, end, window, report,
                  target):
    '''
    Bin the band signal into 1 s levels, and pass the controller each window
    of `window` of them measured at the gain it last asked for.

    The input's samples are taken to be on the same clock as the output's
    (both count from the start of acquisition), so input second `k` heard
    output samples from `(k - GUARD) * fs` to `(k + 1) * fs` (with the output's
    fs). Only seconds within `start` to `end` (s, the exposure at full level)
    count.

    Parameters
    ----------
    schedule : GainSchedule
        The exposure output's gain.
    controller : LevelController
    sens : float
        Sensitivity of the band signal (dB SPL re its units), as `SPL` uses.
    start, end : float
        Steady state of the exposure (s).
    window : int
        Number of 1 s levels per decision.
    report : callable
        Called with each decision's record (with its `time`, s).
    target : callable
        Next step of the pipeline (the band signal is passed on unchanged).
    '''
    bin_k = None
    bin_sum = 0.0
    bin_n = 0
    levels = []
    while True:
        data = (yield)
        target(data)
        n_bin = int(round(data.fs))
        x = np.asarray(data).reshape(-1, data.shape[-1])[0]
        s0 = data.s0
        i = 0
        while i < x.shape[-1]:
            k = (s0 + i) // n_bin
            take = min(x.shape[-1] - i, (k + 1) * n_bin - (s0 + i))
            if k != bin_k:
                bin_k, bin_sum, bin_n = k, 0.0, 0
            bin_sum += float(np.sum(x[i:i + take] ** 2))
            bin_n += take
            i += take
            if bin_n < n_bin:
                continue

            # A full second of the recording.
            t0, t1 = k * n_bin / data.fs, (k + 1) * n_bin / data.fs
            bin_k = None
            if t0 < start or t1 > end:
                continue
            with np.errstate(divide='ignore'):
                level = 10 * np.log10(bin_sum / n_bin) + sens

            record = controller.check_second(level)
            if record is not None:
                schedule.set(record['gain'])
                report(dict(record, time=t1))
            if controller.frozen:
                continue

            # Count only seconds played entirely at the gain last asked for.
            gain = schedule.constant_over(floor((t0 - GUARD) * schedule.fs),
                                          ceil(t1 * schedule.fs))
            if gain is None or gain != schedule.gain_db:
                levels = []
                continue
            levels.append(level)
            if len(levels) < window:
                continue

            record = controller.update(float(np.median(levels)))
            levels = []
            if record is None:
                continue
            if record['gain'] is not None \
                    and record['gain'] != schedule.gain_db:
                schedule.set(record['gain'])
            report(dict(record, time=t1))


class LevelControl(ContinuousInput):
    '''
    Holds the exposure's level at its target (see the module), measured in
    the signal it is attached to: the band-filtered microphone signal, or the
    overall one.

    A paradigm can attach one to each and select one: only the selected one
    touches the exposure's gain or reports.
    '''
    #: The exposure output, whose gain is controlled.
    exposure = d_(Typed(object))

    #: Whether this is the level control in use (of those attached to
    #: different signals).
    selected = d_(Bool(True))

    #: Whether to control the level. When False, the output has no gain.
    enabled = d_(Bool(True))

    #: Target band level (dB SPL).
    target_level = d_(Float())

    #: Seconds of the band level per decision.
    window = d_(Float(10))

    max_trim = d_(Float(6))
    max_drift = d_(Float(2))

    #: Steady state of the exposure (s, experiment time).
    start = d_(Float())
    end = d_(Float())

    #: Called, from the acquisition thread, with each decision's record and
    #: the status text; should hand them to the GUI thread.
    report = d_(Callable())

    force_active = set_default(True)

    controller = Typed(LevelController)

    def configure_callback(self):
        cb = super().configure_callback()
        if not self.selected:
            return cb
        if not self.enabled:
            self.exposure.gain = None
            self.report(None, describe(None, enabled=False))
            return cb
        self.controller = LevelController(self.target_level, self.max_trim,
                                          self.max_drift)
        schedule = GainSchedule(self.exposure.fs, ramp_time=RAMP_TIME)
        self.exposure.gain = schedule
        controller = self.controller
        sens = self.calibration.get_sens(1e3)

        def report(record):
            self.report(record, describe(controller))

        self.report(None, describe(controller))
        return control_level(schedule, controller, sens, self.start,
                             self.end, int(round(self.window)), report,
                             cb).send
