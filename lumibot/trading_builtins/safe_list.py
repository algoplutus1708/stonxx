from _thread import RLock as rlock_type


_MISSING = object()


class SafeList:
    def __init__(self, lock, initial=None):
        # PERF: backtesting is single-threaded; allow `lock=None` to skip lock overhead.
        if lock is not None and not isinstance(lock, rlock_type):
            raise ValueError("lock must be a threading.RLock")

        if initial is None:
            initial = []
        self.__lock = lock
        self.__items = initial

    def __repr__(self):
        return repr(self.__items)

    def __bool__(self):
        lock = self.__lock
        if lock is None:
            return bool(self.__items)
        with lock:
            return bool(self.__items)

    def __len__(self):
        lock = self.__lock
        if lock is None:
            return len(self.__items)
        with lock:
            return len(self.__items)

    def __iter__(self):
        lock = self.__lock
        if lock is None:
            return iter(self.__items)
        with lock:
            return iter(self.__items)

    def __contains__(self, val):
        lock = self.__lock
        if lock is None:
            return val in self.__items
        with lock:
            return val in self.__items

    def __getitem__(self, n):
        lock = self.__lock
        if lock is None:
            return self.__items[n]
        with lock:
            return self.__items[n]

    def __setitem__(self, n, val):
        lock = self.__lock
        if lock is None:
            self.__items[n] = val
            return
        with lock:
            self.__items[n] = val

    def __add__(self, val):
        lock = self.__lock
        if lock is None:
            result = SafeList(None)
            result.__items = list(set(self.__items + val.__items))
            return result
        with lock:
            result = SafeList(lock)
            result.__items = list(set(self.__items + val.__items))
            return result

    def append(self, value):
        lock = self.__lock
        if lock is None:
            self.__items.append(value)
            return
        with lock:
            self.__items.append(value)

    def remove(self, value, key=None):
        lock = self.__lock
        if lock is None:
            if key is None:
                self.__items.remove(value)
                return
            if not isinstance(key, str):
                raise ValueError(f"key must be a string, received {key} of type {type(key)}")
            # PERF: key-based removals are heavily used in backtesting order tracking lists
            # (e.g., `key="identifier"`). Avoid rebuilding the full list each time.
            if key == "identifier":
                for idx, item in enumerate(self.__items):
                    item_identifier = getattr(item, "_identifier", _MISSING)
                    if item_identifier is _MISSING:
                        item_identifier = getattr(item, "identifier", _MISSING)
                    if item_identifier == value:
                        del self.__items[idx]
                        break
                return

            for idx, item in enumerate(self.__items):
                if getattr(item, key) == value:
                    del self.__items[idx]
                    break
            return

        with lock:
            if key is None:
                self.__items.remove(value)
            else:
                if not isinstance(key, str):
                    raise ValueError(f"key must be a string, received {key} of type {type(key)}")
                # PERF: key-based removals are heavily used in backtesting order tracking lists
                # (e.g., `key=\"identifier\"`). Avoid rebuilding the full list each time.
                if key == "identifier":
                    for idx, item in enumerate(self.__items):
                        item_identifier = getattr(item, "_identifier", _MISSING)
                        if item_identifier is _MISSING:
                            item_identifier = getattr(item, "identifier", _MISSING)
                        if item_identifier == value:
                            del self.__items[idx]
                            break
                else:
                    for idx, item in enumerate(self.__items):
                        if getattr(item, key) == value:
                            del self.__items[idx]
                            break

    def extend(self, value):
        lock = self.__lock
        if lock is None:
            self.__items.extend(value)
            return
        with lock:
            self.__items.extend(value)

    def get_list(self):
        lock = self.__lock
        if lock is None:
            return self.__items
        with lock:
            return self.__items

    def remove_all(self):
        lock = self.__lock
        if lock is None:
            for item in self.__items:
                self.remove(item)
            return
        with lock:
            for item in self.__items:
                self.remove(item)

    def trim_to_last(self, keep_last: int) -> int:
        """Keep only the last `keep_last` items (drop the oldest).

        This is a performance primitive used by backtesting to avoid O(n log n) sorts and repeated
        `list.remove()` scans when enforcing simple retention policies on append-only event lists.
        """
        keep_last = int(keep_last or 0)
        lock = self.__lock
        if lock is None:
            if keep_last <= 0:
                removed = len(self.__items)
                self.__items = []
                return removed
            if len(self.__items) <= keep_last:
                return 0
            removed = len(self.__items) - keep_last
            self.__items = self.__items[-keep_last:]
            return removed

        with lock:
            if keep_last <= 0:
                removed = len(self.__items)
                self.__items = []
                return removed
            if len(self.__items) <= keep_last:
                return 0
            removed = len(self.__items) - keep_last
            self.__items = self.__items[-keep_last:]
            return removed
