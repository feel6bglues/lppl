# -*- coding: utf-8 -*-
"""
Wyckoff 图像引擎
负责扫描图表文件夹、提取视觉证据、识别时间周期与图像质量
"""

import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.wyckoff.models import ChartManifest, ChartManifestItem, ImageEvidenceBundle

logger = logging.getLogger(__name__)

# 支持的图片格式
SUPPORTED_IMAGE_FORMATS = {".png", ".jpg", ".jpeg", ".webp"}

# 时间周期识别模式
TIMEFRAME_PATTERNS = {
    "weekly": [r"weekly", r"周线", r"w[1-9]*", r"week"],
    "daily": [r"daily", r"日线", r"d[1-9]*", r"day"],
    "60m": [r"60m", r"60 分钟", r"60min"],
    "30m": [r"30m", r"30 分钟", r"30min"],
    "15m": [r"15m", r"15 分钟", r"15min"],
    "5m": [r"5m", r"5 分钟", r"5min"],
}

# 标的识别模式
SYMBOL_PATTERNS = [
    r"(\d{6}\.\w{2,3})",  # 600519.SH, 000001.SZ
    r"(\d{6})",  # 600519
]


class ImageEngine:
    """图像引擎 - 负责扫描和处理图表图片"""

    def __init__(self, config=None):
        self.supported_formats = SUPPORTED_IMAGE_FORMATS
        self.timeframe_patterns = TIMEFRAME_PATTERNS
        self.symbol_patterns = SYMBOL_PATTERNS
        self.config = config

    def scan_chart_directory(
        self, chart_dir: str, target_symbol: Optional[str] = None, recursive: bool = True
    ) -> Dict[str, List[dict]]:
        """
        扫描图表文件夹

        Args:
            chart_dir: 图表文件夹路径
            target_symbol: 目标标的代码（可选）
            recursive: 是否递归扫描子目录

        Returns:
            图表清单字典，包含文件信息和推断属性
        """
        chart_path = Path(chart_dir)
        if not chart_path.exists():
            logger.warning(f"图表文件夹不存在：{chart_dir}")
            return {"files": [], "warnings": [f"文件夹不存在：{chart_dir}"]}

        manifest = {"files": [], "warnings": []}

        # 扫描图片文件
        if recursive:
            image_files = list(chart_path.rglob("*"))
        else:
            image_files = list(chart_path.glob("*"))

        for file_path in image_files:
            if not file_path.is_file():
                continue

            # 检查文件格式
            suffix = file_path.suffix.lower()
            if suffix not in self.supported_formats:
                continue

            # 获取文件信息
            file_info = {
                "file_path": str(file_path),
                "file_name": file_path.name,
                "relative_dir": str(file_path.parent.relative_to(chart_path)),
                "modified_time": self._get_modified_time(file_path),
            }

            # 推断标的归属
            file_info["symbol"] = self._infer_symbol(
                file_path.name, file_path.parent.name, target_symbol
            )

            # 推断时间周期
            file_info["timeframe"] = self._infer_timeframe(file_path.name)

            # 评估图像质量（基础版本 - 基于文件大小）
            file_info["image_quality"] = self._assess_image_quality_basic(file_path)

            manifest["files"].append(file_info)

        logger.info(f"扫描完成，找到 {len(manifest['files'])} 张图片")
        return manifest

    def scan_chart_files(
        self, file_paths: List[str], target_symbol: Optional[str] = None
    ) -> Dict[str, List[dict]]:
        """
        扫描显式指定的图片文件列表 (SPEC_IMAGE_ENGINE第2.2节)

        Args:
            file_paths: 图片文件路径列表
            target_symbol: 目标标的代码（可选）

        Returns:
            图表清单字典
        """
        manifest = {"files": [], "warnings": []}

        for file_path_str in file_paths:
            file_path = Path(file_path_str)

            if not file_path.exists():
                manifest["warnings"].append(f"文件不存在：{file_path_str}")
                continue

            if not file_path.is_file():
                manifest["warnings"].append(f"不是文件：{file_path_str}")
                continue

            suffix = file_path.suffix.lower()
            if suffix not in self.supported_formats:
                manifest["warnings"].append(f"不支持格式：{file_path_str}")
                continue

            file_info = {
                "file_path": str(file_path),
                "file_name": file_path.name,
                "relative_dir": str(file_path.parent.name),
                "modified_time": self._get_modified_time(file_path),
                "symbol": self._infer_symbol(file_path.name, file_path.parent.name, target_symbol),
                "timeframe": self._infer_timeframe(file_path.name),
                "image_quality": self._assess_image_quality_basic(file_path),
            }
            manifest["files"].append(file_info)

        logger.info(f"扫描完成，找到 {len(manifest['files'])} 张图片")
        return manifest

    def _get_modified_time(self, file_path: Path) -> str:
        """获取文件修改时间"""
        try:
            mtime = os.path.getmtime(file_path)
            from datetime import datetime

            return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            logger.warning(f"无法获取文件修改时间：{file_path}, 错误：{e}")
            return "unknown"

    def _infer_symbol(
        self, file_name: str, parent_dir: str, target_symbol: Optional[str] = None
    ) -> str:
        """
        推断图片归属的标的

        优先级：
        1. 文件名包含标准 symbol
        2. 父目录名包含标准 symbol
        3. 命令行显式指定 symbol
        4. 无法归属则记为 unassigned
        """
        # 优先级 1: 文件名包含
        for pattern in self.symbol_patterns:
            match = re.search(pattern, file_name)
            if match:
                symbol = match.group(1)
                # 标准化格式
                if len(symbol) == 6 and symbol.isdigit():
                    # 尝试推断后缀
                    if symbol.startswith("6"):
                        return f"{symbol}.SH"
                    elif symbol.startswith(("0", "3")):
                        return f"{symbol}.SZ"
                return symbol

        # 优先级 2: 父目录名包含
        for pattern in self.symbol_patterns:
            match = re.search(pattern, parent_dir)
            if match:
                symbol = match.group(1)
                if len(symbol) == 6 and symbol.isdigit():
                    if symbol.startswith("6"):
                        return f"{symbol}.SH"
                    elif symbol.startswith(("0", "3")):
                        return f"{symbol}.SZ"
                return symbol

        # 优先级 3: 显式指定
        if target_symbol:
            return target_symbol

        # 优先级 4: 无法归属
        return "unassigned"

    def _infer_timeframe(self, file_name: str) -> str:
        """
        推断图片时间周期

        优先级：
        1. 文件名识别
        2. 无法识别则标为 unknown_tf
        """
        file_name_lower = file_name.lower()

        for timeframe, patterns in self.timeframe_patterns.items():
            for pattern in patterns:
                if re.search(pattern, file_name_lower, re.IGNORECASE):
                    return timeframe

        return "unknown_tf"

    def _assess_image_quality_basic(self, file_path: Path) -> str:
        """
        基础图像质量评估（基于文件大小）

        质量分级：
        - high: 文件较大，可能分辨率足够
        - medium: 中等大小
        - low: 文件较小，可能分辨率不足
        - unusable: 文件过小，可能不可用
        """
        try:
            file_size = file_path.stat().st_size

            # 简单阈值判断（单位：字节）
            if file_size > 500 * 1024:  # > 500KB
                return "high"
            elif file_size > 100 * 1024:  # > 100KB
                return "medium"
            elif file_size > 20 * 1024:  # > 20KB
                return "low"
            else:
                return "unusable"
        except Exception as e:
            logger.warning(f"无法评估图像质量：{file_path}, 错误：{e}")
            return "medium"

    def extract_visual_evidence(self, manifest: Dict[str, List[dict]]) -> ImageEvidenceBundle:
        """
        从图表清单提取视觉证据包

        Args:
            manifest: 图表清单

        Returns:
            ImageEvidenceBundle 图像证据包
        """
        files = [f["file_path"] for f in manifest.get("files", [])]
        manifest_items = [
            ChartManifestItem(
                file_path=f["file_path"],
                file_name=f["file_name"],
                relative_dir=f.get("relative_dir", ""),
                modified_time=f.get("modified_time", ""),
                symbol=f.get("symbol", "unassigned"),
                inferred_timeframe=f.get("timeframe", "unknown_tf"),
                image_quality=f.get("image_quality", "medium"),
            )
            for f in manifest.get("files", [])
        ]

        if not files:
            return ImageEvidenceBundle(
                files=[],
                detected_timeframe="unknown_tf",
                image_quality="unusable",
                trust_level="low",
            )

        # 统计时间周期
        timeframes = {}
        for f in manifest.get("files", []):
            tf = f.get("timeframe", "unknown_tf")
            timeframes[tf] = timeframes.get(tf, 0) + 1

        # 选择最常见的时间周期
        detected_timeframe = (
            max(timeframes.keys(), key=lambda k: timeframes[k]) if timeframes else "unknown_tf"
        )

        # 评估整体图像质量
        quality_counts = {}
        for f in manifest.get("files", []):
            q = f.get("image_quality", "medium")
            quality_counts[q] = quality_counts.get(q, 0) + 1

        # 选择最常见的质量等级
        quality_order = ["high", "medium", "low", "unusable"]
        overall_quality = "medium"
        for q in quality_order:
            if quality_counts.get(q, 0) > 0:
                overall_quality = q
                break

        # 确定信任级别
        if overall_quality in ["high", "medium"] and detected_timeframe != "unknown_tf":
            trust_level = "high"
        elif overall_quality == "low":
            trust_level = "low"
        else:
            trust_level = "medium"

        return ImageEvidenceBundle(
            files=files,
            detected_timeframe=detected_timeframe,
            image_quality=overall_quality,
            visual_trend="unclear",  # 基础版本暂不识别趋势
            visual_phase_hint="unclear",  # 基础版本暂不识别阶段
            visual_boundaries=[],
            visual_anomalies=[],
            visual_volume_labels="unclear",
            trust_level=trust_level,
            manifest=ChartManifest(
                files=manifest_items,
                total_count=len(manifest_items),
                usable_count=len(manifest_items),
                scan_time="",
            ),
            detected_timeframes=[detected_timeframe] if detected_timeframe != "unknown_tf" else [],
            overall_image_quality=overall_quality,
        )

    def generate_chart_manifest_json(
        self, manifest: Dict[str, List[dict]], output_path: str
    ) -> None:
        """
        生成图表清单 JSON 文件

        Args:
            manifest: 图表清单
            output_path: 输出文件路径
        """
        import json

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        logger.info(f"图表清单已保存到：{output_file}")

    def scan_and_extract(
        self,
        chart_dir: str,
        target_symbol: Optional[str] = None,
        output_manifest_path: Optional[str] = None,
    ) -> Tuple[ImageEvidenceBundle, Dict[str, List[dict]]]:
        """
        扫描图表文件夹并提取视觉证据

        Args:
            chart_dir: 图表文件夹路径
            target_symbol: 目标标的代码
            output_manifest_path: 清单输出路径（可选）

        Returns:
            (ImageEvidenceBundle, manifest) 元组
        """
        # 扫描图表文件夹
        manifest = self.scan_chart_directory(chart_dir, target_symbol)

        # 提取视觉证据
        evidence = self.extract_visual_evidence(manifest)

        # 生成清单文件
        if output_manifest_path:
            self.generate_chart_manifest_json(manifest, output_manifest_path)

        return evidence, manifest

    def run(
        self,
        chart_dir: Optional[str] = None,
        chart_files: Optional[List[str]] = None,
        explicit_symbol: Optional[str] = None,
    ) -> ImageEvidenceBundle:
        """兼容新多模态 CLI 的统一入口。"""
        if chart_files:
            manifest = self.scan_chart_files(chart_files, explicit_symbol)
        elif chart_dir:
            manifest = self.scan_chart_directory(chart_dir, explicit_symbol)
        else:
            return ImageEvidenceBundle()

        return self.extract_visual_evidence(manifest)


def main():
    """图像引擎 CLI 入口"""
    import argparse

    parser = argparse.ArgumentParser(description="Wyckoff 图像引擎")
    parser.add_argument("--chart-dir", required=True, help="图表文件夹路径")
    parser.add_argument("--symbol", default=None, help="目标标的代码")
    parser.add_argument("--output-manifest", default=None, help="清单输出路径")
    parser.add_argument("--output-dir", default="output/wyckoff", help="输出目录")

    args = parser.parse_args()

    # 创建图像引擎
    engine = ImageEngine()

    # 扫描并提取证据
    evidence, manifest = engine.scan_and_extract(args.chart_dir, args.symbol, args.output_manifest)

    # 打印结果
    logger.info(f"扫描完成，找到 {len(manifest['files'])} 张图片")
    logger.info(f"主要时间周期：{evidence.detected_timeframe}")
    logger.info(f"整体图像质量：{evidence.image_quality}")
    logger.info(f"信任级别：{evidence.trust_level}")


if __name__ == "__main__":
    main()
