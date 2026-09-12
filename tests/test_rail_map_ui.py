from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RailMapUiTests(unittest.TestCase):
    def test_station_tooltip_uses_yard_and_service_class_without_mod_name(self):
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        self.assertNotIn("FreestyleStation", source)
        self.assertIn("高速场（客）", source)
        self.assertIn("普速场（客货混用）", source)
        self.assertIn("tooltip.textContent=stationPreview(station)", source)

    def test_same_name_high_speed_and_conventional_yards_are_separate_markers(self):
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        self.assertIn("const stationYardClass=", source)
        self.assertIn("stationYardClass(other)===stationYardClass(station)", source)
        self.assertIn("sameLogicalYard(station,other)", source)

    def test_side_information_is_selectable_but_diagrams_are_not(self):
        network = (ROOT / "ui/rail-map/index.html").read_text(encoding="utf-8")
        timetable = (ROOT / "ui/rail-map/timetable.html").read_text(encoding="utf-8")
        self.assertIn("aside,aside *{user-select:text", network)
        self.assertIn(".list,.list *{user-select:text", timetable)
        self.assertIn(".chart,.chart *{user-select:none", timetable)

    def test_station_and_vehicle_details_have_back_navigation(self):
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        self.assertIn("const detailToolbar=", source)
        self.assertIn("返回全路网", source)
        self.assertIn("const renderVehicleSidebar=", source)
        self.assertIn("/api/vehicle-detail/", source)
        self.assertIn("当前装载", source)
        self.assertIn("下一站", source)

    def test_train_positions_step_at_half_second_interval_without_interpolation(self):
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        self.assertIn("setInterval(pollLive,500)", source)
        self.assertIn("每 0.5 秒点动刷新", source)
        self.assertNotIn("interpolatedTrainPosition", source)
        self.assertNotIn("animationDuration", source)

    def test_timetable_information_is_docked_outside_the_chart(self):
        source = (ROOT / "ui/rail-map/timetable.html").read_text(encoding="utf-8")
        self.assertIn('<div class="panel detail-panel">', source)
        self.assertIn('<div class="line-list" id="lines">', source)
        self.assertNotIn('<main class="chart"><svg id="diagram" viewBox="0 0 1200 720"></svg><div class="info"', source)
        self.assertNotIn("position:absolute;right:12px;top:12px", source)

    def test_network_sidebar_shows_ai_advice_and_compact_mcp_log(self):
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        html = (ROOT / "ui/rail-map/index.html").read_text(encoding="utf-8")
        self.assertIn("AI运行图建议", source)
        self.assertIn("MCP工作日志", source)
        self.assertIn("'系统测试'", source)
        self.assertNotIn("'影子方案'", source)
        self.assertIn("/api/ai-suggestions", source)
        self.assertIn("/api/mcp-work-log", source)
        self.assertIn(".mcp-log{max-height:145px", html)
        self.assertNotIn("全路网概况</div>", source)

    def test_ai_advice_is_timestamped_and_revealed_ten_at_a_time(self):
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        self.assertIn("aiAdviceVisibleCount=10", source)
        self.assertIn("sort((a,b)=>(Number(b.created_at)||0)-(Number(a.created_at)||0))", source)
        self.assertIn("slice(0,aiAdviceVisibleCount)", source)
        self.assertIn("查看更多（剩余 ${moreCount} 条）", source)
        self.assertIn("aiAdviceVisibleCount+=10", source)


if __name__ == "__main__":
    unittest.main()
