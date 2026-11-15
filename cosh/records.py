"""Compact records for analyses that hold a million CLs or commits at once.

A dict per CL costs about 830 bytes for its 36 columns and doubles to
1.6 KB once a script adds a dozen derived keys; a record with slots costs
8 bytes a field. record_type() makes such a class that reads and writes
like the dicts the balance scripts were written for: rec["k"],
rec["k"] = v, rec.get("k"), "k" in rec. A key that is neither a field nor
an extra still works: it goes into a per-record dict, made on first use.
Reading a key never set raises AttributeError (a dict raises KeyError).
"""


class Record:
    __slots__ = ("__dict__",)
    __getitem__ = object.__getattribute__     # C speed, unlike a Python method
    __setitem__ = object.__setattr__

    def get(self, k, default=None):
        return getattr(self, k, default)

    def __contains__(self, k):
        return hasattr(self, k)

    def __repr__(self):
        return f"{type(self).__name__}({self._fields_dict()!r})"

    def _fields_dict(self):
        out = {k: getattr(self, k) for k in type(self).__slots__ if hasattr(self, k)}
        out.update(getattr(self, "__dict__", None) or {})
        return out


def record_type(name, fields, extras=()):
    """A Record class with slots for `fields` (set by its constructor, by
    position or keyword) and for `extras` (keys scripts add later)."""
    fields, extras = tuple(fields), tuple(k for k in extras if k not in fields)
    ns = {"__slots__": fields + extras}
    args = ", ".join(fields)
    body = "\n".join(f"    self.{k} = {k}" for k in fields) or "    pass"
    exec(f"def __init__(self, {args}):\n{body}", ns)
    return type(name, (Record,), ns)
