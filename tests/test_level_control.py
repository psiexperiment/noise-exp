'''
Tests of the feedback loop that holds the exposure's band level at target
(`noise_exp.level_control`).
'''
import numpy as np
import pytest

from psiaudio.gain import GainSchedule
from psiaudio.pipeline import PipelineData

from noise_exp import level_control as lc
from noise_exp.level_control import LevelController, control_level


TARGET = 100


# -------- decisions --------

class TestTrim:

    def test_first_window_trims_to_target(self):
        c = LevelController(TARGET)
        record = c.update(97.5)
        assert record['action'] == 'trim'
        assert record['gain'] == pytest.approx(2.5)
        assert c.gain == pytest.approx(2.5)
        assert record['message'] == ''

    def test_large_trim_reported(self):
        c = LevelController(TARGET, max_trim=6)
        record = c.update(TARGET + 4)
        assert record['gain'] == pytest.approx(-4)
        assert 'calibration' in record['message']

    def test_trim_bounded(self):
        c = LevelController(TARGET, max_trim=6)
        record = c.update(TARGET - 8)
        assert record['gain'] == 6
        assert 'more than the 6 dB allowed' in record['message']


class TestInitialGain:
    '''
    The operator's trim: the exposure starts at it, and the loop's trim and
    drift are about it.
    '''

    def test_gain_starts_at_initial(self):
        c = LevelController(TARGET, initial=1.5)
        assert c.gain == 1.5

    def test_trim_is_about_initial(self):
        c = LevelController(TARGET, initial=1.5)
        record = c.update(TARGET + 0.5)
        assert c.trim == pytest.approx(-0.5)
        assert record['gain'] == pytest.approx(1.0)
        assert record['initial'] == 1.5

    def test_trim_bounded_about_initial(self):
        c = LevelController(TARGET, max_trim=6, initial=-4)
        record = c.update(TARGET - 8)
        assert c.trim == 6
        assert record['gain'] == pytest.approx(2)

    def test_trip_about_initial(self):
        c = LevelController(TARGET, max_trim=6, max_drift=2, initial=1)
        c.update(TARGET)
        loud = TARGET + lc.TRIP_LEVEL + 1
        for _ in range(lc.TRIP_SECONDS):
            record = c.check_second(loud)
        assert record['action'] == 'trip'
        assert record['gain'] == pytest.approx(-7)
        assert c.gain == pytest.approx(-7)

    def test_describe(self):
        assert lc.describe(LevelController(TARGET)) == 'measuring'
        assert lc.describe(LevelController(TARGET, initial=1.5)) == \
            '+1.5 dB (measuring)'


class TestDrift:

    def trimmed(self, **kw):
        c = LevelController(TARGET, **kw)
        c.update(TARGET)
        return c

    def test_deadband(self):
        c = self.trimmed()
        record = c.update(TARGET - 0.9 * lc.DEADBAND)
        assert record['action'] == 'hold'
        assert record['gain'] is None
        assert c.gain == 0

    def test_corrects_part_of_error(self):
        c = self.trimmed()
        record = c.update(TARGET - 0.6)
        assert record['action'] == 'adjust'
        assert record['gain'] == pytest.approx(lc.LOOP_GAIN * 0.6)

    def test_step_bounded(self):
        c = self.trimmed()
        record = c.update(TARGET - 5)
        assert record['gain'] == pytest.approx(lc.MAX_STEP)

    def test_drift_bounded_then_frozen(self):
        '''
        A correction that stays at its limit means something physical has
        changed: the loop stops and says so rather than masking it.
        '''
        c = self.trimmed(max_drift=1)
        records = [c.update(TARGET - 5) for _ in range(20)]
        records = [r for r in records if r is not None]
        assert c.drift == 1
        assert c.frozen
        assert records[-1]['action'] == 'freeze'
        assert 'limit' in records[-1]['message']
        assert all(r['gain'] is None or r['gain'] <= 1 for r in records)


