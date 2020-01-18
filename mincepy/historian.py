from collections import namedtuple
import contextlib
import copy
import typing
from typing import Optional
import weakref

from . import archive
from . import defaults
from . import depositor
from . import exceptions
from . import inmemory
from . import process
from . import types
from . import utils

__all__ = ('Historian', 'set_historian', 'get_historian', 'INHERIT')

INHERIT = 'INHERIT'

CURRENT_HISTORIAN = None

ObjectEntry = namedtuple('ObjectEntry', 'ref obj')


class WrapperHelper(types.TypeHelper):
    """Wraps up an object type to perform the necessary Historian actions"""
    # pylint: disable=invalid-name
    TYPE = None
    TYPE_ID = None

    def __init__(self, obj_type: typing.Type[types.SavableComparable]):
        self.TYPE = obj_type
        self.TYPE_ID = obj_type.TYPE_ID
        super(WrapperHelper, self).__init__()

    def yield_hashables(self, obj, hasher):
        yield from self.TYPE.yield_hashables(obj, hasher)

    def eq(self, one, other) -> bool:
        return self.TYPE.__eq__(one, other)

    def save_instance_state(self, obj: types.Savable, referencer):
        return self.TYPE.save_instance_state(obj, referencer)

    def load_instance_state(self, obj, saved_state: types.Savable, referencer):
        return self.TYPE.load_instance_state(obj, saved_state, referencer)


