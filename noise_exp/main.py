from enaml.qt.qt_application import QtApplication
import enaml
with enaml.imports():
    from .gui import Main


from psi.application import load_paradigm_descriptions


def main():
    import argparse
    parser = argparse.ArgumentParser('noise-exp')
    args = parser.parse_args()
    load_paradigm_descriptions()
    app = QtApplication()
    view = Main()
    #view.settings.load_config(args.config)
    view.show()
    app.start()
    return True