class TestFaults:

    def test_low_level_freezes_without_raising_gain(self):
        '''
        A band level far below target is taken to be a failed measurement
        (e.g., the microphone unplugged), never answered by turning up.
        '''
        c = LevelController(TARGET)
        c.update(TARGET)
        record = c.update(-np.inf)
        assert record['action'] == 'freeze'
        assert record['gain'] is None
        assert c.frozen
        assert c.update(TARGET - 3) is None
        assert c.gain == 0

    def test_low_level_before_trim(self):
        c = LevelController(TARGET)
        record = c.update(TARGET - lc.LOW_FAULT - 1)
        assert record['action'] == 'freeze'
        assert c.trim is None

    def test_trip(self):
        c = LevelController(TARGET, max_trim=6, max_drift=2)
        c.update(TARGET)
        loud = TARGET + lc.TRIP_LEVEL + 1
        for _ in range(lc.TRIP_SECONDS - 1):
            assert c.check_second(loud) is None
        record = c.check_second(loud)
        assert record['action'] == 'trip'
        assert record['gain'] == -8
        assert c.frozen

    def test_trip_needs_consecutive_seconds(self):
        c = LevelController(TARGET)
        loud = TARGET + lc.TRIP_LEVEL + 1
        for _ in range(10):
            for _ in range(lc.TRIP_SECONDS - 1):
                assert c.check_second(loud) is None
            assert c.check_second(TARGET) is None
        assert not c.frozen


# -------- the loop, closed through a simulated booth --------

FS = 100
BLOCK = FS // 10


class Loop:
    '''
    A run of `run_loop`: the schedule, the controller, its decisions, and
    what was played and heard.
    '''
    def __init__(self, schedule, controller, records, plant_db, mic, start):
        self.schedule = schedule
        self.controller = controller
        self.records = records
        self.start = start
        n = len(mic)
        #: Time of each sample (s).
        self.t = np.arange(n) / FS
        #: The booth's offset (dB) at each sample.
        self.plant_db = plant_db
        #: The gain (dB) each sample was played at.
        self.gain_db = schedule.gain_at(np.arange(n))
        #: Level (dB SPL) heard in each second, as the loop measures it.
        seconds = n // FS
        power = np.mean(mic[:seconds * FS].reshape(seconds, FS) ** 2, axis=1)
        with np.errstate(divide='ignore'):
            self.levels = 10 * np.log10(power) + TARGET
        self.level_t = np.arange(seconds) + 1


def run_loop(plant_db, seconds=300, lookahead=5, window=10, start=2,
             block=BLOCK, rise_time=0, initial=0, **controller_kw):
    '''
    Run the loop with an output that renders `lookahead` s ahead of what the
    microphone hears (as the hardware buffer does).

    The exposure is a constant 1 (so each second's level is exact), after a
    cos² onset ramp of `rise_time` s ending at `start`, heard at TARGET dB
    SPL plus `plant_db(t)` (dB, the booth's offset at time t, s) times the
    gain the loop set when the samples were rendered, starting at `initial`.
    '''
    schedule = GainSchedule(FS, ramp_time=lc.RAMP_TIME, gain_db=initial)
    controller = LevelController(TARGET, initial=initial, **controller_kw)
    records = []
    sens = TARGET
    pipeline = control_level(schedule, controller, sens, start, seconds,
                             window, records.append, lambda data: None,
                             rise_time=rise_time)
    n = seconds * FS
    t = np.arange(n) / FS
    if rise_time > 0:
        frac = np.clip((t - (start - rise_time)) / rise_time, 0, 1)
        exposure = np.sin(np.pi / 2 * frac) ** 2
    else:
        exposure = np.ones(n)
    played = np.zeros(n)
    plant = plant_db(t)
    mic = np.zeros(n)
    rendered = 0
    for i in range(0, n, block):
        while rendered < min(n, i + lookahead * FS + block):
            s = slice(rendered, rendered + block)
            played[s] = schedule.apply(rendered, exposure[s])
            rendered += block
        s = slice(i, i + block)
        mic[s] = played[s] * 10 ** (plant[s] / 20)
        pipeline.send(PipelineData(mic[s], fs=FS, s0=i))
    return Loop(schedule, controller, records, plant, mic, start)


def actions(records):
    return [r['action'] for r in records]


ACTION_STYLE = {
    'trim': ('tab:purple', 'D'),
    'adjust': ('tab:blue', 'o'),
    'hold': ('0.6', '.'),
    'limit': ('tab:orange', 's'),
    'freeze': ('tab:red', 'X'),
    'trip': ('tab:red', 'v'),
}


