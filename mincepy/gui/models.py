from collections import namedtuple
from functools import partial
import logging
import typing

from bidict import bidict
import PySide2
from PySide2 import QtCore, QtGui
from PySide2.QtCore import QObject, Signal, Qt, QModelIndex

import mincepy
from mincepy import archive
from . import common

__all__ = 'DbModel', 'SnapshotRecord'

logger = logging.getLogger(__name__)

DATA_RECORD_MAPPING = bidict({"[{}]".format(entry): entry for entry in mincepy.DataRecord._fields})

UNSET = ''  # The value printed for records that don't have a particular attribute

TOOLTIPS = {
    DATA_RECORD_MAPPING.inverse[archive.TYPE_ID]: 'Object type',
    DATA_RECORD_MAPPING.inverse[archive.CREATION_TIME]: 'Creation time',
    DATA_RECORD_MAPPING.inverse[archive.SNAPSHOT_TIME]: 'Last modification time',
    DATA_RECORD_MAPPING.inverse[archive.VERSION]: 'Version',
}

SnapshotRecord = namedtuple("SnapshotRecord", 'snapshot record')


def pretty_type_string(obj_type: typing.Type):
    """Given an type will return a simple type string"""
    type_str = str(obj_type)
    if type_str.startswith('<class '):
        return type_str[8:-2]
    return type_str


class DbModel(QObject):
    # Signals
    historian_changed = Signal(mincepy.Historian)

    def __init__(self):
        super().__init__()
        self._historian = None

    @property
    def historian(self) -> mincepy.Historian:
        return self._historian

    @historian.setter
    def historian(self, historian):
        self._historian = historian
        self.historian_changed.emit(self._historian)


class DataRecordQueryModel(QtCore.QAbstractTableModel):
    # Signals
    type_restriction_changed = Signal(object)
    sort_changed = Signal(dict)

    def __init__(self, db_model: DbModel, executor=common.default_executor, parent=None):
        super().__init__(parent)
        self._db_model = db_model
        self._query = {}
        self._results = None
        self._sort = None
        self._type_restriction = None
        self._column_names = mincepy.DataRecord._fields
        self._update_future = None

        self._executor = executor
        self._new_results.connect(self._inject_results)

        # If the historian changes then we get invalidated
        self._db_model.historian_changed.connect(lambda hist: self._invalidate_results())

    @property
    def db_model(self):
        return self._db_model

    @property
    def column_names(self):
        return self._column_names

    def get_query(self):
        return self._query

    def set_query(self, query: dict):
        """Set the query that will be passed to historian.find()"""
        self._query = query
        self._invalidate_results()

    def set_type_restriction(self, type_id):
        if type_id == self._type_restriction:
            return

        self._type_restriction = type_id
        self._invalidate_results()
        self.type_restriction_changed.emit(self._type_restriction)

    def get_type_restriction(self):
        return self._type_restriction

    def set_sort(self, sort):
        if sort == self._sort:
            return

        self._sort = sort
        self._invalidate_results()
        self.sort_changed.emit(self._sort)

    def get_sort(self):
        return self._sort

    def get_records(self):
        return self._results

    def refresh(self):
        self._invalidate_results()

    def rowCount(self, _parent: QtCore.QModelIndex = QModelIndex()) -> int:
        if self._results is None:
            return 0

        return len(self._results)

    def columnCount(self, _parent: QtCore.QModelIndex = QModelIndex()) -> int:
        return len(self.column_names)

    def headerData(self, section: int, orientation: PySide2.QtCore.Qt.Orientation, role: int = ...) -> typing.Any:
        if role != Qt.DisplayRole:
            return None

        if orientation == QtCore.Qt.Orientation.Horizontal:
            return self.column_names[section]

        return str(self._results[section])

    def data(self, index: PySide2.QtCore.QModelIndex, role: int = ...) -> typing.Any:
        if role == Qt.DisplayRole:
            value = getattr(self._results[index.row()], self.column_names[index.column()])
            return str(value)

        return None

    def _update_results(self):
        if self._query is None or self._db_model.historian is None:
            self._results = []
        else:
            query = self._query.copy()
            if self._type_restriction is not None:
                query['obj_type'] = self._type_restriction
            if self._sort is not None:
                query['sort'] = self._sort

            self._results = []
            self._update_future = self._executor(partial(self._perform_query, query), msg="Querying...", blocking=False)

    def _invalidate_results(self):
        self.beginResetModel()
        self._results = None
        self.endResetModel()
        self._update_results()

    def _perform_query(self, query, batch_size=4):
        logging.debug("Starting query: %s", query)

        total = 0
        batch = []
        for result in self._db_model.historian.find(**query, as_objects=False):
            batch.append(result)
            if len(batch) == batch_size:
                self._new_results.emit(batch)
                batch = []
            total += 1

        if batch:
            # Emit the last batch
            self._new_results.emit(batch)

        logging.debug('Finished query, got %s results', total)

    _new_results = Signal(list)

    @QtCore.Slot(list)
    def _inject_results(self, batch: list):
        """As a query is executed batches of results as emitted and passed to this callback for insertion"""
        first = len(self._results)
        last = first + len(batch) - 1
        self.beginInsertRows(QModelIndex(), first, last)
        self._results.extend(batch)
        self.endInsertRows()


