# Generates main-icon.png and main-icon.ico. Run from this directory:
#   python make_icon.py
#
# Deliberately mirrors cftscal/icons/make_icon.py (same frame, palette and
# construction) so the two launchers read as part of one family. The signal
# inside the frame is what differs: a chirp there, broadband noise here.
import matplotlib as mp
import matplotlib.pyplot as plt
from matplotlib import patheffects as pe
import numpy as np
from PIL import Image


#: Sizes Windows picks from when it renders the icon (taskbar, alt-tab,
#: Explorer, ...).
ICO_SIZES = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)]


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


def make_main_icon():
    fig = plt.figure(frameon=False)
    fig.set_size_inches(1, 1)
    ax = plt.Axes(fig, [0, 0, 1, 1])
    ax.set_axis_off()
    fig.add_axes(ax)

    background = mp.patches.Rectangle([0, 0], width=1, height=1, facecolor='midnightblue',
                                      edgecolor='none', transform=ax.transAxes)
    ax.add_patch(background)

    t = np.linspace(0, 1, 500)
    y = make_noise(t.size)

    # Taper the noise on and off, evoking the fixed-duration exposure the
    # program delivers rather than a continuously running signal.
    envelope = np.sin(np.pi * t) ** 0.5
    y = y * envelope

    spline_effect = [
        pe.Stroke(linewidth=4, foreground='white'),
    ]
    ax.fill_between(t, y, -1.5, color='cornflowerblue')
    ax.plot(t, y, color='none', solid_capstyle='round', path_effects=spline_effect)

    ax.axis(xmin=-0.05, xmax=1.05, ymin=-1.5, ymax=1.5)

    border = mp.patches.Rectangle([0, 0], width=1, height=1, facecolor='none',
                                  edgecolor='white', linewidth=10,
                                  transform=ax.transAxes, zorder=3)
    ax.add_patch(border)
    fig.savefig('main-icon.png', transparent=False, bbox_inches='tight', pad_inches=0, dpi=256)


def make_ico():
    # cftscal used an online converter for this step; Pillow is already
    # pulled in by matplotlib, so do it here instead.
    image = Image.open('main-icon.png').convert('RGBA')
    image.save('main-icon.ico', sizes=ICO_SIZES)


if __name__ == '__main__':
    make_main_icon()
    make_ico()
