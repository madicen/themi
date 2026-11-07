"""CR3: a typed registry of what modules provide.

Objects are filed under their class's name. Look one up by its class, or, where importing
the class would be an import cycle, by a `Key` that names it:

    board = services.get(TaskBoard)          # raises ModuleError when nobody provides it
    triage = services.maybe(keys.triage)      # EmailTriage | None

Keys live on the features' side (`themi.core.keys`), never in core, and import their
classes only for type checking, so using one imports nothing at runtime.
"""

from __future__ import annotations

from typing import overload

from themi.modules.base import ModuleError


class Key[T]:
    """The name an object is filed under: its class's `__name__`."""

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"Key({self.name!r})"


def name_of(key: type | Key) -> str:
    return key.name if isinstance(key, Key) else key.__name__


class Registry:
    """Mixed into `Services`. Providing again replaces, as setting an attribute did; the
    module context is what refuses two modules providing the same thing."""

    _provided: dict[str, object]

    def _registry(self) -> dict[str, object]:
        try:
            return self._provided
        except AttributeError:
            self._provided = {}
            return self._provided

    @overload
    def provide[T](self, key: Key[T], obj: T | None) -> None: ...
    @overload
    def provide[T](self, key: type[T], obj: T | None) -> None: ...
    def provide(self, key: type | Key, obj: object) -> None:
        """File `obj` under `key`; None takes it away."""
        if obj is None:
            self._registry().pop(name_of(key), None)
        else:
            self._registry()[name_of(key)] = obj

    @overload
    def maybe[T](self, key: Key[T]) -> T | None: ...
    @overload
    def maybe[T](self, key: type[T]) -> T | None: ...
    def maybe(self, key: type | Key) -> object | None:
        return self._registry().get(name_of(key))

    @overload
    def get[T](self, key: Key[T]) -> T: ...
    @overload
    def get[T](self, key: type[T]) -> T: ...
    def get(self, key: type | Key) -> object:
        found = self._registry().get(name_of(key))
        if found is None:
            raise ModuleError(f"nothing provides {name_of(key)}: is its module installed?")
        return found

    def provided(self) -> list[str]:
        return sorted(self._registry())
