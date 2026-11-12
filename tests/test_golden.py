'''
A golden copy of the exposure, to catch any change to the noise the animals
are exposed to.

The exposure is built the way psi builds it when the experiment prepares
(`psi.controller.token_context.initialize_factory` on the paradigm's
`exposure` output, with the context psi read for it), so this covers the
paradigm's token (`noise_exposure.enaml`), the defaults of the token's
parameters (psiexperiment's `psi.token.primitives`) and the waveform
factories (psiaudio). Two files are kept in `tests/golden`:

* `exposure-context.json`: the context psi read for the exposure, i.e. every
  setting of the noise and its envelope, as the paradigm defaults them, and
  the values the paradigm fixes on each block of its token (`values`, e.g.
  `polarity`), which psi also fixes the context item of the same
  setting at.
* `exposure.npz`: the waveform, with the duration and rise time shortened
  (see `DURATION` and `RISE_TIME`) to keep the file small. The noise is
  frozen (seeded), so every exposure with these settings is this waveform.

The experiment runs on `null_io` with the fake calibrations in `conftest.py`,
so the levels are dB re 1 Vrms and the waveform's scale is arbitrary.

If a change to the exposure is intended, rewrite the golden files with
`pytest tests/test_golden.py --update-golden` and review the diff.
'''
import json
from pathlib import Path

import numpy as np
import pytest

from psi.controller.token_context import initialize_factory


GOLDEN = Path(__file__).parent / 'golden'
CONTEXT_FILE = GOLDEN / 'exposure-context.json'
WAVEFORM_FILE = GOLDEN / 'exposure.npz'

#: Context items of the exposure's envelope, as the token names them (the
#: paradigm's settings of the same values, which drive these, keep the
#: exposure's established names; see `noise_exposure.enaml`).
DURATION_NAME = 'exposure_burst_duration'
RISE_TIME_NAME = 'exposure_burst_rise_time'

#: The golden waveform's duration and rise time (s), shorter than the
#: paradigm's defaults so the file stays small. Both ramps and a stretch of
#: steady noise between them are still in it.
DURATION = 0.5
RISE_TIME = 0.1

#: Samples the sound card engine asks the output for at a time
#: (`SoundcardEngine` in psiexperiment), to check that rendering in blocks
#: matches rendering in one go.
ENGINE_BLOCKSIZE = 8192


def to_json(value):
    '''
    `value` as JSON-compatible data that compares equal after a round trip.
    '''
    if isinstance(value, dict):
        return {str(k): to_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json(v) for v in value]
    if isinstance(value, np.ndarray):
        return to_json(value.tolist())
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and np.isnan(value):
        return 'nan'
    return value


@pytest.fixture
def update(request):
    return request.config.getoption('--update-golden')


@pytest.fixture(scope='module')
def exposure(running_experiment):
    '''
    The exposure output and the context psi read for it when the experiment
    prepared (`exposure.prepare`, on `context_initialized`).
    '''
    controller = running_experiment.get_plugin('psi.controller')
    output = controller.get_output('exposure')
    return output, dict(output.source_md)


def render(output, context, blocksize=None):
    '''
    The exposure for `context`, shortened to `DURATION`, rendered in one go
    or, given `blocksize`, a block at a time as the engine asks for it.
    '''
    context = {**context, DURATION_NAME: DURATION, RISE_TIME_NAME: RISE_TIME,
               'fs': output.fs, 'calibration': output.calibration}
    factory = initialize_factory(output, output.token, context)
    if blocksize is None:
        return factory.get_samples_remaining()
    n = factory.n_samples_remaining()
    blocks = []
    while not factory.is_complete():
        blocks.append(factory.next(blocksize))
    return np.concatenate(blocks)[:n]


def fixed_values(block):
    '''
    The values fixed on `block` and the blocks inside it, by block name.
    '''
    values = {block.name: dict(block.values)}
    for b in block.blocks:
        values.update(fixed_values(b))
    return values


def test_context(exposure, update):
    '''
    The settings of the exposure psi uses by default.
    '''
    output, context = exposure
    actual = to_json({'context': context,
                      'fixed values': fixed_values(output.token)})
    if update:
        GOLDEN.mkdir(exist_ok=True)
        CONTEXT_FILE.write_text(json.dumps(actual, indent=1, sort_keys=True)
                                + '\n')
        pytest.skip('Golden exposure context rewritten')
    expected = json.loads(CONTEXT_FILE.read_text())
    assert actual == expected


def test_waveform(exposure, update):
    output, context = exposure
    actual = render(output, context)
    if update:
        GOLDEN.mkdir(exist_ok=True)
        np.savez_compressed(WAVEFORM_FILE, fs=output.fs,
                            duration=DURATION, rise_time=RISE_TIME,
                            waveform=actual.astype('float32'))
        pytest.skip('Golden exposure waveform rewritten')
    golden = np.load(WAVEFORM_FILE)
    assert float(golden['fs']) == output.fs
    assert float(golden['duration']) == DURATION
    assert float(golden['rise_time']) == RISE_TIME
    expected = golden['waveform']
    actual = actual.astype('float32')
    assert actual.shape == expected.shape
    scale = np.abs(expected).max()
    np.testing.assert_allclose(actual, expected, rtol=1e-5, atol=1e-6 * scale)


def test_waveform_rendered_in_blocks(exposure):
    '''
    The engine renders the exposure a block at a time, which must give the
    same noise as rendering it in one go (the noise generator and its filter
    carry their state from block to block).
    '''
    output, context = exposure
    whole = render(output, context)
    blocks = render(output, context, ENGINE_BLOCKSIZE)
    np.testing.assert_allclose(blocks, whole, rtol=0,
                               atol=1e-9 * np.abs(whole).max())
