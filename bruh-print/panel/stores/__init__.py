"""Everything this add-on remembers, one file per kind of thing.

Every store is the same shape — a JSON file under /data, written through
`atomic_write`, read into dataclasses — and none of them is a queue. The one
that looks like it might be is `history`, and it is capped and never drained:
a reprint is the whole reason it exists.
"""