def plot_loop(loop, title, minutes=False):
    '''
    Level heard, against what it would have been with no control; the gain
    as played, against the gain that would cancel the booth's offset; and
    each decision, at the time it was made.
    '''
    import matplotlib.pyplot as plt
    scale, unit = (60, 'min') if minutes else (1, 's')
    figure, (ax_level, ax_gain) = plt.subplots(
        2, 1, figsize=(10, 6.5), sharex=True, constrained_layout=True)

    ax_level.axhspan(TARGET - lc.DEADBAND, TARGET + lc.DEADBAND,
                     color='tab:green', alpha=0.15, lw=0,
                     label=f'target ± {lc.DEADBAND} dB (deadband)')
    ax_level.plot(loop.t / scale, TARGET + loop.plant_db, color='tab:orange',
                  ls='--', lw=1, label='without control')
    ax_level.plot(loop.level_t / scale, loop.levels, '.', ms=2, color='k',
                  label='heard (1 s levels)')
    ax_level.set_ylabel('Level (dB SPL)')
    finite = loop.levels[np.isfinite(loop.levels)]
    lo = min(finite.min(), (TARGET + loop.plant_db).min()) - 0.5
    hi = max(finite.max(), (TARGET + loop.plant_db).max()) + 0.5
    ax_level.set_ylim(max(lo, TARGET - 12), min(hi, TARGET + 12))

    ax_gain.plot(loop.t / scale, -loop.plant_db, color='tab:orange', ls='--',
                 lw=1, label='gain that cancels the offset')
    ax_gain.plot(loop.t / scale, loop.gain_db, color='tab:blue',
                 label='gain as played')
    ax_gain.set_ylabel('Gain (dB)')
    ax_gain.set_xlabel(f'Time ({unit})')
    # Scaled to the gain and the booth's usual offset, not brief noises.
    finite = -loop.plant_db[np.isfinite(loop.plant_db)]
    lo = min(loop.gain_db.min(), np.percentile(finite, 1)) - 0.5
    hi = max(loop.gain_db.max(), np.percentile(finite, 99)) + 0.5
    ax_gain.set_ylim(lo, hi)

    for ax in (ax_level, ax_gain):
        ax.axvspan(0, loop.start / scale, color='0.9', lw=0)
    shown = set()
    for r in loop.records:
        color, marker = ACTION_STYLE[r['action']]
        label = None if r['action'] in shown else r['action']
        shown.add(r['action'])
        ax_level.plot(r['time'] / scale, r['level'], marker, color=color,
                      ms=6, mec='w', mew=0.5, label=label)
        if r['gain'] is not None:
            ax_gain.plot(r['time'] / scale, r['gain'], marker, color=color,
                         ms=6, mec='w', mew=0.5)

    ax_level.legend(loc='upper right', fontsize=8, ncol=2)
    ax_gain.legend(loc='upper right', fontsize=8)
    ax_level.set_title(f'{title}\nMarkers: each decision (median of the '
                       'window, and the gain asked for) when it was made; '
                       'the gain takes effect after the output buffer.',
                       fontsize=9)
    return figure


@pytest.mark.parametrize('offset', [-2.5, 2.5])
def test_trims_offset_once(offset, plot):
    '''
    A constant offset is corrected by the startup trim, once: the seconds
    still playing at the old gain (5 s of buffer) are not judged again.
    '''
    loop = run_loop(lambda t: np.full_like(t, offset))
    if plot.enabled:
        plot(plot_loop(loop, f'Constant {offset:+} dB offset'))
    assert actions(loop.records)[0] == 'trim'
    assert set(actions(loop.records[1:])) == {'hold'}
    assert loop.controller.gain == pytest.approx(-offset)
    assert len(loop.schedule.changes) == 1


def test_follows_drift_without_overshoot(plot):
    '''
    A 1 dB drop partway through is corrected in shrinking steps, ending
    within the deadband, never past the target.
    '''
    def plant(t):
        return np.where(t < 100, 0.0, -1.0)
    loop = run_loop(plant)
    if plot.enabled:
        plot(plot_loop(loop, 'Step of -1 dB at 100 s'))
    adjusts = [r for r in loop.records if r['action'] == 'adjust']
    assert 1 <= len(adjusts) <= 4
    gains = [r['gain'] for r in adjusts]
    assert np.all(np.diff(gains) > 0)
    assert all(g <= 1 for g in gains)
    assert 1 - loop.controller.gain <= lc.DEADBAND
    assert not loop.controller.frozen


