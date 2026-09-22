from enaml.qt.qt_application import QtApplication
import enaml
with enaml.imports():
    from .gui import Main


from psi.application import (
    install_exception_handler, load_paradigm_descriptions,
    setup_windows_console
)

# psiapp.util rather than psiapp.api: the latter pulls in .enaml modules and
# so needs the enaml import hook active, which this needs no part of.
from psiapp.util import set_app_id


def main():
    import argparse
    parser = argparse.ArgumentParser('noise-exp')
    args = parser.parse_args()

    # Importing psi.application no longer installs the exception hook or
    # adjusts the Windows console as a side effect (psiexperiment 0.7.0);
    # launchers that do not go through `launch_experiment` have to ask for
    # both explicitly.
    setup_windows_console()
    install_exception_handler()

    # Before QtApplication, and distinct from the `psi.psi` the exposure
    # subprocess claims, so the launcher and the running experiment get their
    # own taskbar buttons.
    set_app_id('psi.noise-exp')

    load_paradigm_descriptions()
    app = QtApplication()
    view = Main()
    view.show()
    app.start()
    return True
