'''
Tracks whether the psivideo server is running, and starts it on request.

The exposure requires psivideo (see `paradigms.video_mixin`) but does not
launch it: the operator needs to open it first to frame the shot before the
exposure starts.
'''
import logging
log = logging.getLogger(__name__)

import shutil
import subprocess
import sysconfig
import threading

from atom.api import Atom, Bool, Float, Int, Str, Typed, Value
from enaml.application import deferred_call, timed_call
from websockets.sync.client import connect

# The port `psivideo.plugin.PSIVideo` connects to, which is also the psivideo
# server's default.
PSIVIDEO_PORT = 33331


def is_psivideo_running(hostname='127.0.0.1', port=PSIVIDEO_PORT, timeout=1):
    '''
    True if a psivideo server answers on `port`.

    Opens a real websocket rather than a bare TCP connection, which the server
    logs as a failed handshake (with a traceback) on every check. 127.0.0.1
    rather than localhost: on Windows a refused connection takes ~2 s per
    address tried, and localhost tries both ::1 and 127.0.0.1.
    '''
    try:
        with connect(f'ws://{hostname}:{port}', open_timeout=timeout):
            return True
    except Exception:
        return False


def find_psivideo():
    '''
    Path to the `psivideow` (no console) entry point, preferring the one
    installed alongside noise-exp in case the environment's script folder is
    not on the PATH.
    '''
    return shutil.which('psivideow', path=sysconfig.get_path('scripts')) \
        or shutil.which('psivideow')


class PSIVideoMonitor(Atom):

    #: Checked every `interval` seconds on a background thread, since a check
    #: can take a couple of seconds when the server is not running.
    running = Bool(False)

    #: True from clicking "Open psivideo" until the server answers, the
    #: process exits, or `launch_timeout` seconds pass, so the button cannot
    #: start a second copy while the camera is still starting up.
    launching = Bool(False)

    hostname = Str('127.0.0.1')
    port = Int(PSIVIDEO_PORT)
    interval = Float(2)
    launch_timeout = Float(30)

    process = Value()
    _stop = Typed(threading.Event, ())
    _thread = Typed(threading.Thread)

    def start(self):
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _monitor(self):
        while True:
            running = is_psivideo_running(self.hostname, self.port)
            deferred_call(self._update, running)
            if self._stop.wait(self.interval):
                break

    def _update(self, running):
        self.running = running
        if running or (self.process is not None and self.process.poll() is not None):
            self.launching = False

    def launch(self):
        '''
        Start psivideo without waiting for it. It is left running if the
        launcher closes, since the operator may still be using it.
        '''
        path = find_psivideo()
        if path is None:
            raise FileNotFoundError('Could not find psivideow. Is psivideo '
                                    'installed in this environment?')
        log.info('Starting %s', path)
        self.process = subprocess.Popen([path])
        self.launching = True
        timed_call(int(self.launch_timeout * 1000), self._launch_timed_out,
                   self.process)

    def _launch_timed_out(self, process):
        # Ignore the timer from an earlier launch.
        if process is self.process:
            self.launching = False
