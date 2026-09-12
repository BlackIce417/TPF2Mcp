# Phase 18 Native Stop Construction

## Live findings

- `api.type.Line.Stop.new()` creates userdata but this game build rejects that wrapper when assigned directly to `Line.stops`.
- A copied native `LINE.stops` vector is accepted by `Line.stops` and its entries are writable in a temporary `Line`.
- The vector has fixed length. The builder therefore requires an exact-size template and refuses a longer one.
- `api.cmd.make.createLine(name, color, player, line)` and `updateLine(line, line)` are present. No add/insert/set-stop command was discovered.

## Live acceptance inherited and verified

- A-B: line `1790269`, requested route matched.
- A-B-C: line `1729428`, requested route matched with explicit terminals where ambiguous.
- Staffed A-B: line `1695630`, vehicles `1733153` and `621964` assigned with fresh-snapshot postconditions.

`CREATE_LINE` accepts business station IDs; it does not require `source_line_id`.
