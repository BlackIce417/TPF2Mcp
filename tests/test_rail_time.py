"""Run the shared frontend time model against clock discontinuities."""
import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("node"), "Node is required for frontend time tests")
class RailTimeTests(unittest.TestCase):
    def test_wall_projection_pause_stale_save_and_motion(self):
        script = r"""
const assert = require('node:assert/strict');
const time = require('./ui/rail-map/src/shared/rail-time.js');
const c = new time.Clock();
let now = Date.UTC(2026, 8, 18, 15, 59, 50) / 1000;
Date.now = () => now * 1000;
const frame = (game, rate=1, status='RUNNING', save='a') => ({save_id:save, fresh:true,
  sampled_at:now, simulation:{status, speed_multiplier:rate, clock:{game_time:game*1000}}});
c.update(frame(100));
assert.equal(c.prediction(130), now+30);
assert.equal(c.toGame(now+30), 130);
const historicalWall = c.toWall(100);
now+=10; c.update(frame(110,3));
assert.equal(c.prediction(140), now+10);
assert.equal(historicalWall, now-10);
c.update(frame(110,0,'PAUSED'));
assert.equal(c.prediction(140), null);
assert.match(c.status(), /暂停/);
now+=20; c.update(frame(110,1));
assert.equal(c.prediction(140), now+30);
now+=16; assert.equal(c.prediction(140), null);
assert.match(c.status(), /过期/);
c.update(frame(5,0,'PAUSED','b'));
assert.equal(c.anchor, null);
c.update(frame(5)); assert.equal(c.toGame(c.toWall(90)),90);
c.update(frame(1,0,'PAUSED'));
assert.equal(c.anchor,null); // save rewind must not reuse future anchors
c.update({...frame(3), fresh:false}); assert.equal(c.prediction(10),null);
c.update(frame(3,null)); assert.equal(c.prediction(10),null);
c.update(frame(3));
c.update({...frame(3),simulation:{status:'RUNNING',speed_multiplier:1,clock:{game_time:null}}});
assert.equal(c.prediction(10),null);
c.update(null); assert.equal(c.anchor,null);
assert.equal(time.localTime(null),'—');
assert.equal(time.motion({speed_kmh:100},frame(5)),'区间运行');
assert.equal(time.motion({raw_state:2,speed_kmh:0},frame(5)),'站内停靠');
assert.equal(time.motion({speed_kmh:null},frame(5)),'速度未知');
assert.equal(time.motion({speed_kmh:100,position_stale:true},frame(5)),'运行信息未更新');
assert.equal(time.motion({speed_kmh:100},frame(5,0,'PAUSED')),'游戏已暂停');
assert.equal(time.motion({speed_kmh:100},{...frame(5),sampled_at:now-60}),'运行信息未更新');
const midnight = new Date(2026,8,19,0,0,10).getTime()/1000;
assert.match(time.localTime(midnight), /00:00:10/);
assert.notEqual(time.localTime(midnight,true),time.localTime(midnight-60,true));
"""
        result = subprocess.run([shutil.which("node"), "-e", script],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
