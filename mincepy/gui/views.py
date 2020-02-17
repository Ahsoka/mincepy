from concurrent.futures import ThreadPoolExecutor

from PySide2 import QtCore, QtWidgets
from PySide2.QtCore import Signal

import mincepy
from . import models
from . import tree_models

__all__ = 'TypeDropDown', 'ConnectionWidget', 'MincepyWidget'


class TypeDropDown(QtWidgets.QComboBox):
    """Drop down combo box that lists the types available in archive"""
    ALL = None

    # Signals
    selected_type_changed = Signal(object)

    def __init__(self, query_model: models.DataRecordQueryModel, parent=None):
        super().__init__(parent)
        self._query_model = query_model
        query_model.db_model.historian_changed.connect(self._update)

        self.setEditable(True)
        self._types = [None]
        self.addItem(self.ALL)

        def selection_changed(index):
            restrict_type = self._types[index]
            self.selected_type_changed.emit(restrict_type)

        self.currentIndexChanged.connect(selection_changed)

    @property
    def _historian(self):
        return self._query_model.db_model.historian

    def _update(self):
        self.clear()

        results = self._historian.get_archive().find()
        self._types = [None]
        self._types.extend(list(set(result.type_id for result in results)))

        type_names = self._get_type_names(self._types)

        self.addItems(type_names)
        completer = QtWidgets.QCompleter(type_names)
        self.setCompleter(completer)

    def _get_type_names(self, types):
        type_names = []
        for type_id in types:
            try:
                helper = self._historian.get_helper(type_id)
            except TypeError:
                type_names.append(str(type_id))
            else:
                type_names.append(mincepy.analysis.get_type_name(helper.TYPE))

        return type_names


class FilterControlPanel(QtWidgets.QWidget):
    # Signals
    display_as_class_changed = Signal(object)

    def __init__(self, entries_table: models.EntriesTable, parent=None):
        super().__init__(parent)
        self._entries_table = entries_table

        refresh = QtWidgets.QPushButton("Refresh")
        refresh.clicked.connect(self._entries_table.refresh)

        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(self._create_type_drop_down())
        layout.addWidget(self._create_display_as_class_checkbox())
        layout.addWidget(refresh)
        self.setLayout(layout)

    def _create_display_as_class_checkbox(self):
        # Show snapshot class checkbox
        display_class_checkbox = QtWidgets.QCheckBox('Display as class', self)
        display_class_checkbox.setCheckState(QtCore.Qt.Checked)
        display_class_checkbox.stateChanged.connect(
            lambda state: self._entries_table.set_show_as_objects(state == QtCore.Qt.Checked))
        self._entries_table.set_show_as_objects(display_class_checkbox.checkState() == QtCore.Qt.Checked)

        return display_class_checkbox

    def _create_type_drop_down(self):
        type_drop_down = TypeDropDown(self._entries_table.query_model, self)
        type_drop_down.selected_type_changed.connect(self._entries_table.query_model.set_type_restriction)

        # Create an lay out the panel
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(QtWidgets.QLabel("Restrict type:"))
        layout.addWidget(type_drop_down)
        panel.setLayout(layout)

        return panel


class ConnectionWidget(QtWidgets.QWidget):
    # Signals
    connection_requested = Signal(str)

    def __init__(self, default_connect_uri='', parent=None):
        super().__init__(parent)
        self._connection_string = QtWidgets.QLineEdit(self)
        self._connection_string.setText(default_connect_uri)
        self._connect_button = QtWidgets.QPushButton('Connect', self)

        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(self._connection_string)
        layout.addWidget(self._connect_button)
        self.setLayout(layout)

        self._connect_button.clicked.connect(self._connect_pushed)

    def _connect_pushed(self):
        string = self._connection_string.text()
        self.connection_requested.emit(string)


class MincepyWidget(QtWidgets.QWidget):

    def __init__(self, default_connect_uri='', create_historian_callback=None):
        super().__init__()

        def default_create_historian(uri) -> mincepy.Historian:
            historian = mincepy.create_historian(uri)
            mincepy.set_historian(historian)
            return historian

        self._executor = ThreadPoolExecutor()

        self._create_historian_callback = create_historian_callback or default_create_historian

        # The model
        self._db_model = models.DbModel()
        self._data_records = models.DataRecordQueryModel(self._db_model, executor=self._executor, parent=self)

        # Set up the connect panel of the GUI
        connect_panel = ConnectionWidget(default_connect_uri, self)
        connect_panel.connection_requested.connect(self._connect)

        self._entries_table = models.EntriesTable(self._data_records, parent=self)

        control_panel = FilterControlPanel(self._entries_table, self)

        self.layout = QtWidgets.QVBoxLayout()
        self.layout.addWidget(connect_panel)
        self.layout.addWidget(control_panel)
        self.layout.addWidget(self._create_display_panel(self._entries_table))
        self.setLayout(self.layout)

    @property
    def db_model(self):
        return self._db_model

    def _connect(self, uri):
        try:
            historian = self._create_historian_callback(uri)
            self._db_model.historian = historian
        except Exception as exc:
            err_msg = "Error creating historian with uri '{}':\n{}".format(uri, exc)
            QtWidgets.QErrorMessage(self).showMessage(err_msg)

    def _create_display_panel(self, entries_table: models.EntriesTable):
        panel = QtWidgets.QSplitter(QtCore.Qt.Vertical)

        entries_view = QtWidgets.QTableView(panel)
        entries_view.setSortingEnabled(True)
        entries_view.setModel(entries_table)

        record_tree = tree_models.RecordTree(parent=panel)
        record_tree_view = QtWidgets.QTreeView(panel)
        record_tree_view.setModel(record_tree)

        def row_changed(current, _previous):
            entries_table = self._entries_table
            record = entries_table.get_record(current.row())
            snapshot = entries_table.get_snapshot(current.row())
            record_tree.set_record(record, snapshot)

        entries_view.selectionModel().currentRowChanged.connect(row_changed)

        panel.addWidget(entries_view)
        panel.addWidget(record_tree_view)

        return panel
