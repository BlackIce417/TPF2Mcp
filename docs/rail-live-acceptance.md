# Railway live layer acceptance

Date: 2026-09-11

## Verified on the active large save

- Full static rail topology: 19,035 nodes, 19,611 edges, 130 rail station groups, 77 rail lines, 78 spatial tiles.
- Compact `vehicles_live` frame: 262 transport vehicles / 164 rail-line vehicles, 81 KB, 171 ms collection time.
- `MOVE_PATH.dyn.pathPos` produced a current path position for all 164 rail vehicles.
- 155 rail vehicles were on an edge in the exported main rail graph in the sampled frame; the remaining vehicles were on depot or otherwise non-exported edges and were not falsely snapped.
- `MOVE_PATH.dyn.speed` produced engine speed for all 164 rail vehicles.
- Consecutive HTTP frames 4.89 seconds apart showed 116 moving coordinates, 108 edge changes, 120 positive speeds, and a maximum observed speed of 350 km/h.
- Dynamic response remained about 91 KB; static controls and tiled topology are served separately.
- The game process remained responsive after manual and automatic sampling.

## Signal and block semantics

`SIGNAL_LIST` belongs to the edge-object entity identified by `SignalId.entity`, not to the parent `BASE_EDGE`. The collector reads signal-list entries from each track edge object and only promotes documented signal types 0 (`SIGNAL`) and 1 (`ONE_WAY_SIGNAL`). Type 2 (`WAYPOINT`) is not promoted as an operational signal.

Live acceptance after the final reload found 1,546 signal-list objects: 1,545 type-0 `SIGNAL` entries and one type-1 `ONE_WAY_SIGNAL`, with no type-2 `WAYPOINT` entries. All 1,546 signal coordinates were projected back onto their owning Hermite rail curve (parameter range 0.002188–0.993576), producing 3,819 signal/junction-delimited blocks.

## Intentionally unavailable

- Signal aspect/state: `UNKNOWN` until a verified read path is established.
- Passenger/cargo demand: `UNKNOWN`; the unsafe station UI sampling chain remains disabled after its repeatable native crash.
- Vehicles on depot/non-exported edges are omitted from main-network occupancy instead of being falsely attached to nearby track.
