"""Run the read-only direction collector in Lua 5.2 against API fixtures."""
from pathlib import Path
import unittest

try:
    from lupa.lua52 import LuaRuntime
except ImportError:
    LuaRuntime = None

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(LuaRuntime is None, 'install tests/requirements-regional.txt in project .venv')
class LuaSignalTests(unittest.TestCase):
    def test_raw_signal_animation_zero_and_missing_fields(self):
        lua = self.runtime()
        value = lua.execute("return require('tpf2_mcp/collectors/signal_state').entry({type=0,state=0,stateTime=0},2)")
        self.assertEqual(0, value['raw_state'])
        self.assertEqual(2, value['signal_index'])
        self.assertEqual('RAW_ANIMATION_OBSERVED', value['status'])
        self.assertEqual('UNKNOWN', value['aspect'])
        value = lua.execute("return require('tpf2_mcp/collectors/signal_state').entry({type=0},0)")
        self.assertEqual('API_FIELD_UNAVAILABLE', value['status'])

    def test_signal_state_reads_component_and_excludes_waypoints(self):
        lua = self.runtime()
        lua.execute('''
          api.type.ComponentType.SIGNAL_LIST=2
          api.engine.getComponent=function(id, component)
            return {signals={{type=0,state=0},{type=1,state=1},{type=2,state=3}}}
          end
        ''')
        value = lua.execute("return require('tpf2_mcp/collectors/signal_state').collect({77},{})")
        self.assertEqual(2, len(value[1]['entries']))
        self.assertEqual(1, value[1]['entries'][2]['raw_state'])

    def test_one_success_and_one_query_error_remains_unresolved(self):
        lua = self.runtime()
        lua.execute('''api.engine.system.signalSystem.getSignal=function(edge,reversed)
          if reversed then error('unavailable') end
          return {entity=77,index=0}
        end''')
        value = lua.execute('return collector.collect({type=0,edgePr={{entity=11,index=0},false}},77,0,{})')
        self.assertEqual('DIRECTION_UNRESOLVED', value['status'])

    def runtime(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        source = (ROOT/'tpf2_mod/res/scripts').as_posix()
        lua.execute(f"package.path = {str(source + '/?.lua')!r} .. ';' .. package.path")
        lua.execute('''
          api = {type={ComponentType={TRANSPORT_NETWORK=1}}, engine={system={signalSystem={}}}}
          api.type.EdgeId = {new=function(entity,index) return {entity=entity,index=index} end}
          api.engine.getComponent = function(entity, component)
            return {edges={{geometry={params={pos={{x=0,y=0},{x=100,y=0}}}}}}}
          end
          api.engine.system.signalSystem.getSignal = function(edge, reversed)
            if reversed == false then return {entity=77,index=0} end
            return {entity=-1,index=-1}
          end
          collector = require 'tpf2_mcp/collectors/signal_direction'
        ''')
        return lua

    def test_false_boolean_and_zero_based_pairs_are_retained(self):
        for expression in ('{{entity=11,index=0},false}', '{[0]={entity=11,index=0},[1]=false}', '{first={entity=11,index=0},second=false}'):
            with self.subTest(pair=expression):
                lua = self.runtime()
                value = lua.execute('return collector.collect({type=0,edgePr='+expression+'},77,0,{})')
                self.assertEqual('ENGINE_QUERY_CONFIRMED', value['status'])
                self.assertIs(value['declared_direction'], False)
                self.assertIs(value['transport_forward'], True)
                self.assertEqual(11, value['transport_entity'])

    def test_query_error_and_multiple_matches_do_not_confirm(self):
        for body in ("error('unavailable')", 'return {entity=77,index=0}'):
            lua = self.runtime(); lua.execute('api.engine.system.signalSystem.getSignal=function() '+body+' end')
            value = lua.execute('return collector.collect({type=0,edgePr={{entity=11,index=0},true}},77,0,{})')
            self.assertEqual('DIRECTION_UNRESOLVED', value['status'])

    def test_signal_list_without_edge_pair_queries_actual_parent_network(self):
        lua = self.runtime()
        value = lua.execute('return collector.collect({type=0},77,0,{},11)')
        self.assertEqual('ENGINE_QUERY_CONFIRMED', value['status'])
        self.assertEqual('PARENT_TRANSPORT_NETWORK_QUERY', value['binding_source'])

    def test_game_callable_tables_are_supported(self):
        lua = self.runtime()
        lua.execute('''
          local get = api.engine.system.signalSystem.getSignal
          api.engine.system.signalSystem.getSignal = setmetatable({}, {__call=function(_,...) return get(...) end})
          local new = api.type.EdgeId.new
          api.type.EdgeId.new = setmetatable({}, {__call=function(_,...) return new(...) end})
        ''')
        value = lua.execute('return collector.collect({type=0},77,0,{},11)')
        self.assertEqual('ENGINE_QUERY_CONFIRMED', value['status'])

    def test_train_parts_are_collected_in_one_hz_footprint_frames(self):
        lua = self.runtime()
        lua.execute('''
          api.type.ComponentType = setmetatable({}, {__index=function(_,key) return key end})
          api.engine.util = {getWorld=function() return 999 end}
          train_reads = 0
          api.engine.forEachEntityWithComponent = function(fn,component) if component=='TRANSPORT_VEHICLE' then fn(1) end end
          api.engine.getComponent = function(entity,component)
            if component=='TRANSPORT_VEHICLE' then return {carrier=1,line=3} end
            if component=='TRAIN' then train_reads=train_reads+1; return {vehicles={10,11},reservedFrom=0,reservedTo=3} end
            if component=='MOVE_PATH' then return {path={edges={
              {edgeId={entity=20,index=0},dir=true},{edgeId={entity=21,index=1},dir=false}
            }},dyn={pathPos={edgeIndex=0},speed=10,brakeDecel=1.5}} end
            if component=='BOUNDING_VOLUME' and entity>=10 and entity<=11 then
              if missing_part and entity==11 then return nil end
              return {bbox={min={x=entity*10,y=0,z=0},max={x=entity*10+9,y=3,z=4}}}
            end
            return {}
          end
          telemetry=require 'tpf2_mcp/collectors/operational_telemetry'
        ''')
        result = lua.execute("return telemetry.collect('vehicles_live')")
        train = result['vehicles'][1]
        self.assertTrue(train['train_envelope']['complete'])
        self.assertEqual(2, train['train_envelope']['expected_parts'])
        self.assertEqual(1.5, train['brake_decel_mps2'])
        count = lua.globals().train_reads
        fast = lua.execute("return telemetry.collect('vehicle_positions')")
        self.assertEqual(count, lua.globals().train_reads)
        self.assertIsNone(fast['vehicles'][1]['train_envelope'])
        footprint = lua.execute("return telemetry.collect('train_footprints')")
        self.assertEqual('OPERATIONAL_TRAIN_FOOTPRINT_FRAME', footprint['probe_kind'])
        self.assertTrue(footprint['vehicles'][1]['train_envelope']['complete'])
        self.assertEqual(1.5, footprint['vehicles'][1]['brake_decel_mps2'])
        self.assertEqual(20, footprint['vehicles'][1]['route_window']['edge_ids'][1])
        self.assertEqual(0, footprint['vehicles'][1]['route_window']['start_index'])
        self.assertGreater(lua.globals().train_reads, count)
        lua.execute('missing_part=true')
        result = lua.execute("return telemetry.collect('train_footprints')")
        self.assertFalse(result['vehicles'][1]['train_envelope']['complete'])

    def test_modified_lua_sources_compile_in_game_lua_version(self):
        lua = self.runtime()
        compile_only = lua.eval('function(s) local f,e=load(s); if not f then error(e) end; return true end')
        for file in ('signal_direction.lua', 'operational_telemetry.lua'):
            self.assertTrue(compile_only((ROOT/'tpf2_mod/res/scripts/tpf2_mcp/collectors'/file).read_text('utf8')))
        self.assertTrue(compile_only((ROOT/'tpf2_mod/res/scripts/tpf2_mcp/operations/dispatcher.lua').read_text('utf8')))
        self.assertTrue(compile_only((ROOT/'tpf2_mod/res/scripts/tpf2_mcp/state.lua').read_text('utf8')))
        self.assertTrue(compile_only((ROOT/'tpf2_mod/res/scripts/tpf2_mcp/runtime.lua').read_text('utf8')))

    def test_user_stop_has_bounded_watchdog_release(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        source = (ROOT/'tpf2_mod/res/scripts').as_posix()
        lua.execute(f"package.path = {str(source + '/?.lua')!r} .. ';' .. package.path")
        lua.execute('''
          fake_now=100
          os.time=function() return fake_now end
          package.loaded['tpf2_mcp/config']={allow_write_operations=true,
            allowed_operations={STOP_VEHICLE=true,START_VEHICLE=true}}
          sent={}
          api={cmd={make={setUserStopped=function(vehicle,stopped)
            return {vehicle=vehicle,stopped=stopped} end},sendCommand=function(command,callback)
            sent[#sent+1]=command; callback(command,true) end},type={ComponentType={TRANSPORT_VEHICLE=1}},
            engine={getComponent=function() return {} end}}
          game={interface={getEntity=function() return {} end}}
          dispatcher=require 'tpf2_mcp/operations/dispatcher'
        ''')
        accepted, result = lua.execute("return dispatcher.dispatch({operation_id='s1',operation_type='STOP_VEHICLE',target={vehicle_id=7},parameters={max_stop_seconds=5}})")
        self.assertTrue(accepted); self.assertTrue(result['engine_command_sent'])
        self.assertTrue(lua.execute('return sent[#sent].stopped'))
        lua.execute('fake_now=106; dispatcher.tick()')
        self.assertFalse(lua.execute('return sent[#sent].stopped'))
        control = lua.execute('return dispatcher.movement_control(7)')
        self.assertFalse(control['stopped']); self.assertTrue(control['command_confirmed'])

    def test_live_acceptance_can_revoke_loaded_write_permissions(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        source = (ROOT/'tpf2_mod/res/scripts').as_posix()
        lua.execute(f"package.path = {str(source + '/?.lua')!r} .. ';' .. package.path")
        lua.execute('''
          package.loaded['tpf2_mcp/config']={allow_write_operations=true,
            allowed_operations={DISABLE_WRITE_OPERATIONS=true}}
          api={}; game={}; dispatcher=require 'tpf2_mcp/operations/dispatcher'
        ''')
        accepted, result = lua.execute("return dispatcher.dispatch({operation_id='off-1',operation_type='DISABLE_WRITE_OPERATIONS',target={},parameters={}})")
        self.assertTrue(accepted); self.assertEqual('WRITE_DISABLED', result['code'])
        accepted, result = lua.execute("return dispatcher.dispatch({operation_id='off-2',operation_type='DISABLE_WRITE_OPERATIONS',target={},parameters={}})")
        self.assertFalse(accepted); self.assertEqual('WRITE_DISABLED', result['code'])

    def test_generated_write_permissions_hot_refresh_and_kill_latch(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        source = (ROOT/'tpf2_mod/res/scripts').as_posix()
        lua.execute(f"package.path = {str(source + '/?.lua')!r} .. ';' .. package.path")
        lua.execute('''
          permission_text='M.allow_write_operations = true\\nM.allowed_operations = { STOP_VEHICLE = true }'
          io.open=function()
            return {read=function() return permission_text end,close=function() end}
          end
          config=require 'tpf2_mcp/config'
        ''')
        self.assertTrue(lua.execute('return config.allow_write_operations'))
        self.assertTrue(lua.execute('return config.allowed_operations.STOP_VEHICLE'))
        lua.execute("permission_text='M.allow_write_operations = false\\nM.allowed_operations = {}'; config.refresh_permissions()")
        self.assertFalse(lua.execute('return config.allow_write_operations'))
        lua.execute("permission_text='M.allow_write_operations = true\\nM.allowed_operations = { START_VEHICLE = true }'; config.refresh_permissions()")
        self.assertTrue(lua.execute('return config.allowed_operations.START_VEHICLE'))
        lua.execute('config.disable_write_operations(); config.refresh_permissions()')
        self.assertFalse(lua.execute('return config.allow_write_operations'))
        self.assertIsNone(lua.execute('return config.allowed_operations.START_VEHICLE'))


if __name__ == '__main__': unittest.main()
