import sys

from PySide2 import QtWidgets

from . import views

__all__ = ('run_application',)


def run_application(create_historian_callback=None):
    app = QtWidgets.QApplication([])
    widget = views.MincepyWidget(create_historian_callback)
    widget.resize(800, 600)
    widget.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    run_application()
