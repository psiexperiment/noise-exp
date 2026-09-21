'''
Calibrations that need nothing on disk.

cftscal hands a calibration to an experiment as a string of the form
``<module>.<class>::<args>`` and rebuilds it with
``CalibrationManager.from_string``, which simply imports the named class
and calls its own ``from_string``. That makes it easy to stand in a fake
here rather than having to write a real calibration directory (complete
with its ``metadata.json`` sidecar) into the test's temporary path.
'''
import datetime as dt

from psiaudio.calibration import FlatCalibration

from cftscal.objects import Calibration


class FakeMicrophoneCalibration(Calibration):
    '''Flat microphone calibration with the given sensitivity in mV/Pa.'''

    def __init__(self, sens=10):
        self.name = 'fake-microphone'
        self.sens = float(sens)

    @property
    def datetime(self):
        return dt.datetime(2026, 1, 1)

    def load(self):
        return FlatCalibration.from_mv_pa(self.sens)

    def to_string(self):
        return f'{self.qualname}::{self.sens}'

    @classmethod
    def from_string(cls, string):
        _, sens = string.split('::')
        return cls(sens)


class FakeSpeakerCalibration(Calibration):
    '''Speaker calibration where 1 Vrms is 1 Pa at every frequency.'''

    def __init__(self):
        self.name = 'fake-speaker'

    @property
    def datetime(self):
        return dt.datetime(2026, 1, 1)

    def load(self):
        return FlatCalibration.as_attenuation()

    def to_string(self):
        return self.qualname

    @classmethod
    def from_string(cls, string):
        return cls()
