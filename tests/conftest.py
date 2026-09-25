'''
Fixtures for the noise-exposure smoke tests.

The point of these tests is to catch API drift in the two packages
noise-exp is built on (psiexperiment and cftscal) without needing the rig
attached: the paradigm is assembled against a `NullEngine` IO manifest
and driven through the same startup path the `psi` command-line launcher
uses.
'''
import os

import pytest

import enaml

with enaml.imports():
    from null_io import NullIOManifest


#: What the launcher (`noise_exp/gui.enaml`) puts in the environment when
#: it starts an exposure. `read_env_vars` in cftscal builds the name of
#: every variable but the first from the value of the first one.
CAL_ENV = {
    'CFTSCAL_MICROPHONE': 'mic_a',
    'CFTSCAL_MICROPHONE_MIC_A_GAIN': '20',
    'CFTSCAL_MICROPHONE_MIC_A': 'fake_calibrations.FakeMicrophoneCalibration::10',
    'CFTSCAL_SPEAKER': 'speaker_a',
    'CFTSCAL_SPEAKER_SPEAKER_A': 'fake_calibrations.FakeSpeakerCalibration',
}


@pytest.fixture(scope='session')
def app():
    '''
    The enaml application. Enaml allows only one per process.
    '''
    from enaml.application import Application
    from enaml.qt.qt_application import QtApplication
    return Application.instance() or QtApplication()


@pytest.fixture(scope='session', autouse=True)
def pinned_io():
    '''
    Point cftscal at the null IO manifest.

    cftscal discovers hardware through its own workspace settings rather
    than through the `--io` manifest the experiment is launched with, so
    without this the tests would go looking for whatever sound card the
    developer happens to have configured. Session-scoped and autouse
    because the manifests cache the channel list the first time they are
    built.
    '''
    import cftscal.util
    original = cftscal.util.IO_MANIFEST
    cftscal.util.IO_MANIFEST = NullIOManifest()
    yield
    cftscal.util.IO_MANIFEST = original


@pytest.fixture(scope='session')
def cal_env():
    '''
    Set the environment variables the paradigm is configured from.
    '''
    original = {k: os.environ.get(k) for k in CAL_ENV}
    os.environ.update(CAL_ENV)
    yield CAL_ENV
    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture(scope='session')
def paradigm():
    import noise_exp.paradigms  # noqa: F401
    from psi.experiment.api import paradigm_manager
    return paradigm_manager.get_paradigm('noise_exposure')


@pytest.fixture(scope='session')
def running_experiment(app, cal_env, paradigm, tmp_path_factory):
    '''
    The noise-exposure paradigm, started and left running.

    Mirrors `psi.application.workbench.PSIWorkbench.start_workspace`, but
    pumps the event loop by hand instead of handing control to Qt so the
    test can make assertions while the experiment is up.
    '''
    from enaml.qt.QtWidgets import QApplication
    from psi.application.workbench import PSIWorkbench

    # The `psi` command-line launcher deselects everything and then loads
    # only what is marked required, so do the same here.
    paradigm.disable_all_plugins()
    plugins = [p.manifest for p in paradigm.plugins if p.selected or p.required]

    workbench = PSIWorkbench()
    workbench.register_core_plugins('null_io.NullIOManifest', plugins)

    controller = workbench.get_plugin('psi.controller')
    ui = workbench.get_plugin('enaml.workbench.ui')

    ui.select_workspace('psi.experiment.ui.workspace')
    ui.show_window()
    ui.window.proxy.widget.hide()

    base_path = str(tmp_path_factory.mktemp('data') / 'exposure')
    controller.register_action('experiment_prepare', 'psi.data.set_base_path',
                               {'base_path': base_path, 'is_temp': True})

    def pump(n=20):
        for _ in range(n):
            QApplication.processEvents()

    # Service the deferred calls queued by `select_workspace`
    # (plugins_started, default preferences, default layout).
    pump()

    controller.start_experiment()
    pump()
    yield workbench

    controller.stop_experiment(skip_errors=True)
    pump()
