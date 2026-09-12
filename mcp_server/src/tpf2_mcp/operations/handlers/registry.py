from .base import OperationHandler
from .buy_vehicle import BuyVehicleHandler
from .assign_vehicle import AssignVehicleHandler
from .create_line import ArbitraryCreateLineHandler, CreateLineHandler
from .set_line_stops import SetLineStopsHandler
from .sell_vehicle import SellVehicleHandler
from .set_line_stop_policy import SetLineStopPolicyHandler
from .vehicle_departure import HoldVehicleAtTerminalHandler, ReleaseVehicleFromHoldHandler

HANDLERS: dict[str, OperationHandler] = {item.operation_type: item for item in (BuyVehicleHandler(), AssignVehicleHandler(), CreateLineHandler(), ArbitraryCreateLineHandler(), SetLineStopsHandler(), SetLineStopPolicyHandler(), SellVehicleHandler(), HoldVehicleAtTerminalHandler(), ReleaseVehicleFromHoldHandler())}

def get(operation_type: str) -> OperationHandler | None: return HANDLERS.get(operation_type)
