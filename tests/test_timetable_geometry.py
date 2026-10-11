"""Execute the browser's pure geometry/observation code, without a game."""
import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("node"), "Node is needed to execute frontend geometry")
class TimetableGeometryTests(unittest.TestCase):
    def test_unwrapped_cycle_and_real_station_observation_gaps(self):
        script = r"""
const assert = require('node:assert/strict');
const g = require('./ui/rail-map/src/pages/timetable/timetable.js');
const line = {cycle_seconds: 120, stops: [
  {arrival_offset_seconds: 30, departure_offset_seconds: 40},
  {arrival_offset_seconds: 120, departure_offset_seconds: 140},
]};
const points = g.points(line, 1000);
assert.deepEqual(points, [[1030,0],[1040,0],[1120,1],[1140,1],[1150,2]]);
assert.ok(points.every((point, index) => !index || point[0] >= points[index-1][0]));
const [first,last] = g.cycles(line, 100000, 100600);
assert.ok(first * 120 + 30 <= 100000);
assert.ok(last * 120 + 30 >= 100600);
assert.equal(g.clock(86401), '24:00:01');
const frame = (gameTime, sampledAt, state=2, stop=1) => ({fresh:true, sampled_at:sampledAt,
 simulation:{clock:{game_time:gameTime}}, vehicles:[{entity_id:7,raw_state:state,stop_index:stop,timetable:{punctuality:'LATE'}}]});
assert.equal(g.stationPoints(frame(12000,12), frame(10000,10), 2)[0].previous, 10);
assert.equal(g.stationPoints(frame(12000,12), frame(10000,10), 2)[0].timetable.punctuality, 'LATE');
assert.equal(g.stationPoints(frame(12000,20), frame(10000,10), 2)[0].previous, null);
assert.equal(g.stationPoints(frame(12000,12), frame(10000,10,1), 2)[0].previous, null);
assert.equal(g.stationPoints(frame(12000,12), frame(10000,10,2,0), 2)[0].previous, null);
assert.equal(g.stationPoints(frame(8000,12), frame(10000,10), 2)[0].previous, null);
assert.deepEqual(g.stationPoints(frame(10000,12), frame(10000,10), 2), []);
assert.deepEqual(g.stationPoints(frame(12000,12,1), frame(10000,10), 2), []);
const stale = frame(12000,12); stale.vehicles[0].position_stale=true;
assert.deepEqual(g.stationPoints(stale, frame(10000,10), 2), []);
assert.deepEqual(g.stationPoints({...frame(12000,12),fresh:false}, frame(10000,10), 2), []);
assert.deepEqual(g.stationPoints(frame(12000,12,2,-1), null, 2), []);
assert.deepEqual(g.stationPoints(frame(12000,12,2,2), null, 2), []);
"""
        result = subprocess.run([shutil.which("node"), "-e", script],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
