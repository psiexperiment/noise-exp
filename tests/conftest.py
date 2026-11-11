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

from fake_video import FakeVideoClient

with enaml.imports():
    from null_io import NullIOManifest


def pytest_addoption(parser):
    parser.addoption(
        '--update-golden', action='store_true',
        help='Rewrite the golden exposure (tests/golden) from the current '
        'code instead of checking against it. Review the diff before '
        'committing it.')


#: What the launcher (`src/noise_exp/gui.enaml`) puts in the environment when
#: it starts an exposure. `read_env_vars` in cftscal builds the name of
#: every variable but the first from the value of the first one.
CAL_ENV = {
    'CFTSCAL_MICROPHONE': 'mic_a',
    'CFTSCAL_MICROPHONE_MIC_A_GAIN': '20',
    'CFTSCAL_MICROPHONE_MIC_A': 'fake_calibrations.FakeMicrophoneCalibration::10',
    'CFTSCAL_SPEAKER': 'speaker_a',
    'CFTSCAL_SPEAKER_SPEAKER_A': 'fake_calibrations.FakeSpeakerCalibration',
}


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    '''
    Give every test its own empty configuration file.

    Settings resolve as default, then config.toml, then the environment,
    and the file is whatever PSI_CONFIG_FILE points at -- on a developer
    machine, the real rig configuration. A test asserting a built-in
    default therefore passed or failed depending on what the person
    running it had configured, and anything that saved settings wrote
    into their live file. Both are fixed by pointing the whole suite at a
    fresh tmp_path.

    The environment overrides both, so every setting set there is removed
    too (e.g., CFTSCAL_IO on a machine set up for the keyboard manifest).
    The variables the exposure is configured from (`cal_env`) have already
    been read by then: the running experiment is set up first.
    '''
    import os
    from psi import config as psi_config

    settings = set(psi_config.setting_names())
    for name in list(os.environ):
        if name in settings or                 name.startswith(('PSI_', 'CFTSCAL_', 'NOISE_EXP_')):
            monkeypatch.delenv(name)
    monkeypatch.setenv('PSI_CONFIG_FILE', str(tmp_path / 'config.toml'))
    psi_config.reload_config()
    yield
    psi_config.reload_config()


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


@pytest.fixture(scope='session', autouse=True)
def fake_video_client():
    '''
    Replace the psivideo client with `FakeVideoClient`. The plugin imports
    the client when it first needs one, so patching the module is enough.
    '''
    import psivideo.client
    original = psivideo.client.SyncVideoClient
    psivideo.client.SyncVideoClient = FakeVideoClient
    yield
    psivideo.client.SyncVideoClient = original


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
    # what is marked required plus the plugins it is given, so do the same
    # here, with video recorded as the noise-exp launcher does by default.
    paradigm.disable_all_plugins()
    paradigm.enable_plugin('psivideo')
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
