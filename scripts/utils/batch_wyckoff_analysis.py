#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wyckoff 批量分析工具
对 8 个主要指数进行威科夫分析并生成报告
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# 添加项目根路径
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.manager import DataManager
from src.wyckoff.analyzer import WyckoffAnalyzer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 8 个主要指数
SYMBOLS = {
    '000001.SH': '上证综指',
    '399001.SZ': '深证成指',
    '399006.SZ': '创业板指',
    '000016.SH': '上证 50',
    '000300.SH': '沪深 300',
    '000905.SH': '中证 500',
    '000852.SH': '中证 1000',
    '932000.SH': '中证 2000',
}


def analyze_symbol(symbol: str, name: str, output_dir: str, lookback: int = 120):
    """分析单个指数"""
    logger.info(f"\n{'='*60}")
    logger.info(f"正在分析：{symbol} ({name})")
    logger.info(f"{'='*60}")
    
    try:
        # 加载数据
        data_manager = DataManager()
        df = data_manager.get_data(symbol)
        
        if df is None or df.empty:
            logger.warning(f"无法获取 {symbol} 数据，跳过")
            return None
        
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        
        logger.info(f"数据加载完成：{len(df)} 条记录，最新日期：{df['date'].iloc[-1].date()}")
        
        # 执行 Wyckoff 分析
        analyzer = WyckoffAnalyzer(lookback_days=lookback)
        report = analyzer.analyze(df, symbol=symbol, period="日线")
        
        # 生成输出目录
        symbol_slug = symbol.replace(".", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 保存 Markdown 报告
        report_dir = os.path.join(output_dir, "reports")
        os.makedirs(report_dir, exist_ok=True)
        
        report_file = os.path.join(report_dir, f"wyckoff_{symbol_slug}_{timestamp}.md")
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report.to_markdown())
        
        logger.info(f"报告已保存：{report_file}")
        
        # 打印摘要
        print("\n" + "="*60)
        print(f"{symbol} - {name} Wyckoff 分析摘要")
        print("="*60)
        print(f"阶段：{report.structure.phase.value}")
        print(f"BC 点：{'找到' if report.structure.bc_point else '未找到'}")
        print(f"SC 点：{'找到' if report.structure.sc_point else '未找到'}")
        print(f"信号类型：{report.signal.signal_type}")
        print(f"置信度：{report.signal.confidence.value}")
        print(f"交易决策：{report.trading_plan.direction}")
        print(f"描述：{report.signal.description[:50]}..." if len(report.signal.description) > 50 else f"描述：{report.signal.description}")
        print("="*60)
        
        return {
            'symbol': symbol,
            'name': name,
            'phase': report.structure.phase.value,
            'bc_found': report.structure.bc_point is not None,
            'sc_found': report.structure.sc_point is not None,
            'signal_type': report.signal.signal_type,
            'confidence': report.signal.confidence.value,
            'decision': report.trading_plan.direction,
            'report_file': report_file,
        }
        
    except Exception as e:
        logger.error(f"分析 {symbol} 失败：{e}", exc_info=True)
        return None


def generate_summary(results: list, output_dir: str):
    """生成分析摘要汇总"""
    logger.info("\n生成分析摘要汇总...")
    
    summary_file = os.path.join(output_dir, "summary", "wyckoff_batch_summary.csv")
    os.makedirs(os.path.dirname(summary_file), exist_ok=True)
    
    import pandas as pd
    df_summary = pd.DataFrame(results)
    df_summary.to_csv(summary_file, index=False, encoding='utf-8-sig')
    
    logger.info(f"摘要汇总已保存：{summary_file}")
    
    # 打印汇总表格
    print("\n" + "="*120)
    print("Wyckoff 批量分析汇总")
    print("="*120)
    print(df_summary.to_string(index=False))
    print("="*120)
    
    # 统计信息
    total = len(results)
    bc_found_count = sum(1 for r in results if r['bc_found'])
    sc_found_count = sum(1 for r in results if r['sc_found'])
    long_setups = sum(1 for r in results if '做多' in r['decision'])
    
    print("\n统计信息:")
    print(f"  - 分析指数数量：{total}")
    print(f"  - 找到 BC 点：{bc_found_count} ({bc_found_count/total*100:.1f}%)")
    print(f"  - 找到 SC 点：{sc_found_count} ({sc_found_count/total*100:.1f}%)")
    print(f"  - 做多机会：{long_setups} ({long_setups/total*100:.1f}%)")
    print("="*120)


def main():
    """主函数"""
    logger.info("开始 Wyckoff 批量分析...")
    
    # 输出目录
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = f"output/wyckoff_batch_{timestamp}"
    os.makedirs(output_dir, exist_ok=True)
    
    logger.info(f"输出目录：{output_dir}")
    
    # 批量分析
    results = []
    for symbol, name in SYMBOLS.items():
        result = analyze_symbol(symbol, name, output_dir)
        if result:
            results.append(result)
    
    # 生成汇总
    if results:
        generate_summary(results, output_dir)
        
        logger.info(f"\n批量分析完成！共分析 {len(results)} 个指数")
        logger.info(f"结果保存在：{output_dir}")
    else:
        logger.error("没有成功分析任何指数")


if __name__ == "__main__":
    import pandas as pd
    main()
