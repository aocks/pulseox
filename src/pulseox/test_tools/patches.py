"""Tools for patching things for tests.
"""

import os


class EnvPatcher:
    """Class to patch environment.
    """

    _patches = {}

    @classmethod
    def patch(cls, name, value):
        "Override env var with given `name` to `value` (undo with unpatch)."
        if name in cls._patches:
            raise ValueError(f'Refusing to re-patch existing {name=}')
        cls._patches[name] = os.environ.get(name, None)
        os.environ[name] = value

    @classmethod
    def unpatch(cls):
        """Undo previous patches
        """
        for name in list(cls._patches):
            value = cls._patches.pop(name)
            if value is not None:
                os.environ[name] = value
            else:
                del os.environ[name]