class Historian(depositor.Referencer):

    def __init__(self, archive: archive.Archive, equators=()):
        self._archive = archive
        self._equator = types.Equator(defaults.get_default_equators() + equators)

        # Object that are up to date during a transaction
        self._up_to_date_objects = utils.WeakObjectIdDict()  # type: typing.MutableMapping[archive.Ref, typing.Any]
        # Object to record
        self._records = utils.WeakObjectIdDict()  # type: MutableMapping[typing.Any, archive.DataRecord]
        #  Reference -> object
        self._objects = weakref.WeakValueDictionary()  # type: MutableMapping[archive.Ref, typing.Any]
        self._staged = []
        self._transaction_count = 0

        self._type_registry = {}  # type: typing.MutableMapping[typing.Type, types.TypeHelper]
        self._type_ids = {}

    def save(self, obj, with_meta=None):
        """Save the object in the history producing a unique id"""
        record = self.save_object(obj, LatestReferencer(self))
        if with_meta is not None:
            self._archive.set_meta(record.obj_id, with_meta)
        return record.obj_id

    def save_as(self, obj, obj_id, with_meta=None):
        """Save an object with a given id.  Will write to the history of an object if the id already exists"""
        with self._transaction():
            # Do we have any records with that id
            current_obj = None
            current_record = None
            for stored, record in self._records.items():
                if record.obj_id == obj_id:
                    current_obj, current_record = stored, record

            if current_obj is not None:
                self._records.pop(current_obj)
            else:
                # Check the archive
                try:
                    current_record = self._archive.history(obj_id, -1)
                except exceptions.NotFound:
                    pass

            if current_record is not None:
                self._records[obj] = current_record
                self._objects[record.version] = obj
            # Now save the thing
            record = self.save_object(obj, LatestReferencer(self))

        if with_meta is not None:
            self._archive.set_meta(record.obj_id, with_meta)

        return obj_id

    def save_snapshot(self, obj, with_meta=None) -> archive.Ref:
        """
        Save a snapshot of the current state of the object.  Returns a reference that can
        then be used with load_snapshot()
        """
        record = self.save_object(obj, self)
        if with_meta is not None:
            self._archive.set_meta(record.obj_id, with_meta)
        return record.get_reference()

    def load(self, obj_id):
        """Load an object."""
        if not isinstance(obj_id, self._archive.get_id_type()):
            raise TypeError("Object id must be of type '{}'".format(self._archive.get_id_type()))

        ref = self._get_latest_snapshot_reference(obj_id)
        return self.load_object(ref, LatestReferencer(self))

    def load_snapshot(self, reference: archive.Ref):
        """Load a snapshot of the object using a reference."""
        return self.load_object(reference, self)

    def copy(self, obj):
        with self._transaction():
            record = self.save_object(obj, LatestReferencer(self))
            copy_builder = record.copy_builder(obj_id=self._archive.create_archive_id(),)
            obj_copy = copy.copy(obj)
            obj_copy_record = copy_builder.build()
            self._insert_object(obj_copy, obj_copy_record)
            self._staged.append(obj_copy_record)
        return obj_copy

    def history(self, obj_id, idx_or_slice='*') -> typing.Sequence[ObjectEntry]:
        """
        Get a sequence of object ids and instances from the history of the given object.

        Example:

        >>> car = Car('ferrari', 'white')
        >>> car_id = historian.save(car)
        >>> car.colour = 'red'
        >>> historian.save(car)
        >>> history = historian.history(car_id)
        >>> len(history)
        2
        >>> history[0].obj.colour == 'white'
        True
        >>> history[1].obj.colour == 'red'
        True
        >>> history[1].obj is car
        """
        snapshot_refs = self._archive.get_snapshot_refs(obj_id)
        indices = utils.to_slice(idx_or_slice)
        to_get = snapshot_refs[indices]
        return [ObjectEntry(ref, self.load_object(ref, self)) for ref in to_get]

    def load_object(self, reference, referencer):
        # Try getting the object from the our dict of up to date ones
        for obj, ref in self._up_to_date_objects.items():
            if reference == ref:
                return obj

        # Couldn't find it, so let's check if we have one and check if it is up to date
        record = self._archive.load(reference)
        try:
            obj = self._objects[reference]
        except KeyError:
            # Ok, just use the one from storage
            return self.two_step_load(record, referencer)
        else:
            # Need to check if the version we have is up to date
            with self._transaction() as transaction:
                loaded_obj = self.two_step_load(record, referencer)

                if self.hash(obj) == self.hash(loaded_obj) and self.eq(obj, loaded_obj):
                    # Objects identical, keep the one we have
                    transaction.rollback()
                else:
                    obj = loaded_obj

            return obj

    def save_object(self, obj, referencer) -> archive.DataRecord:
        # Check if we already have an up to date record
        if obj in self._up_to_date_objects:
            return self._records[obj]

        # Ok, have to save it
        helper = self._ensure_compatible(type(obj))
        current_hash = self.hash(obj)

        try:
            # Let's see if we have a record at all
            record = self._records[obj]
        except KeyError:
            # Completely new
            try:
                created_in = self.get_current_record(process.Process.current_process()).obj_id
            except exceptions.NotFound:
                created_in = None

            builder = archive.DataRecord.get_builder(type_id=helper.TYPE_ID,
                                                     obj_id=self._archive.create_archive_id(),
                                                     created_in=created_in,
                                                     version=0,
                                                     snapshot_hash=current_hash)
            return self.two_step_save(obj, builder)
        else:
            # Check if our record is up to date
            with self._transaction() as transaction:
                loaded_obj = self.two_step_load(record, referencer)
                if current_hash == record.snapshot_hash and self.eq(obj, loaded_obj):
                    # Objects identical
                    transaction.rollback()
                else:
                    builder = record.child_builder()
                    builder.snapshot_hash = current_hash
                    record = self.two_step_save(obj, builder)

            return record

    def get_meta(self, obj_id):
        if isinstance(obj_id, archive.Ref):
            obj_id = obj_id.obj_id
        return self._archive.get_meta(obj_id)

    def set_meta(self, obj_id, meta):
        if isinstance(obj_id, archive.Ref):
            obj_id = obj_id.obj_id
        self._archive.set_meta(obj_id, meta)

    def get_obj_type_id(self, obj_type):
        return self._type_registry[obj_type].TYPE_ID

    def get_helper(self, type_id) -> types.TypeHelper:
        return self.get_helper_from_obj_type(self._type_ids[type_id])

    def get_helper_from_obj_type(self, obj_type) -> types.TypeHelper:
        return self._type_registry[obj_type]

    def get_current_record(self, obj) -> archive.DataRecord:
        try:
            return self._records[obj]
        except KeyError:
            raise exceptions.NotFound("Unknown object '{}'".format(obj))

    def hash(self, obj):
        return self._equator.hash(obj)

    def eq(self, one, other):  # pylint: disable=invalid-name
        return self._equator.eq(one, other)

    def register_type(self, obj_class_or_helper: [types.TypeHelper, typing.Type[types.SavableComparable]]):
        if isinstance(obj_class_or_helper, types.TypeHelper):
            helper = obj_class_or_helper
        else:
            if not issubclass(obj_class_or_helper, types.SavableComparable):
                raise TypeError("Type '{}' is nether a TypeHelper nor a SavableComparable".format(obj_class_or_helper))
            helper = WrapperHelper(obj_class_or_helper)

        self._type_registry[helper.TYPE] = helper
        self._type_ids[helper.TYPE_ID] = helper.TYPE
        self._equator.add_equator(helper)

    def find(self, obj_type=None, criteria=None, limit=0):
        """Find entries in the archive"""
        obj_type_id = self.get_obj_type_id(obj_type) if obj_type is not None else None
        results = self._archive.find(obj_type_id=obj_type_id, criteria=criteria, limit=limit)
        return [self.load(result.obj_id) for result in results]

    def created_in(self, obj_or_identifier):
        """Return the id of the object that created the passed object"""
        try:
            return self.get_current_record(obj_or_identifier).created_in
        except exceptions.NotFound:
            return self._archive.load(self._get_latest_snapshot_reference(obj_or_identifier)).created_in

    def _get_latest_snapshot_reference(self, obj_id) -> archive.Ref:
        """Given an object id this will return a refernce to the latest snapshot"""
        return self._archive.get_snapshot_refs(obj_id)[-1]

    def ref(self, obj) -> Optional[archive.Ref]:
        """Get a reference id to an object."""
        if obj is None:
            return None

        return self.save_object(obj, self).get_reference()

    def deref(self, reference: Optional[archive.Ref]):
        """Get the object from a reference"""
        if reference is None:
            return None

        return self.load_object(reference, self)
        # return self.load(reference.obj_id)

    def encode(self, obj):
        obj_type = type(obj)
        if obj_type in self._get_primitive_types():
            # Deal with the special containers by encoding their values if need be
            if isinstance(obj, list):
                return [self.encode(entry) for entry in obj]
            if isinstance(obj, dict):
                return {key: self.encode(value) for key, value in obj.items()}

            return obj

        # Non base types should always be converted to encoded dictionaries
        helper = self._ensure_compatible(obj_type)
        saved_state = helper.save_instance_state(obj, self)
        return {archive.TYPE_ID: helper.TYPE_ID, archive.STATE: self.encode(saved_state)}

    def decode(self, encoded, referencer: depositor.Referencer):
        """Decode the saved state recreating any saved objects within."""
        enc_type = type(encoded)
        primitives = self._get_primitive_types()
        if enc_type not in primitives:
            raise TypeError("Encoded type must be one of '{}', got '{}'".format(primitives, enc_type))

        if enc_type is dict:
            if archive.TYPE_ID in encoded:
                # Assume object encoded as dictionary, decode it as such
                type_id = encoded[archive.TYPE_ID]
                helper = self.get_helper(type_id)
                saved_state = self.decode(encoded[archive.STATE], referencer)
                with self.create_from(saved_state, helper, referencer) as obj:
                    return obj
            else:
                return {key: self.decode(value, referencer) for key, value in encoded.items()}
        if enc_type is list:
            return [self.decode(value, referencer) for value in encoded]

        # No decoding to be done
        return encoded

    @contextlib.contextmanager
    def create_from(self, encoded_saved_state, helper: types.TypeHelper, referencer: depositor.Referencer):
        """
        Loading of an object takes place in two steps, analogously to the way python
        creates objects.  First a 'blank' object is created and and yielded by this
        context manager.  Then loading is finished in load_instance_state.  Naturally,
        the state of the object should not be relied upon until the context exits.
        """
        new_obj = helper.new(encoded_saved_state)
        try:
            yield new_obj
        finally:
            decoded = self.decode(encoded_saved_state, referencer)
            helper.load_instance_state(new_obj, decoded, referencer)

    def two_step_load(self, record: archive.DataRecord, referencer):
        try:
            helper = self.get_helper(record.type_id)
        except KeyError:
            raise ValueError("Type with id '{}' has not been registered".format(record.type_id))

        with self._transaction():
            with self.create_from(record.state, helper, referencer) as obj:
                self._insert_object(obj, record)
        return obj

    def two_step_save(self, obj, builder):
        with self._transaction():
            ref = archive.Ref(builder.obj_id, builder.version)
            self._up_to_date_objects[obj] = ref
            self._objects[ref] = obj
            builder.update(self.encode(obj))
            record = builder.build()
            self._records[obj] = record
            self._staged.append(record)
        return record

    @contextlib.contextmanager
    def _transaction(self):
        """
        Carry out a transaction.  A checkpoint it created at the beginning so that the state can be rolled back
        if need be, otherwise the state changes are committed at the end of the context.

        e.g.:
        ```
        with self._transaction() as transaction:
            # Do stuff
        # Changes committed
        ```
        or
        ```
        with self._transaction() as transaction:
            # Do stuff
            transaction.rollback()
        # Changes cancelled
        """
        initial_records = copy.copy(self._records)
        initial_objects = copy.copy(self._objects)
        initial_up_to_date_objects = copy.copy(self._up_to_date_objects)
        transaction = Transaction()
        self._transaction_count += 1
        try:
            yield transaction
        except RollbackTransaction:
            self._records = initial_records
            self._objects = initial_objects
            self._up_to_date_objects = initial_up_to_date_objects
        finally:

            self._transaction_count -= 1
            if not self._transaction_count:
                self._up_to_date_objects = utils.WeakObjectIdDict()
                # Save any records that were staged for archiving
                if self._staged:
                    self._archive.save_many(self._staged)
                    self._staged = []

    def _get_primitive_types(self) -> tuple:
        """Get a tuple of the primitive types"""
        return types.BASE_TYPES + (self._archive.get_id_type(),)

    def _ensure_compatible(self, obj_type: typing.Type):
        if obj_type not in self._type_registry:
            if issubclass(obj_type, types.SavableComparable):
                # Make a wrapper
                self.register_type(WrapperHelper(obj_type))
            else:
                raise TypeError(
                    "Object type '{}' is incompatible with the historian, either subclass from SavableComparable or "
                    "provide a helper".format(obj_type))

        return self._type_registry[obj_type]

    def _insert_object(self, obj, record):
        self._up_to_date_objects[obj] = record.get_reference()
        self._objects[record.get_reference()] = obj
        self._records[obj] = record


class RollbackTransaction(Exception):
    pass


class Transaction:

    @staticmethod
    def rollback():
        raise RollbackTransaction


class LatestReferencer(depositor.Referencer):

    def __init__(self, historian: Historian):
        self._historian = historian

    def ref(self, obj):
        return self._historian.ref(obj)

    def deref(self, reference):
        if reference is None:
            return None

        ref = self._historian._get_latest_snapshot_reference(reference.obj_id)
        return self._historian.load_object(ref, self)


def create_default_historian() -> Historian:
    return Historian(inmemory.InMemory())


def get_historian() -> Historian:
    global CURRENT_HISTORIAN  # pylint: disable=global-statement
    if CURRENT_HISTORIAN is None:
        CURRENT_HISTORIAN = create_default_historian()
    return CURRENT_HISTORIAN


def set_historian(historian: Historian):
    global CURRENT_HISTORIAN  # pylint: disable=global-statement
    CURRENT_HISTORIAN = historian
