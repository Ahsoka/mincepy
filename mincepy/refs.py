"""References module"""
import uuid

from . import records
from . import types

__all__ = ('ObjRef',)


class ObjRef(types.SavableObject):
    """A reference to an object instance"""
    TYPE_ID = uuid.UUID('633c7035-64fe-4d87-a91e-3b7abd8a6a28')

    def __init__(self, obj):
        super().__init__()
        self._obj = obj
        self._ref = None
        self._loader = None

    def __str__(self):
        desc = "ref: "
        if self._obj is not None:
            desc += str(self._obj)
        else:
            desc += str(self._ref)
        return desc

    def __call__(self):
        if self._obj is None:
            if self._ref is None:
                raise RuntimeError("Cannot dereference a None reference")
            # Cache the object
            self._obj = self._loader.load(self._ref)
            assert self._obj is not None, "Loader did not load object"
            self._ref = None
            self._loader = None

        return self._obj

    def __eq__(self, other):
        return self is other

    def yield_hashables(self, hasher):
        yield from hasher.yield_hashables(self._ref)

    def save_instance_state(self, saver):
        ref = self._ref
        if ref is None:
            # This should mean that we have loaded the object via the 'call' method previously
            assert self._obj is not None
            ref = saver.ref(self._obj)

        return [ref.obj_id, ref.version]

    def load_instance_state(self, saved_state, loader):
        self._ref = records.Ref(*saved_state)
        self._obj = None
        self._loader = loader


HISTORIAN_TYPES = (ObjRef,)