def slow_drift(seed=0):
    '''
    A booth over a 2 h exposure: the level reads 2.5 dB high at the start
    (the calibration's offset), the speaker loses 1.5 dB as it warms up
    (time constant 15 min), the level wanders ±0.3 dB (period 40 min), each
    second's level varies by 0.1 dB (SD), and the animals make a dozen
    1-2 s noises 8 dB above the exposure.
    '''
    rng = np.random.default_rng(seed)
    seconds = 2 * 3600
    jitter = rng.normal(scale=0.1, size=seconds + 1)
    bursts = np.zeros(seconds + 1)
    for s in rng.choice(np.arange(60, seconds - 2), size=12, replace=False):
        bursts[s:s + rng.integers(1, 3)] = 8

    def plant(t):
        drift = 2.5 - 1.5 * (1 - np.exp(-t / 900)) \
            + 0.3 * np.sin(2 * np.pi * t / 2400)
        s = t.astype(int)
        return drift + jitter[s] + bursts[s]
    return plant, seconds


def test_follows_slow_drift(plot):
    '''
    Over a 2 h exposure with a warming speaker, a wandering level, noisy
    seconds and brief animal noises, the trim removes the starting offset
    and the drift loop keeps the level within about the deadband of target,
    without freezing, tripping or chasing the animal noises.
    '''
    plant, seconds = slow_drift()
    loop = run_loop(plant, seconds=seconds, block=FS)
    if plot.enabled:
        plot(plot_loop(loop, 'Slow drift over a 2 h exposure', minutes=True))
        early = (loop.t < 300)
        zoom = Loop.__new__(Loop)
        zoom.__dict__.update(loop.__dict__)
        zoom.t, zoom.plant_db, zoom.gain_db = \
            loop.t[early], loop.plant_db[early], loop.gain_db[early]
        keep = loop.level_t <= 300
        zoom.levels, zoom.level_t = loop.levels[keep], loop.level_t[keep]
        zoom.records = [r for r in loop.records if r['time'] <= 300]
        plot(plot_loop(zoom, 'Slow drift: the first 5 min'), 'start')

    assert actions(loop.records)[0] == 'trim'
    assert not loop.controller.frozen
    assert 'trip' not in actions(loop.records)

    # The level heard, apart from the jitter and noises, after the trim.
    t = loop.t[::FS]
    steady = t > 60
    smooth = 2.5 - 1.5 * (1 - np.exp(-t / 900)) \
        + 0.3 * np.sin(2 * np.pi * t / 2400)
    error = smooth + loop.gain_db[::FS]
    assert np.max(np.abs(error[steady])) < 0.5
    assert np.sqrt(np.mean(error[steady] ** 2)) < 0.25
    # Each change is small after the trim.
    gains = [r['gain'] for r in loop.records[1:] if r['gain'] is not None]
    assert np.all(np.abs(np.diff(gains)) <= lc.MAX_STEP + 1e-9)


def test_drift_beyond_limit_freezes(plot):
    '''
    A speaker that keeps losing level is followed up to `max_drift`, then
    the loop freezes and says so rather than turning the exposure up
    without end.
    '''
    def plant(t):
        return -np.clip((t - 60) / 300, 0, None)    # -1 dB per 5 min
    loop = run_loop(plant, seconds=1200)
    if plot.enabled:
        plot(plot_loop(loop, 'Speaker losing 1 dB every 5 min (max_drift '
                       '2 dB)'))
    assert loop.controller.frozen
    assert loop.records[-1]['action'] == 'freeze'
    assert loop.schedule.gain_db == pytest.approx(2)


def test_microphone_dropout_freezes(plot):
    '''
    The microphone going silent freezes the loop; the exposure is not turned
    up.
    '''
    def plant(t):
        return np.where(t < 100, -1.0, -np.inf)
    with np.errstate(divide='ignore'):
        loop = run_loop(plant)
    if plot.enabled:
        plot(plot_loop(loop, 'Microphone goes silent at 100 s'))
    assert loop.controller.frozen
    assert loop.records[-1]['action'] == 'freeze'
    assert loop.controller.gain == pytest.approx(1)
    assert loop.schedule.gain_db == pytest.approx(1)


def test_over_level_trips(plot):
    def plant(t):
        return np.where(t < 100, 0.0, 10.0)
    loop = run_loop(plant)
    if plot.enabled:
        plot(plot_loop(loop, 'Level jumps 10 dB at 100 s'))
    assert 'trip' in actions(loop.records)
    assert loop.schedule.gain_db == loop.controller.min_gain
    assert loop.controller.frozen


def test_nothing_before_steady_state():
    '''
    Seconds before `start` (the onset ramp) are not judged.
    '''
    loop = run_loop(lambda t: np.full_like(t, -2.0), seconds=30, start=25)
    assert loop.records == []
    assert loop.schedule.changes == []


