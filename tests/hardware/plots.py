'''
Figures for the exposure run's report.
'''
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from scipy import signal

from psi.loopback.plots import save

from exposure_analysis import BLOCK_RESIDUAL_LIMIT, RMS_DURATION


def envelope(x, fs, width=0.01):
    '''
    Peak of `x` in each `width` s, for plotting a long recording.
    '''
    n = int(width * fs)
    k = len(x) // n
    t = (np.arange(k) + 0.5) * n / fs
    return t, np.abs(x[:k * n]).reshape(k, n).max(axis=-1)


def plot_exposure(a, path, zoom=0.02):
    '''
    The recording against the exposure: all of it, its onset, and the
    residual of each continuity block.
    '''
    figure, axes = plt.subplots(3, 1, figsize=(8, 8))
    fs = a.fs
    ax = axes[0]
    for x, label, style in ((a.recorded, 'Recorded', '-'),
                            (a.expected, 'Expected', '--')):
        t, env = envelope(x, fs)
        ax.plot(t, env, style, label=label)
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Peak (V)')
    ax.legend(loc='upper right')

    ax = axes[1]
    onset = np.flatnonzero(a.expected)
    i = onset[0] if len(onset) else 0
    lb, ub = max(i - int(zoom * fs), 0), i + int(zoom * fs)
    t = np.arange(lb, ub) / fs
    ax.plot(t, a.recorded[lb:ub], label='Recorded')
    ax.plot(t, a.expected[lb:ub], '--', label='Expected')
    ax.axvline(i / fs, color='k', lw=0.5)
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Signal (V)')
    ax.set_title('Onset')

    ax = axes[2]
    if len(a.block_times):
        ax.plot(a.block_times, a.block_residual_db, '.')
    ax.axhline(BLOCK_RESIDUAL_LIMIT, color='r', ls=':', label='Limit')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Residual (dB re exposure)')
    ax.set_title('Continuity')
    figure.tight_layout()
    return save(figure, path)


def plot_levels(a, path):
    '''
    The 1 s levels psi saved and the running averages it showed, against
    what they should be.
    '''
    figure, ax = plt.subplots(figsize=(8, 4.5))
    t = (np.arange(len(a.expected_levels)) + 0.5) * RMS_DURATION
    m = a.level_mask
    ax.plot(t[m], a.expected_levels[m], 'k-', label='Expected (1 s)')
    ax.plot(t[m], a.psi_levels[m], 'o', mfc='none', label='psi (noise_level)')
    colors = {'overall': 'C1', 'band': 'C2'}
    for name, (shown, should) in a.averages.items():
        ax.axhline(should, color=colors[name], ls='--',
                   label=f'Expected average ({name})')
        if shown is not None:
            ax.axhline(shown, color=colors[name], ls=':',
                       label=f'psi average ({name}) {shown:.1f}')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Level (dB SPL)')
    if np.any(m):
        center = a.steady_level
        ax.set_ylim(center - 3, center + 1)
    ax.legend(fontsize=8, loc='lower right')
    return save(figure, path)


def plot_spectrum(a, fl, fh, path):
    '''
    Spectrum of the steady part of the exposure as recorded and as it
    should be.
    '''
    figure, ax = plt.subplots(figsize=(8, 4.5))
    nz = np.flatnonzero(a.expected)
    if len(nz):
        lb, ub = nz[0], nz[-1] + 1
        quarter = (ub - lb) // 4
        lb, ub = lb + quarter, ub - quarter
        for x, label, style in ((a.recorded, 'Recorded', '-'),
                                (a.expected, 'Expected', '--')):
            f, p = signal.welch(x[lb:ub], a.fs, nperseg=8192)
            with np.errstate(divide='ignore'):
                ax.semilogx(f[1:], 10 * np.log10(p[1:]), style, label=label)
    for f in (fl, fh):
        ax.axvline(f, color='k', lw=0.5)
    ax.set_xlabel('Frequency (Hz)')
    ax.set_ylabel('PSD (dB re 1 V²/Hz)')
    ax.legend()
    return save(figure, path)
