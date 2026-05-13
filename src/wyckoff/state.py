# -*- coding: utf-8 -*-
"""
Wyckoff 状态管理器
负责分析状态的持久化、连续性追踪和 Spring 冷冻期管理
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

from src.wyckoff.models import AnalysisResult, AnalysisState

logger = logging.getLogger(__name__)


class StateManager:
    """状态管理器 - 管理分析状态的持久化和连续性"""

    def __init__(self):
        self.spring_freeze_days = 3  # Spring 冷冻期天数（T+3）

    def update_state(
        self,
        symbol: str,
        analysis_result: AnalysisResult,
        output_path: str,
        prev_state: Optional[AnalysisState] = None,
    ) -> AnalysisState:
        """
        更新分析状态

        Args:
            symbol: 标的代码
            analysis_result: 分析结果
            output_path: 状态文件输出路径
            prev_state: 上次状态（可选）

        Returns:
            AnalysisState 更新后的状态
        """
        # 创建新状态
        state = AnalysisState()

        # 基本信息
        state.symbol = symbol
        state.asset_type = analysis_result.asset_type
        state.analysis_date = analysis_result.analysis_date

        # 上次分析结果
        state.last_phase = analysis_result.phase
        state.last_micro_action = analysis_result.micro_action
        state.last_confidence = analysis_result.confidence

        # 关键状态
        state.bc_found = analysis_result.bc_found
        state.spring_detected = analysis_result.spring_detected

        # Spring 冷冻期管理
        state.freeze_until = self._calculate_freeze_until(analysis_result, prev_state)
        state.watch_status = self._determine_watch_status(state)

        # 触发器状态
        if analysis_result.decision == "long_setup":
            state.trigger_armed = True
            state.trigger_text = analysis_result.trigger
            state.invalid_level = analysis_result.invalidation
            state.target_1 = analysis_result.target_1
        else:
            state.trigger_armed = False
            state.trigger_text = ""
            state.invalid_level = ""
            state.target_1 = ""

        # 上下文
        state.weekly_context = self._extract_weekly_context(analysis_result)
        state.intraday_context = self._extract_intraday_context(analysis_result)
        state.conflict_summary = (
            "; ".join(analysis_result.conflicts) if analysis_result.conflicts else ""
        )

        # 决策记录
        state.last_decision = analysis_result.decision
        state.abandon_reason = analysis_result.abandon_reason

        # 保存状态
        self.save_state(state, output_path)

        return state

    @staticmethod
    def _add_trading_days(start_date: "datetime", n_days: int) -> "datetime":
        """
        在给定日期加上 n 个交易日（跳过周末）。

        注意：此方法仅处理周末，不处理 A 股法定节假日。
        如需精确的 A 股交易日历，请接入 exchange_calendars 或 tushare 节假日数据。
        """
        current = start_date
        added = 0
        while added < n_days:
            current += timedelta(days=1)
            # 周一=0 … 周五=4，跳过周六(5)和周日(6)
            if current.weekday() < 5:
                added += 1
        return current

    def _calculate_freeze_until(
        self, analysis_result: AnalysisResult, prev_state: Optional[AnalysisState]
    ) -> Optional[str]:
        """计算 Spring 冷冻期截止日期（SPEC §9.2：T+3 交易日）"""
        if not analysis_result.spring_detected:
            # 没有检测到 Spring，继承上次状态
            if prev_state:
                return prev_state.freeze_until
            return None

        # 检测到 Spring，设置冷冻期
        try:
            analysis_date = datetime.strptime(analysis_result.analysis_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            analysis_date = datetime.now()

        # 使用交易日偏移（跳过周末），而非简单日历天
        freeze_until = self._add_trading_days(analysis_date, self.spring_freeze_days)
        return freeze_until.strftime("%Y-%m-%d")

    def _determine_watch_status(self, state: AnalysisState) -> str:
        """确定观察状态"""
        if state.freeze_until:
            try:
                freeze_date = datetime.strptime(state.freeze_until, "%Y-%m-%d")
                if datetime.now() <= freeze_date:
                    return "cooling_down"
            except (ValueError, TypeError):
                pass

        if state.trigger_armed:
            return "watching"

        return "none"

    def _extract_weekly_context(self, analysis_result: AnalysisResult) -> str:
        """提取周线上下文"""
        # 简化版本：从 phase 推断
        if analysis_result.phase == "accumulation":
            return "周线可能在筑底"
        elif analysis_result.phase == "markup":
            return "周线可能在上升"
        elif analysis_result.phase == "distribution":
            return "周线可能在派发"
        elif analysis_result.phase == "markdown":
            return "周线可能在下跌"
        return ""

    def _extract_intraday_context(self, analysis_result: AnalysisResult) -> str:
        """提取日内上下文"""
        # 简化版本：从 micro_action 推断
        if analysis_result.micro_action:
            return f"日内动作：{analysis_result.micro_action}"
        return ""

    def save_state(self, state: AnalysisState, output_path: str) -> None:
        """保存状态到 JSON 文件"""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # 转换为字典
        state_dict = {
            "symbol": state.symbol,
            "asset_type": state.asset_type,
            "analysis_date": state.analysis_date,
            "last_phase": state.last_phase,
            "last_micro_action": state.last_micro_action,
            "last_confidence": state.last_confidence,
            "bc_found": state.bc_found,
            "spring_detected": state.spring_detected,
            "freeze_until": state.freeze_until,
            "watch_status": state.watch_status,
            "trigger_armed": state.trigger_armed,
            "trigger_text": state.trigger_text,
            "invalid_level": state.invalid_level,
            "target_1": state.target_1,
            "weekly_context": state.weekly_context,
            "intraday_context": state.intraday_context,
            "conflict_summary": state.conflict_summary,
            "last_decision": state.last_decision,
            "abandon_reason": state.abandon_reason,
        }

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(state_dict, f, ensure_ascii=False, indent=2)

        logger.info(f"状态已保存到：{output_file}")

    def load_state(self, input_path: str) -> Optional[AnalysisState]:
        """从 JSON 文件加载状态"""
        input_file = Path(input_path)
        if not input_file.exists():
            logger.warning(f"状态文件不存在：{input_path}")
            return None

        with open(input_file, "r", encoding="utf-8") as f:
            state_dict = json.load(f)

        # 转换为 AnalysisState
        state = AnalysisState(
            symbol=state_dict.get("symbol", ""),
            asset_type=state_dict.get("asset_type", "stock"),
            analysis_date=state_dict.get("analysis_date", ""),
            last_phase=state_dict.get("last_phase", ""),
            last_micro_action=state_dict.get("last_micro_action", ""),
            last_confidence=state_dict.get("last_confidence", "D"),
            bc_found=state_dict.get("bc_found", False),
            spring_detected=state_dict.get("spring_detected", False),
            freeze_until=state_dict.get("freeze_until"),
            watch_status=state_dict.get("watch_status", "none"),
            trigger_armed=state_dict.get("trigger_armed", False),
            trigger_text=state_dict.get("trigger_text", ""),
            invalid_level=state_dict.get("invalid_level", ""),
            target_1=state_dict.get("target_1", ""),
            weekly_context=state_dict.get("weekly_context", ""),
            intraday_context=state_dict.get("intraday_context", ""),
            conflict_summary=state_dict.get("conflict_summary", ""),
            last_decision=state_dict.get("last_decision", ""),
            abandon_reason=state_dict.get("abandon_reason", ""),
        )

        return state

    def is_in_freeze_period(self, state: AnalysisState) -> bool:
        """检查是否在冷冻期"""
        if not state.freeze_until:
            return False

        try:
            freeze_date = datetime.strptime(state.freeze_until, "%Y-%m-%d")
            return datetime.now() <= freeze_date
        except (ValueError, TypeError):
            return False

    def get_continuity_report(self, symbol: str, state_dir: str) -> Dict:
        """
        生成连续性报告

        Args:
            symbol: 标的代码
            state_dir: 状态文件目录

        Returns:
            连续性报告字典
        """
        state_file = Path(state_dir) / f"{symbol.replace('.', '_')}_wyckoff_state.json"
        state = self.load_state(str(state_file))

        if not state:
            return {"error": "无法加载状态文件"}

        return {
            "symbol": state.symbol,
            "last_analysis": state.analysis_date,
            "current_phase": state.last_phase,
            "confidence": state.last_confidence,
            "spring_detected": state.spring_detected,
            "freeze_status": state.watch_status,
            "freeze_until": state.freeze_until,
            "trigger_armed": state.trigger_armed,
            "last_decision": state.last_decision,
            "conflicts": state.conflict_summary,
        }
