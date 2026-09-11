import abc
from pathlib import Path

from ..helpers import unlink_with_retry
from .file_persistent_dict import FilePersistentDict
from .persistent_dict import PersistentDict
from .redis_persistent_dict import RedisPersistentDict


class StorageBackend(abc.ABC):
    """Creates and owns the persistent dicts behind ``app.storage``.

    Subclass this to keep ``app.storage.general``, ``app.storage.user`` and ``app.storage.tab``
    somewhere other than the built-in file and Redis backends,
    and assign an instance to ``Storage.backend`` before the app starts.
    """

    @abc.abstractmethod
    def create(self, id: str, *, ttl: float | None = None) -> PersistentDict:  # pylint: disable=redefined-builtin
        """Create a persistent dict for the given storage ID.

        ``ttl`` is the number of seconds after which the data may expire, or ``None`` to keep it indefinitely.
        Backends without expiry support can ignore it, because NiceGUI prunes tab storage on a timer as well.
        """

    @property
    def persists_tab_storage(self) -> bool:
        """Whether this backend can persist ``app.storage.tab``.

        If ``False``, NiceGUI keeps tab storage in a volatile dict that is lost when the server restarts.
        """
        return False

    def clear(self) -> None:  # noqa: B027
        """Remove all data owned by this backend.

        This is an optional hook, like ``PersistentDict.close()``, so backends that have nothing to tear down
        can leave it alone.
        It is called from the synchronous ``app.storage.clear()``,
        so backends that delete asynchronously should schedule a background task.
        """


class FileStorageBackend(StorageBackend):
    """Stores each dict as a JSON file inside a directory."""

    def __init__(self, path: Path, *, encoding: str = 'utf-8', indent: bool = False) -> None:
        self.path = path
        self.encoding = encoding
        self.indent = indent

    def create(self, id: str, *, ttl: float | None = None) -> PersistentDict:  # pylint: disable=redefined-builtin
        _ = ttl  # files do not expire on their own; tab storage is pruned on a timer instead
        return FilePersistentDict(self.path / f'storage-{id}.json', encoding=self.encoding, indent=self.indent)

    def clear(self) -> None:
        for filepath in self.path.glob('storage-*.json'):
            unlink_with_retry(filepath, missing_ok=True)
        for tmp_path in self.path.glob('storage-*.json.tmp'):
            unlink_with_retry(tmp_path, missing_ok=True)  # an in-flight backup releases it from a worker thread
        if self.path.exists():
            self.path.rmdir()


class RedisStorageBackend(StorageBackend):
    """Stores each dict under a Redis key so that multiple instances share the data."""

    def __init__(self, url: str, *, key_prefix: str = 'nicegui:') -> None:
        self.url = url
        self.key_prefix = key_prefix

    def create(self, id: str, *, ttl: float | None = None) -> PersistentDict:  # pylint: disable=redefined-builtin
        return RedisPersistentDict(url=self.url, id=id, key_prefix=self.key_prefix,
                                   ttl=None if ttl is None else int(ttl))

    @property
    def persists_tab_storage(self) -> bool:
        return True