class EntriesTable(QtCore.QAbstractTableModel):
    ARCHIVE_COLUMNS = (archive.OBJ_ID, archive.TYPE_ID, archive.CREATION_TIME, archive.SNAPSHOT_TIME, archive.VERSION,
                       archive.STATE)
    DEFAULT_COLUMNS = tuple(DATA_RECORD_MAPPING.inverse[label] for label in ARCHIVE_COLUMNS)

    def __init__(self, query_model: DataRecordQueryModel, parent=None):
        super().__init__(parent)
        self._query_model = query_model
        self._query_model.modelReset.connect(self._invalidate)
        self._query_model.rowsInserted.connect(self._query_rows_inserted)

        self._columns = list(self.DEFAULT_COLUMNS)
        self._show_objects = True

        self._snapshots_cache = {}

    def get_records(self):
        return self._query_model.get_records()

    @property
    def query_model(self):
        return self._query_model

    def get_record(self, row) -> typing.Optional[mincepy.DataRecord]:
        if row < 0 or row >= self.rowCount():
            return None

        return self.get_records()[row]

    def get_snapshot(self, row: int):
        ref = self.get_record(row).get_reference()
        if ref not in self._snapshots_cache:
            historian = self._query_model.db_model.historian
            try:
                self._snapshots_cache[ref] = historian.load_snapshot(ref)
            except TypeError:
                self._snapshots_cache[ref] = None

        return self._snapshots_cache[ref]

    def get_show_as_objects(self):
        return self._show_objects

    def set_show_as_objects(self, as_objects):
        if self._show_objects != as_objects:
            self._show_objects = as_objects
            # Remove the old columns, if there are any to be removed
            if len(self._columns) > len(self.DEFAULT_COLUMNS):
                first = len(self.DEFAULT_COLUMNS)
                last = len(self._columns) - 1

                self.beginRemoveColumns(QModelIndex(), first, last)
                self._reset_columns()
                self.endRemoveColumns()

            # Now add the new ones
            columns = set()
            for row in range(self.rowCount()):
                columns.update(self._get_columns_for(row))

            if columns:
                # Convert to list and sort alphabetically
                new_columns = list(columns)
                new_columns.sort()
                self._insert_columns(new_columns)

    def refresh(self):
        # As the query to refresh from the database
        self._query_model.refresh()

    def rowCount(self, _parent: PySide2.QtCore.QModelIndex = ...) -> int:
        return self._query_model.rowCount()

    def columnCount(self, _parent: PySide2.QtCore.QModelIndex = ...) -> int:
        return len(self._columns)

    def headerData(self, section: int, orientation: PySide2.QtCore.Qt.Orientation, role: int = ...) -> typing.Any:
        if role != Qt.DisplayRole:
            return None

        if orientation == QtCore.Qt.Orientation.Horizontal:
            if section >= len(self._columns):
                return None
            return self._columns[section]

        if orientation == QtCore.Qt.Orientation.Vertical:
            return str(section)

        return None

    def data(self, index: PySide2.QtCore.QModelIndex, role: int = ...) -> typing.Any:
        column_name = self._columns[index.column()]
        if role == Qt.DisplayRole:
            value = self._get_value_string(index.row(), index.column())
            return value
        if role == Qt.FontRole:
            if column_name in DATA_RECORD_MAPPING:
                font = QtGui.QFont()
                font.setItalic(True)
                return font
        if role == Qt.ToolTipRole:
            try:
                return TOOLTIPS[column_name]
            except KeyError:
                pass

        return None

    def sort(self, column: int, order: PySide2.QtCore.Qt.SortOrder = ...):
        column_name = self._columns[column]
        try:
            sort_criterion = DATA_RECORD_MAPPING[column_name]
        except KeyError:
            if self._show_objects:
                # We can't deal with sorting objects at the moment
                return
            sort_criterion = "state.{}".format(column_name)

        sort_dict = {sort_criterion: mincepy.ASCENDING if order == Qt.AscendingOrder else mincepy.DESCENDING}
        self._query_model.set_sort(sort_dict)

    def _invalidate(self):
        self.beginResetModel()
        self._snapshots_cache = {}
        self._reset_columns()
        self.endResetModel()

    def _get_snapshot_state(self, record):
        if self._show_objects:
            historian = self._query_model.db_model.historian
            try:
                return historian.load_snapshot(record.get_reference())
            except TypeError:
                pass  # Fall back to displaying the state

        return record.state

    def _get_columns_for(self, row: int) -> tuple:
        if self.get_show_as_objects():
            obj = self.get_snapshot(row)
            try:
                state = vars(obj)
            except TypeError:
                state = {}
        else:
            state = self.get_record(row).state

        if isinstance(state, dict):
            return tuple(state.keys())

        return ()

    def _get_value_string(self, row: int, column: int) -> str:
        column_name = self._columns[column]
        record = self.get_record(row)

        if column < len(self.DEFAULT_COLUMNS):
            original_name = DATA_RECORD_MAPPING[column_name]
            record_value = record._asdict()[original_name]

            # Special case to show type ids as the class name
            if original_name == archive.TYPE_ID:
                try:
                    historian = self._query_model.db_model.historian
                    return pretty_type_string(historian.get_obj_type(record_value))
                except TypeError:
                    pass
            return str(record_value)

        # The column is a custom attribute of the item
        if self.get_show_as_objects():
            snapshot = self.get_snapshot(row)
            try:
                state = vars(snapshot)
            except TypeError:
                state = {}
        else:
            state = record.state

        # The state in the record needn't be a dict so we check
        if isinstance(state, dict):
            return str(state.get(column_name, UNSET))

        return UNSET

    def _query_rows_inserted(self, _parent: QModelIndex, first: int, last: int):
        """Called when there are new entries inserted into the entries table"""

        self.beginInsertRows(QModelIndex(), first, last)

        columns = set()  # Keep track of all the columns in this batch
        for row in range(first, last + 1):
            columns.update(self._get_columns_for(row))

        self.endInsertRows()

        # Check if the columns need updating
        columns -= set(self._columns)
        if columns:
            # There are new columns to insert
            cols = list(columns)
            cols.sort()
            self._insert_columns(cols)

    def _insert_columns(self, new_columns: typing.Sequence):
        """Add new columns to our existing ones"""
        first_col = len(self._columns)
        last_col = first_col + len(new_columns) - 1
        self.beginInsertColumns(QModelIndex(), first_col, last_col)
        self._columns.extend(new_columns)
        self.endInsertColumns()

    def _reset_columns(self):
        """Reset the columns back to the default internally.  This should only be done between either
        an model invalidation or appropriate removeColumns call
        """
        self._columns = list(self.DEFAULT_COLUMNS)
