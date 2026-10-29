from collections import OrderedDict


class ByteCache:
    """In-memory cache with a total size limit; the least recently used items are dropped first.

    Keys are git SHAs (blobs, trees), whose content never changes, so nothing can go stale.
    The cache is lost on restart, which only costs a re-download.
    """

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self._items: OrderedDict[str, bytes] = OrderedDict()
        self._size = 0

    def get(self, key: str) -> bytes | None:
        value = self._items.get(key)
        if value is not None:
            self._items.move_to_end(key)
        return value

    def put(self, key: str, value: bytes) -> None:
        if len(value) > self.max_bytes:
            return
        if key in self._items:
            self._size -= len(self._items.pop(key))
        self._items[key] = value
        self._size += len(value)
        while self._size > self.max_bytes:
            _, oldest = self._items.popitem(last=False)
            self._size -= len(oldest)
