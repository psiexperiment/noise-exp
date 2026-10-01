'''
Default values for every noise-exp setting.

Registered with :func:`psi.config.register_defaults` when ``noise_exp`` is
imported, so these resolve the same way as any psi setting: default, then
``config.toml``, then the environment.
'''
from psi import Setting


#: Number of animals that can be exposed at once. A property of the
#: exposure cage rather than of the software, which is why a rig with a
#: differently-sized cage can override it.
DEFAULT_MAX_ANIMALS = 6


DEFAULTS = {
    'NOISE_EXP_MAX_ANIMALS': Setting(
        int, DEFAULT_MAX_ANIMALS,
        doc='Number of animals the exposure cage holds.'),

    #: Launcher defaults, previously a default.json under the psi config
    #: folder.
    'NOISE_EXP_LOGGING_LEVEL': Setting(
        str, 'info', doc='Console logging level for the exposure.'),
    'NOISE_EXP_PREFERENCE': Setting(
        str, '', doc='Preferences file to load.'),

    #: Microphone and speaker selections, as tables so that the device,
    #: connection name and gain travel together.
    'NOISE_EXP_MICROPHONE': Setting(
        dict, {}, doc='Selected microphone, connection and gain.'),
    'NOISE_EXP_SPEAKER': Setting(
        dict, {}, doc='Selected speaker and connection.'),
}
