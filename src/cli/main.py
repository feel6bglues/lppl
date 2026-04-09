# -*- coding: utf-8 -*-
import logging
import sys
from datetime import datetime

logger = logging.getLogger(__name__)


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def main() -> int:
    setup_logging()
    logger.info("=" * 80)
    logger.info("LPPL模型扫描系统 - 主程序入口")
    logger.info(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 80)

    logger.info("[1/3] 数据管理模块 - 检查数据可用性")
    logger.info("-" * 60)

    data_manager = None
    computation = None
    html_generator = None

    try:
        from src.data.manager import DataManager, summarize_update_results
        data_manager = DataManager()
        data_results = data_manager.update_all_data()
        success_count, failed_count = summarize_update_results(data_results)

        logger.info(f"数据检查完成: 可用 {success_count} 个, 不可用 {failed_count} 个")

        if failed_count == len(data_results):
            logger.error("错误: 所有数据不可用，无法继续执行")
            return 1

        data_dict = data_manager.get_all_indices_data()

        if not data_dict:
            logger.error("错误: 无法加载任何有效数据")
            return 1

        logger.info(f"成功加载 {len(data_dict)} 个指数数据")
    except FileNotFoundError as e:
        logger.error(f"错误: 数据目录不存在 - {e}")
        return 1
    except ImportError as e:
        logger.error(f"错误: 模块导入失败 - {e}")
        return 1
    except Exception as e:
        logger.error(f"错误: 数据管理模块执行失败 - {type(e).__name__}: {e}")
        return 1

    logger.info("")
    logger.info("[2/3] 多线程计算模块 - 执行LPPL模型扫描")
    logger.info("-" * 60)

    try:
        from src.computation import LPPLComputation
        computation = LPPLComputation()
        report_data, params_data = computation.run_computation(data_dict, close_executor=True)

        if not report_data:
            logger.warning("警告: 计算模块未返回任何结果")
            markdown_path = None
            data_date = datetime.now().strftime('%Y%m%d')
        else:
            logger.info(f"计算完成: 生成 {len(report_data)} 条扫描结果")

            if params_data:
                data_dates = []
                for param in params_data:
                    last_date_str = param.get("last_date")
                    if last_date_str:
                        try:
                            from datetime import datetime as dt
                            data_date_val = dt.strptime(last_date_str, '%Y-%m-%d')
                            data_dates.append(data_date_val)
                        except ValueError:
                            pass

                if data_dates:
                    latest_data_date = max(data_dates)
                    data_date = latest_data_date.strftime('%Y%m%d')
                else:
                    data_date = datetime.now().strftime('%Y%m%d')
            else:
                data_date = datetime.now().strftime('%Y%m%d')

            markdown_path = computation.generate_markdown(report_data, data_date=data_date)
            if not markdown_path:
                logger.warning("警告: 无法生成Markdown报告")

            if params_data:
                params_path = computation.save_params_to_json(params_data, data_date=data_date)
                if params_path:
                    logger.info(f"参数文件保存成功: {params_path}")
    except ImportError as e:
        logger.error(f"错误: 计算模块导入失败 - {e}")
        return 1
    except MemoryError as e:
        logger.error(f"错误: 内存不足 - {e}")
        return 1
    except Exception as e:
        logger.error(f"错误: 计算模块执行失败 - {type(e).__name__}: {e}")
        return 1

    logger.info("")
    logger.info("[3/3] HTML生成模块 - 生成可视化报告")
    logger.info("-" * 60)

    try:
        from src.reporting import HTMLGenerator
        html_generator = HTMLGenerator()

        if not report_data:
            logger.warning("没有报告数据，跳过HTML生成")
        else:
            html_path = html_generator.generate_report(report_data, data_date=data_date)

            if html_path:
                logger.info(f"HTML报告生成成功: {html_path}")
            else:
                logger.warning("警告: HTML报告生成失败")
    except ImportError as e:
        logger.error(f"错误: HTML生成模块导入失败 - {e}")
        return 1
    except Exception as e:
        logger.error(f"错误: HTML生成模块执行失败 - {type(e).__name__}: {e}")
        return 1

    logger.info("")
    logger.info("=" * 80)
    logger.info("LPPL模型扫描系统 - 执行完成")
    logger.info(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 80)
    logger.info("执行完成! 您可以在浏览器中打开HTML文件查看详细结果。")

    return 0


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()

    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')

    exit_code = 0
    try:
        exit_code = main()
    except KeyboardInterrupt:
        logger.info("\n用户强制停止脚本")
        exit_code = 0
    except SystemExit as e:
        exit_code = e.code
    except Exception as e:
        logger.error(f"\n发生未捕获异常: {type(e).__name__}: {e}")
        exit_code = 1

    sys.exit(exit_code)
