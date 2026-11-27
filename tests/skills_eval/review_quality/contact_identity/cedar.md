# Address book API

A contact is a (value, kind) pair. Two entries identify the same contact when their values match. The add operation keeps the existing entry on a match and appends a new entry otherwise. Both outcomes return True. Entries retain insertion order.

Run the tests with `python3 -B -m unittest -v`.
