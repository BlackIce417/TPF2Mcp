# Phase 17: arbitrary route creation status

`CREATE_LINE_FROM_SOURCE_ROUTE` is the only verified line-creation primitive:
it copies a complete native `Line.stops` collection from an existing line.

The attempted arbitrary A→B builder resolved station `498162` / terminal `0`
and station `213303` / terminal `0` from observed raw stops, but assigning
individual stop proxies to `Line.stops` was rejected before an engine command
was constructed. The engine reports that the proxy is not the required native
userdata type. No line was created by that attempt.

Therefore `CREATE_LINE` remains `DISCOVERED_NOT_VERIFIED`. The resolver is
useful for evidence and ambiguity detection only; it is not authorization to
construct a native stop descriptor. Further progress requires confirming a
native stop constructor/helper from a new Lua load, not guessing terminal
payloads.
