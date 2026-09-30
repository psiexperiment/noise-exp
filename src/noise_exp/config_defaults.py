'''
Default values for every noise-exp setting.

Registered with :func:`psi.config.register_defaults` when ``noise_exp`` is
imported, so these resolve the same way as any psi setting: default, then
``config.toml``, then the environment.
'''

#: Number of animals that can be exposed at once. A property of the
#: exposure cage rather than of the software, which is why a rig with a
#: differently-sized cage can override it.
DEFAULT_MAX_ANIMALS = 6


DEFAULTS = {
    'NOISE_EXP_MAX_ANIMALS': lambda: DEFAULT_MAX_ANIMALS,

    #: Launcher defaults, previously a default.json under the psi config
    #: folder.
    'NOISE_EXP_LOGGING_LEVEL': lambda: 'info',
    'NOISE_EXP_PREFERENCE': lambda: '',

    #: Microphone and speaker selections, as tables so that the device,
    #: connection name and gain travel together.
    'NOISE_EXP_MICROPHONE': lambda: {},
    'NOISE_EXP_SPEAKER': lambda: {},
}
