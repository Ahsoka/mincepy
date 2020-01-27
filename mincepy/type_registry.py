from typing import Type, MutableMapping, Iterable, Any

from . import helpers
from . import types


class TypeRegistry:

    def __init__(self):
        self._helpers = {}  # type: MutableMapping[Type, helpers.TypeHelper]
        self._type_ids = {}  # type: MutableMapping[Any, Type]

    def __contains__(self, item: Type) -> bool:
        return item in self._helpers

    def register_type(self, obj_class_or_helper: [helpers.TypeHelper, Type[types.Object]]) -> helpers.WrapperHelper:
        if isinstance(obj_class_or_helper, helpers.TypeHelper):
            helper = obj_class_or_helper
        else:
            if not issubclass(obj_class_or_helper, types.Object):
                raise TypeError("Type '{}' is nether a TypeHelper nor a SavableComparable".format(obj_class_or_helper))
            helper = helpers.WrapperHelper(obj_class_or_helper)

        obj_types = helper.TYPE if isinstance(helper.TYPE, Iterable) else (helper.TYPE,)

        for obj_type in obj_types:
            self._helpers[obj_type] = helper
            self._type_ids[helper.TYPE_ID] = obj_type

        return helper

    def get_type_id(self, obj_type):
        try:
            # Try a direct lookup first
            return self._helpers[obj_type].TYPE_ID
        except KeyError:
            # Try an issubclass lookup as a backup
            for type_id, known_type in self._type_ids.items():
                if issubclass(obj_type, known_type):
                    return type_id
            raise ValueError("Type '{}' is not known".format(obj_type))

    def get_helper_from_type_id(self, type_id) -> helpers.TypeHelper:
        return self.get_helper_from_obj_type(self._type_ids[type_id])

    def get_helper_from_obj_type(self, obj_type: Type) -> helpers.TypeHelper:
        try:
            # Try the direct lookup
            return self._helpers[obj_type]
        except KeyError:
            # Do the full issubclass lookup
            for known_type, helper in self._helpers.items():
                if issubclass(obj_type, known_type):
                    return helper
            raise ValueError("Type '{}' has not been registered".format(obj_type))