# -------- trimming on the onset ramp --------

class TestRampLevel:

    def test_full_level(self):
        assert lc.ramp_level(10, 11, 10, 5) == 0
        assert lc.ramp_level(3, 4, 2, 0) == 0

    def test_before_ramp(self):
        assert lc.ramp_level(3, 4, 10, 5) == -np.inf
        assert lc.ramp_level(1, 2, 2, 0) == -np.inf

    def test_on_ramp(self):
        '''
        The power average of the cos² ramp's amplitude, squared, over the
        second.
        '''
        start, rise = 20, 10
        t = np.linspace(14, 15, 100001)
        power = np.sin(np.pi / 2 * (t - (start - rise)) / rise) ** 4
        expected = 10 * np.log10(power.mean())
        assert lc.ramp_level(14, 15, start, rise) == \
            pytest.approx(expected, abs=1e-4)

    def test_half_way(self):
        # At half the rise time, the amplitude is 0.5 (-6 dB).
        assert lc.ramp_level(14.999, 15.001, 20, 10) == \
            pytest.approx(-6.02, abs=0.01)


@pytest.mark.parametrize('offset', [-2.5, 2.5])
def test_trims_on_ramp_before_full_level(offset, plot):
    '''
    With a ramp long enough, the trim is measured on the ramp and is already
    in place when the exposure reaches full level: nothing at full level is
    played at the untrimmed gain, and it is not judged again.
    '''
    start = 21
    loop = run_loop(lambda t: np.full_like(t, offset), seconds=120,
                    start=start, rise_time=20, lookahead=5)
    if plot.enabled:
        plot(plot_loop(loop, f'Constant {offset:+} dB offset, 20 s ramp'))
    trim = loop.records[0]
    assert trim['action'] == 'trim'
    assert trim['time'] <= start - 5
    # Within the sampling of the simulated ramp.
    assert trim['level'] == pytest.approx(TARGET + offset, abs=0.05)
    assert loop.controller.gain == pytest.approx(-offset, abs=0.05)
    full = loop.t >= start
    np.testing.assert_allclose(loop.gain_db[full], loop.controller.gain)
    assert set(actions(loop.records[1:])) == {'hold'}
    assert len(loop.schedule.changes) == 1


def test_long_ramp_trims_on_full_window():
    '''
    A ramp with more than a window of time to spare trims on a full window,
    still on the ramp.
    '''
    start = 61
    loop = run_loop(lambda t: np.full_like(t, 2.0), seconds=120,
                    start=start, rise_time=60, lookahead=5)
    trim = loop.records[0]
    assert trim['action'] == 'trim'
    # The top 6 dB of the ramp starts halfway up it, at 31 s.
    assert trim['time'] == pytest.approx(31 + 10, abs=1)
    np.testing.assert_allclose(loop.gain_db[loop.t >= start], -2, atol=0.05)


def test_short_ramp_trims_after_window():
    '''
    With too few seconds of the ramp to judge (the default 1 s ramp), the
    trim comes after a full window, as without the ramp.
    '''
    start = 2
    loop = run_loop(lambda t: np.full_like(t, 2.0), seconds=60,
                    start=start, rise_time=1)
    trim = loop.records[0]
    assert trim['action'] == 'trim'
    # The window's first second is the ramp's.
    assert trim['time'] == start + 9
    assert loop.controller.gain == pytest.approx(-2, abs=0.1)


def test_ramp_trim_with_initial_gain():
    '''
    The operator's trim is played from the start, and the loop's trim on the
    ramp corrects what it leaves.
    '''
    start = 21
    loop = run_loop(lambda t: np.full_like(t, 2.0), seconds=60,
                    start=start, rise_time=20, initial=-1.5)
    assert np.all(loop.gain_db[loop.t < loop.records[0]['time']] == -1.5)
    assert loop.controller.trim == pytest.approx(-0.5, abs=0.05)
    np.testing.assert_allclose(loop.gain_db[loop.t >= start], -2, atol=0.05)


# -------- the envelope of a gain change --------

