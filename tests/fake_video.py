'''
A stand-in for the psivideo client, so the exposure can run without a
psivideo server (and camera) attached.

The paradigm requires `psivideo.plugin.PSIVideo`, whose sink connects to
the server as soon as the plugins start. The unit tests patch the client
class in-process (see `conftest.py`); the loopback tests run the paradigm in
a subprocess and swap it in with `hardware/no_video.enaml`.
'''


class FakeVideoClient:
    '''
    Stands in for `psivideo.client.SyncVideoClient`. Records where it was
    asked to save.
    '''

    def __init__(self, *args, **kwargs):
        self.recording = None

    def __getattr__(self, name):
        # Every other client call (connect, set_data_folder, snapshot, ...)
        # is accepted and ignored.
        return lambda *args, **kwargs: None

    def start(self, filename):
        self.recording = filename

    def get_timing(self):
        return {'frame_number': 0, 'timestamp': 0.0}
