# Generates main-icon.png and main-icon.ico. Run from anywhere:
#   python make_icon.py
#
# The frame, palette and output sizes come from psiapp.icons, shared with the
# other psi programs (pip install psiapp[icons]). Only the motif is drawn here:
# broadband noise, where cftscal's icon has a chirp.
from pathlib import Path

import numpy as np

from psiapp.icons import make_icon, plot_signal


HERE = Path(__file__).parent


def make_noise(n=500, seed=0):
    '''
    Band-limited noise, normalized to +/-1.

    Shaped in the frequency domain rather than by filtering white noise so
    that the trace is smooth enough to stay legible at 16x16 while still
    reading as noise rather than as a tone.
    '''
    rng = np.random.RandomState(seed)
    noise = rng.normal(size=n)
    csd = np.fft.rfft(noise)
    freq = np.fft.rfftfreq(n, 1 / n)
    # Keep only the middle of the band. The lower bound stops the trace from
    # wandering off-center; the upper bound keeps the peaks far enough apart
    # to survive downsampling to the smallest icon.
    csd[(freq < 3) | (freq > 10)] = 0
    y = np.fft.irfft(csd, n)
    # Peak just short of the frame so the trace never collides with the
    # border.
    return y / np.abs(y).max() * 0.9


def draw(ax):
    t = np.linspace(0, 1, 500)
    y = make_noise(t.size)

    # Taper the noise on and off, evoking the fixed-duration exposure the
    # program delivers rather than a continuously running signal.
    envelope = np.sin(np.pi * t) ** 0.5
    plot_signal(ax, t, y * envelope)


if __name__ == '__main__':
    make_icon(draw, HERE / 'main-icon.png', HERE / 'main-icon.ico')
