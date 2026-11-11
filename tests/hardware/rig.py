'''
The Fireface test rig: which IO manifest the exposure runs on and which
channel is which.

The exposure runs on `cftscal.io.dummy_fireface.IOManifest`, where the
speaker is `speaker_1` (output 4) and the measurement microphone the
exposure is monitored with is `cal_microphone` (input 3). Those are not on
the same channel number, so TotalMix needs a route from output 4 to input 3
(the probe in `psi.loopback.rig.measure_routing` checks for it before the
exposure runs).
'''
from psi.loopback.rig import Rig


IO_MANIFEST = 'cftscal.io.dummy_fireface.IOManifest'
DEVICE_NAME = 'ASIO Fireface USB'

SPEAKER = 'speaker_1'
MICROPHONE = 'cal_microphone'

#: Channel numbers in `cftscal.io.dummy_fireface` (0-based).
OUTPUTS = {SPEAKER: 4}
INPUTS = {MICROPHONE: 3}

#: Full-scale input level of the manifest's inputs, `Input.dBFS` in
#: `dummy_fireface`.
INPUT_DBFS = 19

#: The sound card engine's defaults, which `dummy_fireface` keeps.
ENGINE_FS = 96000
ENGINE_BLOCKSIZE = 8192

RIG = Rig(
    io_manifest=IO_MANIFEST,
    device=DEVICE_NAME,
    outputs=OUTPUTS,
    inputs=INPUTS,
    input_dbfs=INPUT_DBFS,
    engine_fs=ENGINE_FS,
    engine_blocksize=ENGINE_BLOCKSIZE,
)
