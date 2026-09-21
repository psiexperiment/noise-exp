'''
Smoke tests for the noise-exposure paradigm and its launcher.
'''
import pytest

import enaml


def test_launcher_imports():
    '''
    The launcher GUI imports (i.e., every cftscal name it uses exists).
    '''
    with enaml.imports():
        from noise_exp.gui import Main  # noqa: F401
    from noise_exp.main import main  # noqa: F401


def test_paradigm_registered(paradigm):
    assert paradigm.name == 'noise_exposure'
    assert paradigm.experiment_type == 'cohort'


def test_all_plugins_required(paradigm):
    '''
    Every mixin is required, so `psi noise_exp.paradigms.noise_exposure`
    (which deselects everything first) still loads the full paradigm.
    '''
    assert all(p.required for p in paradigm.plugins)


def test_experiment_runs(running_experiment):
    controller = running_experiment.get_plugin('psi.controller')
    assert controller.experiment_state == 'running'


def test_exposure_targets_speaker(running_experiment):
    '''
    `cftscal.paradigms.objects.Output` names the output it contributes
    `{id}_output`, which is what the exposure output has to target.
    '''
    controller = running_experiment.get_plugin('psi.controller')
    assert controller.get_output('exposure').target.name == 'speaker_output'


def test_calibrations_loaded(running_experiment):
    '''
    Both calibrations named in the environment reach their channel, and
    the microphone gain is applied.
    '''
    from psiaudio.calibration import FlatCalibration

    controller = running_experiment.get_plugin('psi.controller')
    microphone = controller.get_channel('hw_ai::mic_a')
    speaker = controller.get_channel('hw_ao::speaker_a')

    assert isinstance(microphone.calibration, FlatCalibration)
    assert isinstance(speaker.calibration, FlatCalibration)
    assert microphone.gain == 20


@pytest.mark.parametrize('name', [
    # Contributed by the exposure token. The band-pass filter that
    # isolates the exposure band is defined in terms of the last two.
    'exposure_bandlimited_fir_noise_burst_rise_time',
    'exposure_bandlimited_noise_fl',
    'exposure_bandlimited_noise_fh',
    # Contributed by the cftscal microphone and speaker manifests.
    'monitor_microphone_input',
    'monitor_microphone_input_gain',
    'speaker',
])
def test_context_item_exists(running_experiment, name):
    context = running_experiment.get_plugin('psi.context')
    assert name in context.context_items


def test_inputs_available(running_experiment):
    '''
    The inputs the data sink and the plots are wired to all exist.
    '''
    controller = running_experiment.get_plugin('psi.controller')
    for name in ('monitor_microphone', 'microphone_filtered',
                 'microphone_band_filtered', 'noise_level',
                 'band_noise_level'):
        assert controller.get_input(name) is not None


def test_progress_bar_configured(running_experiment):
    '''
    `configure_experiment` runs on `exposure_start` and sizes the progress
    bar from the output sample rate, which is only known once the output
    has been wired to its channel.
    '''
    from enaml.widgets.api import ProgressBar

    for manifest in running_experiment._manifests.values():
        for obj in manifest.traverse():
            if isinstance(obj, ProgressBar) and obj.name == 'noise_progress':
                assert obj.maximum > 0
                return
    pytest.fail('noise_progress progress bar not found')


@pytest.fixture
def gui():
    '''
    The launcher module.

    Imported lazily (rather than at module scope) because building it
    reaches into cftscal for the list of microphones and speakers, which
    is only pinned to the null IO manifest once `pinned_io` has run.
    '''
    with enaml.imports():
        from noise_exp import gui
    return gui


def test_max_animals_default(gui, monkeypatch):
    monkeypatch.delenv('NOISE_EXP_MAX_ANIMALS', raising=False)
    assert gui.get_max_animals() == 6


def test_max_animals_from_env(gui, monkeypatch):
    '''
    A rig whose cage holds a different number of animals overrides the
    default, and does so without restarting the launcher.
    '''
    monkeypatch.setenv('NOISE_EXP_MAX_ANIMALS', '4')
    assert gui.get_max_animals() == 4


@pytest.mark.parametrize('value', ['0', '-1', 'four'])
def test_max_animals_invalid(gui, monkeypatch, value):
    '''
    A typo in the environment is reported rather than silently ignored or
    turned into a dialog with no fields in it.
    '''
    monkeypatch.setenv('NOISE_EXP_MAX_ANIMALS', value)
    with pytest.raises(ValueError, match='NOISE_EXP_MAX_ANIMALS'):
        gui.get_max_animals()


def test_make_animals_pads(gui):
    assert [a.id for a in gui.make_animals(['A1', 'A2'], 4)] \
        == ['A1', 'A2', '', '']


def test_make_animals_truncates(gui):
    '''
    More IDs than slots cannot happen through the dialog, but the cohort
    must never end up longer than the cage.
    '''
    assert [a.id for a in gui.make_animals(['A1', 'A2', 'A3'], 2)] \
        == ['A1', 'A2']


def test_cohort_dialog_field_count(app, gui, monkeypatch):
    '''
    The dialog offers exactly one field per slot in the cage.
    '''
    from enaml.widgets.api import Field

    monkeypatch.setenv('NOISE_EXP_MAX_ANIMALS', '3')
    dialog = gui.CohortDialog()
    dialog.initialize()
    assert len([o for o in dialog.traverse() if isinstance(o, Field)]) == 3


def test_cohort_dialog_shows_current_animals(app, gui, monkeypatch):
    '''
    Reopening the dialog shows what was entered last time, in the leading
    fields, with the unused slots left blank.
    '''
    from enaml.widgets.api import Field

    monkeypatch.setenv('NOISE_EXP_MAX_ANIMALS', '3')
    dialog = gui.CohortDialog(animals=gui.make_animals(['A1', 'A2']))
    dialog.initialize()
    fields = [o for o in dialog.traverse() if isinstance(o, Field)]
    assert [f.text for f in fields] == ['A1', 'A2', '']


def test_blank_fields_are_not_animals(gui):
    '''
    A blank field means an empty slot, so it must not become an animal (nor
    a doubled space in the filename).
    '''
    settings = gui.Settings()
    animals = gui.make_animals([], 6)
    animals[0].id = 'A1'
    animals[3].id = '  A4  '
    settings.set_animals(animals)
    assert settings.animals == ['A1', 'A4']
    assert settings.cohort == 'A1 A4'


def test_cohort_is_derived_from_animals(gui):
    settings = gui.Settings()
    settings.animals = ['A1', 'A2', 'A3']
    assert settings.cohort == 'A1 A2 A3'
    settings.animals.remove('A2')
    assert settings.cohort == 'A1 A3'


def test_cohort_not_typed_into(app, gui):
    '''
    The cohort is generated from the animal IDs, so the launcher offers a
    button that opens the dialog rather than an editable field.
    '''
    from enaml.widgets.api import Field, PushButton

    main = gui.Main()
    main.initialize()
    button = [o for o in main.traverse()
              if isinstance(o, PushButton) and o.name == 'cohort_button']
    assert len(button) == 1
    assert not isinstance(button[0], Field)

    main.settings.animals = ['A1', 'A2']
    assert button[0].text == 'A1 A2'
