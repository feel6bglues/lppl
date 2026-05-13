# -*- coding: utf-8 -*-
import logging
import os
from datetime import datetime
from typing import List

from src.constants import INDICES, OUTPUT_DIR

logger = logging.getLogger(__name__)


class HTMLGenerator:
    def __init__(self, output_dir: str = None):
        self.output_dir = output_dir or OUTPUT_DIR
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def generate_html(self, report_data: List) -> str:
        index_order = list(INDICES.keys())

        html_template = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LPPL模型扫描 - 实时风险监控</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; background: #0f172a; color: #e2e8f0; padding: 20px; min-height: 100vh; }
        .header { text-align: center; margin-bottom: 30px; padding: 25px; background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border-radius: 16px; border: 1px solid #334155; box-shadow: 0 10px 30px rgba(0,0,0,0.3); }
        .header h1 { font-size: 28px; background: linear-gradient(90deg, #60a5fa, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 8px; }
        .subtitle { color: #64748b; font-size: 14px; }
        .time-section { margin-bottom: 40px; }
        .section-header { display: flex; align-items: center; margin-bottom: 20px; padding: 15px 20px; border-radius: 12px; border-left: 6px solid; background: rgba(30, 41, 59, 0.5); backdrop-filter: blur(10px); }
        .section-header.all-codes { border-color: #4ade80; background: linear-gradient(90deg, rgba(74,222,128,0.1) 0%, transparent 100%); }
        .section-header.short-term { border-color: #38bdf8; background: linear-gradient(90deg, rgba(56,189,248,0.1) 0%, transparent 100%); }
        .section-header.medium-term { border-color: #fbbf24; background: linear-gradient(90deg, rgba(251,191,36,0.1) 0%, transparent 100%); }
        .section-header.long-term { border-color: #a78bfa; background: linear-gradient(90deg, rgba(167,139,250,0.1) 0%, transparent 100%); }
        .section-icon { font-size: 24px; margin-right: 15px; }
        .section-title { font-size: 20px; font-weight: bold; color: #f1f5f9; }
        .section-desc { font-size: 13px; color: #94a3b8; margin-left: auto; font-family: 'Courier New', monospace; }
        .cards-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 20px; }
        .index-card { background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; position: relative; overflow: hidden; transition: all 0.3s ease; }
        .index-card:hover { transform: translateY(-3px); box-shadow: 0 20px 40px rgba(0,0,0,0.4); border-color: #475569; }
        .index-card::before { content: ''; position: absolute; top: 0; left: 0; width: 100%; height: 3px; background: var(--border-color); }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
        .index-info h3 { font-size: 18px; color: #f8fafc; margin-bottom: 4px; }
        .index-code { font-size: 12px; color: #64748b; font-family: 'Courier New', monospace; background: #0f172a; padding: 2px 8px; border-radius: 4px; display: inline-block; }
        .risk-badge { padding: 6px 12px; border-radius: 20px; font-size: 11px; font-weight: bold; letter-spacing: 0.5px; }
        .danger { background: #dc2626; color: white; box-shadow: 0 0 10px rgba(220,38,38,0.4); }
        .warning { background: #ea580c; color: white; }
        .medium { background: #0284c7; color: white; }
        .metrics-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 15px; }
        .metric { text-align: center; padding: 10px; background: #0f172a; border-radius: 8px; border: 1px solid #334155; }
        .metric-label { font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
        .metric-value { font-size: 16px; font-weight: bold; color: #e2e8f0; }
        .metric-rmse { color: #38bdf8; }
        .metric-m { color: #a78bfa; }
        .metric-w { color: #fbbf24; }
        .days-highlight { display: flex; justify-content: space-between; align-items: center; background: linear-gradient(90deg, rgba(15,23,42,0.8) 0%, rgba(30,41,59,0.8) 100%); padding: 12px; border-radius: 8px; margin-top: 10px; border: 1px solid #334155; }
        .days-label { font-size: 12px; color: #94a3b8; }
        .days-value { font-size: 24px; font-weight: bold; color: #f87171; }
        .crash-date { font-size: 14px; color: #cbd5e1; font-family: 'Courier New', monospace; }
        .progress-container { margin-top: 12px; }
        .progress-bar { width: 100%; height: 6px; background: #334155; border-radius: 3px; overflow: hidden; }
        .progress-fill { height: 100%; background: var(--border-color); border-radius: 3px; transition: width 1s ease; }
        .critical-alert { background: linear-gradient(135deg, #7f1d1d 0%, #991b1b 100%); border: 1px solid #dc2626; border-radius: 12px; padding: 20px; margin-bottom: 30px; display: flex; align-items: center; gap: 20px; box-shadow: 0 10px 30px rgba(220,38,38,0.3); }
        .alert-icon-big { font-size: 40px; animation: pulse 2s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        .alert-content h2 { color: #fca5a5; margin-bottom: 5px; }
        .legend-box { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; margin-top: 30px; }
        .legend-title { color: #f8fafc; margin-bottom: 15px; font-size: 16px; }
        .legend-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 15px; font-size: 13px; color: #94a3b8; line-height: 1.6; }
        .empty-state { text-align: center; padding: 40px; color: #64748b; font-style: italic; background: rgba(30,41,59,0.3); border-radius: 12px; border: 2px dashed #334155; }
    </style>
</head>
<body>
    <div class="header">
        <h1>LPPL 模型扫描监控台</h1>
        <div class="subtitle">实时风险监控 | 数据更新: {current_time}</div>
    </div>

    {critical_alert}

    <div class="time-section">
        <div class="section-header short-term">
            <span class="section-icon">📊</span>
            <div>
                <div class="section-title">短期扫描</div>
                <div style="font-size: 12px; color: #64748b; margin-top: 4px;">周期: 70-200天 | 适配游资热点与情绪驱动</div>
            </div>
            <div class="section-desc">按 RMSE 排序</div>
        </div>
        <div class="cards-grid">{short_term_cards}</div>
    </div>

    <div class="time-section">
        <div class="section-header medium-term">
            <span class="section-icon">📈</span>
            <div>
                <div class="section-title">中期扫描</div>
                <div style="font-size: 12px; color: #64748b; margin-top: 4px;">周期: 300-500天 | 适配行业轮动与结构</div>
            </div>
            <div class="section-desc">按 RMSE 排序</div>
        </div>
        <div class="cards-grid">{medium_term_cards}</div>
    </div>

    <div class="time-section">
        <div class="section-header long-term">
            <span class="section-icon">📅</span>
            <div>
                <div class="section-title">长期扫描</div>
                <div style="font-size: 12px; color: #64748b; margin-top: 4px;">周期: 520-700天 | 适配长期趋势与基本面</div>
            </div>
            <div class="section-desc">按 RMSE 排序</div>
        </div>
        <div class="cards-grid">{long_term_cards}</div>
    </div>

    <div class="time-section">
        <div class="section-header all-codes">
            <span class="section-icon">📋</span>
            <div>
                <div class="section-title">所有代码</div>
                <div style="font-size: 12px; color: #64748b; margin-top: 4px;">汇总所有指数的扫描结果</div>
            </div>
            <div class="section-desc">按 RMSE 排序</div>
        </div>
        <div class="cards-grid">{all_codes_cards}</div>
    </div>

    <div class="legend-box">
        <div class="legend-title">📋 指标说明与结果解读</div>
        <div class="legend-grid">
            <div><strong style="color: #4ade80;">所有代码</strong><br>汇总所有指数的扫描结果，按 RMSE 排序，方便整体了解市场风险状况。</div>
            <div><strong style="color: #38bdf8;">短期扫描 (70-200天)</strong><br>适配热点轮动与情绪驱动，RMSE通常较低，预测时效性强。</div>
            <div><strong style="color: #fbbf24;">中期扫描 (300-500天)</strong><br>适配行业结构与估值回归，可观察资金流向与板块轮动。</div>
            <div><strong style="color: #a78bfa;">长期扫描 (520-700天)</strong><br>适配长期趋势与基本面，可观察大周期顶部与反转信号。</div>
            <div><strong style="color: #f87171;">关键指标</strong><br>RMSE&lt;0.02(优秀)、0.02-0.05(良好)、&gt;0.08(较差)；m最佳值0.1-0.5；w最佳值6-13(接近8最佳)。</div>
        </div>
    </div>
</body>
</html>
        """

        all_codes_data = []
        short_term_data = []
        medium_term_data = []
        long_term_data = []

        for row in report_data:
            if len(row) >= 12:
                (
                    name,
                    symbol,
                    time_span,
                    window,
                    rmse,
                    m,
                    w,
                    days_left,
                    crash_date,
                    risk,
                    bottom_signal,
                    bottom_strength,
                ) = row[:12]
            elif len(row) == 10:
                name, symbol, time_span, window, rmse, m, w, days_left, crash_date, risk = row
                bottom_signal = "无抄底信号"
                bottom_strength = "0.00"
            else:
                continue

            window = int(window)
            rmse_val = float(rmse)

            all_codes_data.append(
                (
                    name,
                    symbol,
                    time_span,
                    window,
                    rmse,
                    m,
                    w,
                    days_left,
                    crash_date,
                    risk,
                    rmse_val,
                    bottom_signal,
                    bottom_strength,
                )
            )

            if time_span == "短期":
                short_term_data.append(
                    (
                        name,
                        symbol,
                        window,
                        rmse,
                        m,
                        w,
                        days_left,
                        crash_date,
                        risk,
                        rmse_val,
                        bottom_signal,
                        bottom_strength,
                    )
                )
            elif time_span == "中期":
                medium_term_data.append(
                    (
                        name,
                        symbol,
                        window,
                        rmse,
                        m,
                        w,
                        days_left,
                        crash_date,
                        risk,
                        rmse_val,
                        bottom_signal,
                        bottom_strength,
                    )
                )
            elif time_span == "长期":
                long_term_data.append(
                    (
                        name,
                        symbol,
                        window,
                        rmse,
                        m,
                        w,
                        days_left,
                        crash_date,
                        risk,
                        rmse_val,
                        bottom_signal,
                        bottom_strength,
                    )
                )

        def sort_by_index_order(data):
            return sorted(
                data,
                key=lambda x: index_order.index(x[1]) if x[1] in index_order else len(index_order),
            )

        all_codes_data = sort_by_index_order(all_codes_data)
        short_term_data = sort_by_index_order(short_term_data)
        medium_term_data = sort_by_index_order(medium_term_data)
        long_term_data = sort_by_index_order(long_term_data)

        critical_alert = ""
        high_risk_items = []

        for data in [short_term_data, medium_term_data, long_term_data]:
            for item in data:
                if len(item) >= 12:
                    (
                        name,
                        symbol,
                        window,
                        rmse,
                        m,
                        w,
                        days_left,
                        crash_date,
                        risk,
                        rmse_val,
                        bottom_signal,
                        bottom_strength,
                    ) = item[:12]
                else:
                    name, symbol, window, rmse, m, w, days_left, crash_date, risk, rmse_val = item[
                        :10
                    ]
                    bottom_signal = ""
                risk_str = str(risk) if risk else ""
                if "极高" in risk_str or (
                    "高" in risk_str and float(str(days_left).split()[0]) < 20
                ):
                    high_risk_items.append((name, symbol, days_left, crash_date))

        if high_risk_items:
            alert_content = ""
            for item in high_risk_items:
                name, symbol, days_left, crash_date = item
                alert_content += f"<strong>{name}({symbol})</strong> 预计{days_left}后于 {crash_date} 达到临界点，<br>"

            critical_alert = f"""
            <div class="critical-alert">
                <div class="alert-icon-big">⚠️</div>
                <div class="alert-content">
                    <h2>高风险预警</h2>
                    <p style="color: #fecaca; line-height: 1.6;">
                        {alert_content}
                        请注意市场短期波动风险，建议谨慎操作。
                    </p>
                </div>
            </div>
            """

        def generate_cards(data, border_color):
            cards = []
            for item in data:
                if len(item) >= 12:
                    (
                        name,
                        symbol,
                        time_span,
                        window,
                        rmse,
                        m,
                        w,
                        days_left,
                        crash_date,
                        risk,
                        bottom_signal,
                        bottom_strength,
                    ) = item[:12]
                    rmse_val = float(rmse) if isinstance(rmse, str) else rmse
                elif len(item) == 11:
                    (
                        name,
                        symbol,
                        time_span,
                        window,
                        rmse,
                        m,
                        w,
                        days_left,
                        crash_date,
                        risk,
                        rmse_val,
                    ) = item
                else:
                    name, symbol, window, rmse, m, w, days_left, crash_date, risk, rmse_val = item[
                        :10
                    ]
                    rmse_val = float(rmse) if isinstance(rmse, str) else rmse

                risk_class = "medium"
                risk_str = str(risk) if risk else ""
                if "极高" in risk_str:
                    risk_class = "danger"
                elif "高" in risk_str:
                    risk_class = "warning"

                progress_width = min(100, int((1 - min(rmse_val, 0.1) / 0.1) * 100))

                card = f"""
                <div class="index-card" style="--border-color: {border_color};">
                    <div class="card-header">
                        <div class="index-info">
                            <h3>{name}</h3>
                            <span class="index-code">{symbol}</span>
                        </div>
                        <span class="risk-badge {risk_class}">{risk}</span>
                    </div>
                    <div class="metrics-row">
                        <div class="metric">
                            <div class="metric-label">窗口(天)</div>
                            <div class="metric-value">{window}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">RMSE</div>
                            <div class="metric-value metric-rmse">{rmse}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">m / w</div>
                            <div class="metric-value" style="font-size: 12px;">{m} / {w}</div>
                        </div>
                    </div>
                    <div class="days-highlight">
                        <div>
                            <div class="days-label">距离崩盘</div>
                        </div>
                        <div style="text-align: right;">
                            <div class="days-value">{days_left}</div>
                            <div class="crash-date">{crash_date}</div>
                        </div>
                    </div>
                    <div class="progress-container">
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: {progress_width}%; background: {border_color};"></div>
                        </div>
                    </div>
                </div>
                """
                cards.append(card)

            if not cards:
                cards.append('<div class="empty-state">暂无扫描数据</div>')

            return "".join(cards)

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        html_content = html_template.replace("{current_time}", current_time)
        html_content = html_content.replace("{critical_alert}", critical_alert)
        html_content = html_content.replace(
            "{all_codes_cards}", generate_cards(all_codes_data, "#4ade80")
        )
        html_content = html_content.replace(
            "{short_term_cards}", generate_cards(short_term_data, "#38bdf8")
        )
        html_content = html_content.replace(
            "{medium_term_cards}", generate_cards(medium_term_data, "#fbbf24")
        )
        html_content = html_content.replace(
            "{long_term_cards}", generate_cards(long_term_data, "#a78bfa")
        )

        return html_content

    def save_html(self, html_content: str, filename: str = None, data_date: str = None) -> str:
        if not filename:
            if data_date is None:
                data_date = datetime.now().strftime("%Y%m%d")
            filename = f"lppl_report_{data_date}.html"

        file_path = os.path.join(self.output_dir, filename)

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            logger.info(f"HTML report saved to: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"Error saving HTML report: {e}")
            return None

    def generate_report(self, report_data: List, data_date: str = None) -> str:
        if not report_data:
            logger.warning("No report data provided")
            return None

        html_content = self.generate_html(report_data)
        html_path = self.save_html(html_content, data_date=data_date)

        return html_path
