from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RailMapUiTests(unittest.TestCase):
    def test_station_tooltip_uses_yard_and_service_class_without_mod_name(self):
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        self.assertNotIn("FreestyleStation", source)
        self.assertIn("高速场(客)", source)
        self.assertIn("高普混合场(客)", source)
        self.assertIn("普速场(客-货)", source)
        self.assertIn("普速场(客)", source)
        self.assertIn("普速场(货)", source)
        self.assertIn("客运场(待确认)", source)
        self.assertIn("active_passenger_vehicles", source)
        self.assertNotIn("terminalIsHighSpeed", source)
        self.assertNotIn("track_resource_files", source)
        self.assertIn("name.endsWith('站')?name.slice(0,-1):name", source)
        self.assertIn("yard?`${name}-${yard}`:name", source)
        self.assertIn("tooltip.textContent=stationPreview(station)", source)

    def test_nearby_same_name_station_entities_share_vehicle_service_classification(self):
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        self.assertNotIn("const stationYardClass=", source)
        self.assertNotIn("stationYardClass(other)===stationYardClass(station)", source)
        self.assertIn("sameLogicalYard(station,other)", source)
        self.assertIn("const stationPassengerServiceClass=", source)
        self.assertIn("lineServesPassengerTerminal(line,station)", source)

    def test_station_log_scroll_survives_live_and_log_refreshes(self):
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        self.assertIn("const anchorKey=anchor?.dataset.logKey", source)
        self.assertIn("nextAnchor.offsetTop-anchorOffset", source)
        self.assertIn("refreshStationLogSidebar();", source)
        self.assertIn("if(selectedStation&&hasVehicles)refreshStationLiveSidebar()", source)
        self.assertNotIn("if(selectedStation)renderStationSidebar();else if", source)

    def test_station_log_uses_compact_time_and_line_vehicle_event_order(self):
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        self.assertIn("const formatStationLogTime=", source)
        self.assertIn("`${two(date.getMonth()+1)}-${two(date.getDate())} ${two(date.getHours())}:${two(date.getMinutes())}`", source)
        self.assertIn("`${item.line_name} ${item.vehicle_name} ${item.event_type==='STOP'?'停靠':'跨站'}`", source)

    def test_station_route_uses_compact_scheduled_dwell_label(self):
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        self.assertIn("`第${Number(stop.sequence_index)+1}站 图定停车${scheduled}(${currentSimulationSpeedLabel()})`", source)
        self.assertIn("return Number.isFinite(multiplier)?`${multiplier}x`:'?x'", source)
        self.assertIn("sidebar.dataset.dwellSpeed!==speedLabel", source)
        self.assertNotIn("游戏策略 ${min}–${max} 秒", source)

    def test_station_sidebar_shows_platform_faces_without_track_count(self):
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        template = (ROOT / "ui/rail-map/templates/station-sidebar.html").read_text(encoding="utf-8")
        self.assertIn("'客货混用车站':'客货车站'", source)
        self.assertIn("passenger?'客运车站':cargo?'货运车站':'未知车站'", source)
        self.assertIn("Math.max(1,(platform.terminal_faces||[]).length)", source)
        self.assertIn("${platformFaces}站台", source)
        self.assertNotIn("${routes.length}线", source)
        self.assertIn('data-field="station-summary"', template)
        self.assertNotIn('data-field="platform-count"', template)
        self.assertNotIn('data-field="station-kind"', template)
        self.assertIn('data-field="serving-vehicles"', template)

    def test_side_information_is_selectable_but_diagrams_are_not(self):
        network = (ROOT / "ui/rail-map/network.css").read_text(encoding="utf-8")
        timetable = (ROOT / "ui/rail-map/timetable.css").read_text(encoding="utf-8")
        self.assertRegex(
            network,
            re.compile(r"aside\s*,\s*aside \*\s*\{[^}]*user-select:\s*text", re.DOTALL),
        )
        self.assertRegex(
            timetable,
            re.compile(r"\.list\s*,\s*\.list \*\s*\{[^}]*user-select:\s*text", re.DOTALL),
        )
        self.assertRegex(
            timetable,
            re.compile(r"\.chart\s*,\s*\.chart \*\s*\{[^}]*user-select:\s*none", re.DOTALL),
        )

    def test_html_contains_structure_only_and_links_external_assets(self):
        network = (ROOT / "ui/rail-map/index.html").read_text(encoding="utf-8")
        timetable = (ROOT / "ui/rail-map/timetable.html").read_text(encoding="utf-8")
        templates = list((ROOT / "ui/rail-map/templates").glob("*.html"))

        for html in (network, timetable, *(path.read_text(encoding="utf-8") for path in templates)):
            self.assertNotIn("<style", html)
            self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)")
            self.assertNotIn("onclick=", html)
            self.assertNotRegex(html, r"\sstyle=")

        self.assertIn('href="network.css', network)
        self.assertIn('src="vendor/jquery-4.0.0.min.js"', network)
        self.assertIn('src="network-page.js', network)
        self.assertIn('src="template-runtime.js', network)
        self.assertIn('href="timetable.css', timetable)
        self.assertIn('src="vendor/jquery-4.0.0.min.js"', timetable)
        self.assertIn('src="template-runtime.js', timetable)
        self.assertIn('src="timetable-page.js', timetable)

    def test_local_jquery_is_loaded_before_application_scripts(self):
        jquery = (ROOT / "ui/rail-map/vendor/jquery-4.0.0.min.js").read_text(encoding="utf-8")
        self.assertTrue(jquery.startswith("/*! jQuery v4.0.0"))
        for page_name, first_app_script in (
            ("index.html", "network-page.js"),
            ("timetable.html", "template-runtime.js"),
        ):
            html = (ROOT / "ui/rail-map" / page_name).read_text(encoding="utf-8")
            self.assertLess(html.index("vendor/jquery-4.0.0.min.js"), html.index(first_app_script))

    def test_local_button_requires_a_selected_station_and_uses_station_cache(self):
        html = (ROOT / "ui/rail-map/index.html").read_text(encoding="utf-8")
        network = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        local = (ROOT / "ui/rail-map/app.js").read_text(encoding="utf-8")

        self.assertIn("if (!selectedStation)", network)
        self.assertIn("showRailMapNotice('请选择对应车站')", network)
        self.assertIn("target.searchParams.set('station', selectedStation.entity_id)", network)
        self.assertIn("query.get('view') !== 'local'", local)
        self.assertIn("$.ajax", local)
        self.assertIn("station-previews/station-${stationId}.json", local)
        self.assertIn("preview.save_id !== manifest.save_id", local)
        self.assertIn("请选择对应车站", local)
        self.assertNotIn('src="data.js"', html)
        self.assertNotIn('src="ground-truth.js"', html)
        self.assertNotIn('src="physical-track-data.js"', html)
        self.assertNotIn("PHYSICAL_TRACK_DATA", local)
        self.assertNotIn("STATION_GROUND_TRUTH", local)

    def test_local_station_preview_is_static_and_has_no_vehicle_polling(self):
        local = (ROOT / "ui/rail-map/app.js").read_text(encoding="utf-8")
        page = (ROOT / "ui/rail-map/network-page.js").read_text(encoding="utf-8")

        self.assertIn("ENGINE_OBSERVED_STATION_PHYSICAL_PREVIEW", local)
        self.assertIn("不 同步列车信息".replace(" ", ""), local)
        self.assertNotIn("/api/live", local)
        self.assertNotIn("setInterval", local)
        self.assertNotIn("pollLive", local)
        self.assertNotIn("vehicles", local)
        self.assertIn("staticLocalPreview", page)
        self.assertIn("局部页不订阅动态遥测", page)

    def test_local_station_preview_clips_to_oriented_throat_scope(self):
        local = (ROOT / "ui/rail-map/app.js").read_text(encoding="utf-8")
        generator = (ROOT / "mcp_server/src/tpf2_mcp/station_preview.py").read_text(encoding="utf-8")

        self.assertIn("preview.scope?.polygon", local)
        self.assertIn("$mapLayer.attr('clip-path'", local)
        self.assertIn("PLATFORM_SIDING_THROAT_ORIENTED_RECTANGLE_DERIVED", generator)
        self.assertIn("DEFAULT_MARGIN_M = 50.0", generator)
        self.assertIn("_edge_intersects_scope", generator)

    def test_platform_renderers_use_unified_physical_platforms(self):
        local = (ROOT / "ui/rail-map/app.js").read_text(encoding="utf-8")
        network = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        template = (ROOT / "ui/rail-map/templates/local-station-sidebar.html").read_text(encoding="utf-8")

        self.assertIn("preview.station_groups", local)
        self.assertIn("preview.platforms", local)
        self.assertIn("terminalByNode", local)
        self.assertIn("physicalPlatforms.forEach(platform", local)
        self.assertNotIn("(preview.station.terminals || []).forEach(terminal =>", local)
        self.assertIn("const physicalPlatforms=station=>station.platforms", network)
        self.assertIn("physicalPlatforms(station).forEach(platform", network)
        self.assertIn("groups.flatMap(physicalPlatforms)", network)
        self.assertIn("platform.platform_width_units", local)
        self.assertIn("platform.platform_width_units", network)
        self.assertIn("faceForPointer", local)
        self.assertIn("faceForPointer", network)
        self.assertIn("'stroke-dasharray': '4 3'", local)
        self.assertIn("'stroke-dasharray':'4 3'", network)
        self.assertIn('data-field="terminal-faces"', template)

    def test_local_platform_width_tracks_map_zoom(self):
        local = (ROOT / "ui/rail-map/app.js").read_text(encoding="utf-8")

        self.assertIn("const PLATFORM_DECK_WIDTH_M", local)
        self.assertIn("const platformStrokeWidths", local)
        self.assertIn("'stroke-width': strokeWidths.deck", local)
        self.assertIn("'stroke-width': strokeWidths.outline", local)
        self.assertIn("'stroke-width': strokeWidths.hit", local)
        platform_block = local[local.index("physicalPlatforms.forEach(platform"):local.index("preview.nodes.filter")]
        self.assertNotIn("'vector-effect': 'non-scaling-stroke'", platform_block.replace(
            "'stroke-dasharray': '4 3', 'vector-effect': 'non-scaling-stroke',", ""
        ))

    def test_platform_service_kind_is_coloured_only_in_local_view(self):
        local = (ROOT / "ui/rail-map/app.js").read_text(encoding="utf-8")
        network = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")

        self.assertIn("const PASSENGER_PLATFORM_COLOR", local)
        self.assertIn("const CARGO_PLATFORM_COLOR", local)
        self.assertIn("stroke: platformColor", local)
        self.assertIn("label: '客台'", local)
        self.assertIn("label: '货台'", local)
        self.assertIn("platform.cargo ? '货' : '客'", local)
        self.assertIn("stroke:'#96a2a8'", network)
        self.assertNotIn("PASSENGER_PLATFORM_COLOR", network)
        self.assertNotIn("CARGO_PLATFORM_COLOR", network)
        self.assertIn("站台（${kind}）", network)

    def test_grade_separated_crossings_use_shared_xyz_renderer(self):
        html = (ROOT / "ui/rail-map/index.html").read_text(encoding="utf-8")
        local = (ROOT / "ui/rail-map/app.js").read_text(encoding="utf-8")
        network = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        crossing = (ROOT / "ui/rail-map/bridge-crossings.js").read_text(encoding="utf-8")
        template = (ROOT / "ui/rail-map/templates/local-station-sidebar.html").read_text(encoding="utf-8")

        self.assertLess(html.index("bridge-crossings.js"), html.index("network-app.js"))
        self.assertIn("RailBridgeCrossings.detect(preview.edges", local)
        self.assertIn("RailBridgeCrossings.renderSvg", local)
        self.assertIn("renderVisibleBridges", network)
        self.assertIn("scheduleBridgeRender", network)
        self.assertIn("const cluster =", crossing)
        self.assertIn("data-bridge-role': 'bridge-deck-mask'", crossing)
        self.assertIn("data-bridge-role': 'upper-track'", crossing)
        self.assertNotIn("data-bridge-role': 'bridge-bar'", crossing)
        self.assertNotIn("shape.bars.forEach", crossing)
        self.assertIn("data-bridge-role': 'bridge-side'", crossing)
        self.assertIn("data-bridge-role': 'bridge-wing'", crossing)
        self.assertIn("shape.bridgeSides.forEach", crossing)
        self.assertIn("upperPathForEdge", crossing)
        self.assertIn("deckCorners", crossing)
        self.assertIn("bridgeWingComponentM", crossing)
        self.assertIn("resolveStructures", crossing)
        self.assertIn("ENGINE_UPPER_TRACK_CURVE_SWEPT_DECK", crossing)
        self.assertIn("upperShortEdgeClearanceM", crossing)
        self.assertIn("upperPointsForEdge", local)
        self.assertIn("upperPointsForEdge", network)
        self.assertIn("Number(left.crossing.upper_z) - Number(right.crossing.upper_z)", crossing)
        self.assertIn("立交桥 ${bridgeStructureCount} 座", local)
        self.assertIn("45°", template)

    def test_local_station_summary_only_shows_name_and_serving_lines(self):
        local = (ROOT / "ui/rail-map/app.js").read_text(encoding="utf-8")
        template = (ROOT / "ui/rail-map/templates/local-station-sidebar.html").read_text(encoding="utf-8")
        self.assertIn('data-field="station-name"', template)
        self.assertIn('data-field="serving-lines"', template)
        self.assertIn("(preview.lines || []).map", local)
        for field in ("station-id", "center", "node-edge-count", "switch-count", "line-count"):
            self.assertNotIn(f'data-field="{field}"', template)

    def test_sidebar_html_is_kept_in_external_templates(self):
        network_app = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        local_app = (ROOT / "ui/rail-map/app.js").read_text(encoding="utf-8")
        timetable_app = (ROOT / "ui/rail-map/timetable.js").read_text(encoding="utf-8")
        runtime = (ROOT / "ui/rail-map/template-runtime.js").read_text(encoding="utf-8")
        template_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((ROOT / "ui/rail-map/templates").glob("*.html"))
        )

        self.assertNotIn(".innerHTML", network_app)
        self.assertNotIn(".innerHTML", local_app)
        self.assertNotIn(".innerHTML", timetable_app)
        self.assertNotRegex(network_app, r"`[^`]*<(?:div|span|button|table|br)\b")
        self.assertNotRegex(local_app, r"`[^`]*<(?:div|span|button|table|br)\b")
        self.assertNotRegex(timetable_app, r"`[^`]*<(?:div|span|button|table|br)\b")
        self.assertIn("RAIL_MAP_TEMPLATES_READY", runtime)
        self.assertIn('id="overview-sidebar-template"', template_text)
        self.assertIn('id="station-sidebar-template"', template_text)
        self.assertIn('id="vehicle-sidebar-template"', template_text)
        self.assertIn('id="local-station-sidebar-template"', template_text)
        self.assertIn('id="timetable-line-detail-template"', template_text)

    def test_footer_lamps_are_backed_by_live_status_and_not_static_claims(self):
        html = (ROOT / "ui/rail-map/index.html").read_text(encoding="utf-8")
        page = (ROOT / "ui/rail-map/network-page.js").read_text(encoding="utf-8")
        app = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")

        self.assertIn('id="bridge-lamp"', html)
        self.assertIn('id="live-lamp"', html)
        self.assertNotIn("轨道坐标来自游戏引擎</span>", html)
        self.assertIn("new EventSource('/api/events')", page)
        self.assertIn("status.bridge_connected === true", page)
        self.assertIn("status.live_generation", page)
        self.assertIn("status.live_error", page)
        self.assertIn("events.addEventListener('error'", page)
        self.assertNotIn("document.querySelector('footer .lamp')", app)

    def test_line_selection_and_coloured_route_overlays_are_disabled(self):
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        overview = (ROOT / "ui/rail-map/templates/overview-sidebar.html").read_text(encoding="utf-8")

        self.assertIn("铁路线路（只读）", overview)
        self.assertIn("stroke:'#83a9bd'", source)
        self.assertNotIn("const palette=", source)
        self.assertNotIn("const lineColor=", source)
        self.assertNotIn("const linePaths", source)
        self.assertNotIn("selectedLine", source)
        self.assertNotIn("data-line-row", source)
        self.assertNotIn("line.overview_segments.map", source)

    def test_station_and_vehicle_details_have_back_navigation(self):
        html = (ROOT / "ui/rail-map/index.html").read_text(encoding="utf-8")
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        station = (ROOT / "ui/rail-map/templates/station-sidebar.html").read_text(encoding="utf-8")
        vehicle = (ROOT / "ui/rail-map/templates/vehicle-sidebar.html").read_text(encoding="utf-8")
        self.assertIn('class="sidebar-header"', html)
        self.assertIn('class="detail-back is-hidden" id="sidebar-back"', html)
        self.assertIn("返回全路网", html)
        self.assertNotIn('data-action="sidebar-back"', station)
        self.assertNotIn('data-action="sidebar-back"', vehicle)
        self.assertIn("setSidebarBackVisible(false)", source)
        self.assertGreaterEqual(source.count("setSidebarBackVisible(true)"), 2)
        self.assertIn("toggleClass('is-hidden',!visible)", source)
        self.assertIn("const renderVehicleSidebar=", source)
        self.assertIn("/api/vehicle-detail/", source)
        self.assertIn("当前装载", vehicle)
        self.assertIn("下一站", vehicle)

    def test_station_summary_counts_serving_vehicles_instead_of_only_lines(self):
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        self.assertIn("const stationServingVehicleCount=", source)
        self.assertIn("图定停靠 ${servingVehicles} 趟列车", source)
        self.assertNotIn('<span>接入线路</span><b>${routes.length}</b>', source)

    def test_depots_use_short_chinese_names_at_all_zoom_levels(self):
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        self.assertIn("const depotDisplayName=", source)
        self.assertIn("depotDisplayName(depot),group", source)
        self.assertIn("'汉口所':'汉口动车所'", source)
        self.assertIn("'武汉所':'武汉动车所'", source)
        self.assertNotIn("'DEPOT',group", source)
        self.assertNotIn("'铁路车辆段'", source)

    def test_train_positions_step_at_half_second_interval_without_interpolation(self):
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        self.assertIn("setInterval(pollLive,500)", source)
        self.assertIn("列车位置刷新时间: 0.5s", source)
        self.assertIn("if(clock.textContent!==clockText)clock.textContent=clockText", source)
        self.assertNotIn("interpolatedTrainPosition", source)
        self.assertNotIn("animationDuration", source)

    def test_footer_signal_button_toggles_signal_visibility(self):
        html = (ROOT / "ui/rail-map/index.html").read_text(encoding="utf-8")
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        self.assertIn('id="toggle-signals" hidden', html)
        self.assertIn("const $signalToggle=$('#toggle-signals')", source)
        self.assertIn("signalsVisible=!signalsVisible", source)
        self.assertIn("signalsVisible&&representedMeters()<250", source)
        self.assertIn("signalsVisible?'隐藏信号机':'显示信号机'", source)

    def test_timetable_information_is_docked_outside_the_chart(self):
        source = (ROOT / "ui/rail-map/timetable.html").read_text(encoding="utf-8")
        self.assertIn('<div class="panel detail-panel">', source)
        self.assertIn('<div class="line-list" id="lines">', source)
        self.assertNotIn('<main class="chart"><svg id="diagram" viewBox="0 0 1200 720"></svg><div class="info"', source)
        self.assertNotIn("position:absolute;right:12px;top:12px", source)

    def test_network_sidebar_shows_ai_advice_and_compact_mcp_log(self):
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        overview = (ROOT / "ui/rail-map/templates/overview-sidebar.html").read_text(encoding="utf-8")
        css = (ROOT / "ui/rail-map/network.css").read_text(encoding="utf-8")
        self.assertIn("AI运行图建议", overview)
        self.assertIn("MCP工作日志", overview)
        self.assertIn("'系统测试'", source)
        self.assertNotIn("'影子方案'", source)
        self.assertIn("/api/ai-suggestions", source)
        self.assertIn("/api/mcp-work-log", source)
        self.assertRegex(
            css,
            re.compile(r"\.mcp-log\s*\{[^}]*max-height:\s*145px", re.DOTALL),
        )
        self.assertNotIn("全路网概况</div>", overview)

    def test_full_mcp_work_log_modal_supports_status_and_text_filters(self):
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        overview = (ROOT / "ui/rail-map/templates/overview-sidebar.html").read_text(encoding="utf-8")
        css = (ROOT / "ui/rail-map/network.css").read_text(encoding="utf-8")
        self.assertIn('data-action="work-log-all"', overview)
        self.assertIn('id="work-log-dialog-title"', overview)
        for category in ("ALL", "EXECUTED", "BLOCKED", "PENDING", "CANCELLED", "TEST"):
            self.assertIn(f'data-work-log-filter="{category}"', overview)
        self.assertIn("/api/mcp-work-log?limit=all", source)
        self.assertIn("workLogSearch", source)
        self.assertIn("workLogCategory(item)===workLogFilter", source)
        self.assertIn("event.key==='Escape'", source)
        self.assertIn(".work-log-modal", css)
        self.assertIn(".status-blocked", css)

    def test_ai_advice_is_timestamped_and_revealed_ten_at_a_time(self):
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        self.assertIn("aiAdviceVisibleCount=10", source)
        self.assertIn("sort((a,b)=>(Number(b.created_at)||0)-(Number(a.created_at)||0))", source)
        self.assertIn("slice(0,aiAdviceVisibleCount)", source)
        self.assertIn("查看更多（剩余 ${moreCount} 条）", source)
        self.assertIn("aiAdviceVisibleCount+=10", source)

    def test_network_page_hot_reloads_only_after_new_save_map_is_ready(self):
        source = (ROOT / "ui/rail-map/network-app.js").read_text(encoding="utf-8")
        self.assertIn("status.save_transition", source)
        self.assertIn("status.rail_save_id===status.save_id", source)
        self.assertIn("reloadRequested", source)
        self.assertIn("searchParams.get('_rail')", source)
        self.assertIn("location.replace(target.href)", source)


if __name__ == "__main__":
    unittest.main()