def test_gain_change_envelope(plot):
    '''
    The exposure's envelope through two gain changes, the second made
    halfway through the ramp of the first: each ramps (cos², `RAMP_TIME`)
    from wherever the gain is, so the envelope never jumps, and blocks
    rendered before a change keep their gain.
    '''
    fs = 10000
    block = 512
    schedule = GainSchedule(fs, ramp_time=lc.RAMP_TIME)
    noise = np.random.default_rng(0).normal(scale=0.3, size=int(0.6 * fs))
    out = np.empty_like(noise)
    sets = {int(0.1 * fs): 3, int(0.15 * fs): -3}
    pending = sorted(sets)
    set_at = []
    for i in range(0, len(noise), block):
        while pending and pending[0] <= i:
            set_at.append((i, sets[pending.pop(0)]))
            schedule.set(set_at[-1][1])
        out[i:i + block] = schedule.apply(i, noise[i:i + block])
    gain = schedule.gain_at(np.arange(len(noise)))

    if plot.enabled:
        import matplotlib.pyplot as plt
        t = np.arange(len(noise)) / fs * 1e3
        figure, (ax_wave, ax_gain) = plt.subplots(
            2, 1, figsize=(10, 6), sharex=True, constrained_layout=True)
        ax_wave.plot(t, out, color='0.6', lw=0.5, label='exposure (noise)')
        envelope = 3 * 0.3 * 10 ** (gain / 20)
        ax_wave.plot(t, envelope, color='tab:blue', label='envelope (3 SD)')
        ax_wave.plot(t, -envelope, color='tab:blue')
        ax_wave.set_ylabel('Amplitude')
        ax_gain.plot(t, gain, color='tab:blue', label='gain as played')
        for i, g in set_at:
            for ax in (ax_wave, ax_gain):
                ax.axvline(i / fs * 1e3, color='tab:red', ls=':', lw=1)
            ax_gain.annotate(f'set({g:+}) when rendered up to here',
                             (i / fs * 1e3, gain[i]), fontsize=8,
                             xytext=(4, 4), textcoords='offset points')
        for i in range(0, len(noise), block):
            ax_gain.axvline(i / fs * 1e3, color='0.85', lw=0.5, zorder=0)
        ax_gain.set_ylabel('Gain (dB)')
        ax_gain.set_xlabel('Time (ms)')
        ax_wave.legend(loc='upper right', fontsize=8)
        ax_wave.set_title(
            f'Two changes, the second halfway through the first\'s '
            f'{lc.RAMP_TIME * 1e3:.0f} ms ramp (grey lines: {block}-sample '
            'blocks rendered)', fontsize=9)
        plot(figure)

    first, second = set_at[0][0], set_at[1][0]
    assert np.all(gain[:first] == 0)
    assert np.max(np.abs(np.diff(gain))) < 0.05
    assert 0 < gain[second] < 3
    assert gain[-1] == pytest.approx(-3)
    np.testing.assert_allclose(out, noise * 10 ** (gain / 20))


# -------- the running median plotted --------

def level_blocks(levels, size):
    '''
    `levels` as the blocks of `size` 1 s levels the `SPL` input sends on:
    one channel by time, as from the microphone.
    '''
    return [PipelineData(levels[np.newaxis, i:i + size], fs=1, s0=i)
            for i in range(0, len(levels), size)]


@pytest.mark.parametrize('n', [1, 5])
@pytest.mark.parametrize('size', [1, 3, 7, 20])
def test_running_median(n, size):
    '''
    Each value sent is the median of that level and the `n - 1` before it
    (fewer at the start), at that level's time, however the levels are
    blocked.
    '''
    rng = np.random.default_rng(0)
    levels = 100 + rng.normal(size=20)
    sent = []
    pipeline = lc.running_median(n, sent.append)
    for block in level_blocks(levels, size):
        pipeline.send(block)
    expected = [np.median(levels[max(i - n + 1, 0):i + 1])
                for i in range(len(levels))]
    assert all(b.shape == (1, min(size, 20 - b.s0)) for b in sent)
    medians = np.concatenate([np.asarray(b) for b in sent], axis=-1)[0]
    np.testing.assert_allclose(medians, expected)
    assert [b.s0 for b in sent] == list(range(0, len(levels), size))
    assert all(b.fs == 1 for b in sent)


def test_running_median_ignores_brief_noise():
    '''
    A level or two far off (e.g., an animal vocalizing) barely moves the
    median, as it does not move the level control.
    '''
    levels = np.full(15, 100.0)
    levels[[7, 8]] = 120
    sent = []
    pipeline = lc.running_median(10, sent.append)
    for block in level_blocks(levels, 15):
        pipeline.send(block)
    np.testing.assert_allclose(np.asarray(sent[0]), 100)
