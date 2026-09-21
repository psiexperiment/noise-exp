from enaml.qt.qt_application import QtApplication
import enaml
with enaml.imports():
    from .gui import Main


from psi.application import (
    install_exception_handler, load_paradigm_descriptions,
    setup_windows_console
)


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

    load_paradigm_descriptions()
    app = QtApplication()
    view = Main()
    view.show()
    app.start()
    return True
