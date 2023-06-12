from psi.experiment.api import ParadigmDescription


CORE_PATH = 'psi.paradigms.core.'
PATH = 'noise_exp.paradigms.'


microphone_mixin = {
    'manifest': CORE_PATH + 'signal_mixins.SignalViewManifest',
    'required': True,
    'attrs': {
        'id': 'microphone_signal_view',
        'title': 'Microphone view (time)',
        'time_span': 10,
        'time_delay': 0,
        'source_name': 'microphone_filtered',
        'y_label': 'Microphone (dB)'
    },
}


microphone_fft_mixin = {
    'manifest': CORE_PATH + 'signal_mixins.SignalFFTViewManifest',
    'required': True,
    'attrs': {
        'id': 'microphone_fft_view',
        'title': 'Microphone view (PSD)',
        'fft_time_span': 1,
        'waveform_averages': 10,
        'fft_freq_lb': 500,
        'fft_freq_ub': 64000,
        'source_name': 'microphone_filtered',
        'y_label': 'Microphone (dB)'
    }
}


selectable_microphone_mixin = {
    'manifest': 'cftscal.paradigms.objects.Microphone',
    'required': True,
    'attrs': {'id': 'monitor', 'title': 'Microphone'},
}


ParadigmDescription(
    'noise_exposure', 'Noise exposure', 'cohort', [
        {'manifest': PATH + 'noise_exposure.NoiseControllerManifest'},
        microphone_mixin,
        microphone_fft_mixin,
        selectable_microphone_mixin,
    ],
)
