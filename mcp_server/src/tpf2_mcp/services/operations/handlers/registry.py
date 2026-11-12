from tpf2_mcp.services.operations.handlers.base import OperationHandler
from tpf2_mcp.services.operations.handlers.buy_vehicle import BuyVehicleHandler
from tpf2_mcp.services.operations.handlers.assign_vehicle import AssignVehicleHandler
from tpf2_mcp.services.operations.handlers.create_line import ArbitraryCreateLineHandler, CreateLineHandler
from tpf2_mcp.services.operations.handlers.set_line_stops import SetLineStopsHandler
from tpf2_mcp.services.operations.handlers.sell_vehicle import SellVehicleHandler
from tpf2_mcp.services.operations.handlers.set_line_stop_policy import SetLineStopPolicyHandler
from tpf2_mcp.services.operations.handlers.vehicle_departure import HoldVehicleAtTerminalHandler, ReleaseVehicleFromHoldHandler
from tpf2_mcp.services.operations.handlers.replace_vehicle_config import ReplaceVehicleConfigHandler

HANDLERS: dict[str, OperationHandler] = {item.operation_type: item for item in (BuyVehicleHandler(), AssignVehicleHandler(), CreateLineHandler(), ArbitraryCreateLineHandler(), SetLineStopsHandler(), SetLineStopPolicyHandler(), SellVehicleHandler(), HoldVehicleAtTerminalHandler(), ReleaseVehicleFromHoldHandler(), ReplaceVehicleConfigHandler())}

def get(operation_type: str) -> OperationHandler | None: return HANDLERS.get(operation_type)
