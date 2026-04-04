# 策略回报率审计报告

日期：2026-04-01

## 1. 审计目标

本报告用于审计以下 5 个已落盘参数组合的收益汇报是否准确：

- `000001.SH`
- `000016.SH`
- `000300.SH`
- `399001.SZ`
- `000905.SH`

审计对象包括：

1. 指数持有总回报
2. 指数持有年化回报
3. 策略总回报
4. 策略年化回报
5. 年化超额回报

## 2. 本地回测口径核验

本项目回测汇总口径定义在 [backtest.py](/home/james/Documents/Project/lppl/src/investment/backtest.py#L1234C1)：

- `annualized_return = final_nav ** (252 / len(equity_df)) - 1`
- `benchmark_annualized_return = benchmark_nav ** (252 / len(equity_df)) - 1`
- `annualized_excess_return = annualized_return - benchmark_annualized_return`

关键结论：

1. 年化口径基于 `equity_df` 的交易日行数，不是自然日。
2. “年化超额回报”不是总回报差，而是“策略年化 - 基准年化”。
3. 本次 5 个指数的 `summary.csv` 已用对应 `equity_*.csv` 逐只复算，结果完全一致。

本地验证文件：

- [summary_000001_SH_single_window.csv](/home/james/Documents/Project/lppl/output/cli_verify/000001_SH/summary/summary_000001_SH_single_window.csv)
- [summary_000016_SH_single_window.csv](/home/james/Documents/Project/lppl/output/cli_verify/000016_SH/summary/summary_000016_SH_single_window.csv)
- [summary_000300_SH_single_window.csv](/home/james/Documents/Project/lppl/output/cli_verify/000300_SH/summary/summary_000300_SH_single_window.csv)
- [summary_399001_SZ_single_window.csv](/home/james/Documents/Project/lppl/output/cli_verify/399001_SZ/summary/summary_399001_SZ_single_window.csv)
- [summary_000905_SH_single_window.csv](/home/james/Documents/Project/lppl/output/cli_verify/000905_SH/summary/summary_000905_SH_single_window.csv)

- [equity_000001_SH_single_window.csv](/home/james/Documents/Project/lppl/output/cli_verify/000001_SH/raw/equity_000001_SH_single_window.csv)
- [equity_000016_SH_single_window.csv](/home/james/Documents/Project/lppl/output/cli_verify/000016_SH/raw/equity_000016_SH_single_window.csv)
- [equity_000300_SH_single_window.csv](/home/james/Documents/Project/lppl/output/cli_verify/000300_SH/raw/equity_000300_SH_single_window.csv)
- [equity_399001_SZ_single_window.csv](/home/james/Documents/Project/lppl/output/cli_verify/399001_SZ/raw/equity_399001_SZ_single_window.csv)
- [equity_000905_SH_single_window.csv](/home/james/Documents/Project/lppl/output/cli_verify/000905_SH/raw/equity_000905_SH_single_window.csv)

## 3. 互联网外部校准方法

互联网只能外部核验指数本身表现，也就是 benchmark leg，不能独立复现本地策略净值。

因此本报告采用两种外部校准方法：

1. 官方 factsheet 的 5 年年化收益率，对照本地同截止日重算结果。
2. 主流历史行情页面中的单日收盘点位，对照本地原始数据点位。

## 4. 官方 factsheet 对照

### 4.1 上证50 `000016.SH`

官方来源：

- 中证指数 factsheet: https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000016factsheet.pdf

官方披露：

- 截止 `2026-02-27`
- 5 年年化：`-4.15%`

本地同窗重算：

- 起点交易日：`2021-03-01`
- 终点交易日：`2026-02-27`
- 本地 5 年年化：`-4.48%`

判断：

- 与官方差异约 `0.33%`
- 属于可接受误差范围，说明本地 benchmark 数据口径基本对齐官方指数

### 4.2 沪深300 `000300.SH`

官方来源：

- 中证指数 factsheet: https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000300factsheet.pdf

官方披露：

- 截止 `2026-02-27`
- 5 年年化：`-2.46%`

本地同窗重算：

- 起点交易日：`2021-03-01`
- 终点交易日：`2026-02-27`
- 本地 5 年年化：`-2.87%`

判断：

- 与官方差异约 `0.41%`
- 口径接近，可视为通过外部校准

### 4.3 中证500 `000905.SH`

官方来源：

- 中证指数 factsheet: https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000905factsheet.pdf

官方披露：

- 截止 `2026-02-27`
- 5 年年化：`6.35%`

本地同窗重算：

- 起点交易日：`2021-03-01`
- 终点交易日：`2026-02-27`
- 本地 5 年年化：`6.19%`

判断：

- 与官方差异约 `0.16%`
- 一致性较高，可视为强校准通过

## 5. 单日点位校验

### 5.1 沪深300 `000300.SH`

外部来源：

- Investing 历史数据页: https://www.investing.com/indices/csi300-historical-data

校验点：

- `2026-03-27` 外部页面显示收盘 `4,502.57`
- 本地原始数据同日收盘 `4,502.57`

判断：

- 单点完全一致

### 5.2 深证成指 `399001.SZ`

外部来源：

- 深交所英文市场月报: https://docs.static.szse.cn/www/English/siteMarketData/publication/monthly/W020240411656338306823.html

校验点：

- `2024-09-30` 外部资料显示深证成指 `10,529.76`
- 本地原始数据同日收盘 `10,529.76`

判断：

- 单点完全一致

## 6. 审计后确认的收益表

下表口径均为：

- 总回报：回测区间内净值变化
- 年化：按 252 个交易日年化
- 年化超额：策略年化减持有年化

| 指数 | 持有总回报 | 策略总回报 | 持有年化 | 策略年化 | 年化超额 | 最大回撤 | 交易次数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 000001.SH | 26.85% | 32.41% | 4.05% | 4.80% | 0.75% | -21.63% | 6 |
| 000016.SH | -8.20% | 2.38% | -1.42% | 0.39% | 1.81% | -21.87% | 4 |
| 000300.SH | 8.44% | 44.78% | 1.36% | 6.37% | 5.01% | -30.30% | 5 |
| 399001.SZ | 29.34% | 50.11% | 4.39% | 7.02% | 2.63% | -26.35% | 9 |
| 000905.SH | 44.19% | 53.54% | 6.30% | 7.42% | 1.12% | -21.65% | 10 |

## 7. 审计结论

结论分为两层：

1. 作为本项目回测报告，这 5 个指数的 `策略年化`、`持有年化`、`年化超额` 计算是正确的，已被源码公式和原始净值文件复算验证。
2. 作为外部市场数据，这 5 个指数里的 `000016.SH`、`000300.SH`、`000905.SH` 已被官方 factsheet 的 5 年年化收益率校准，`399001.SZ` 已被深交所公开点位校准，`000001.SH` 虽缺少同级别强校准材料，但未发现与其余数据体系冲突。

因此，本次收益汇报可视为：

- 本地回测口径：通过
- benchmark 数据外部校准：基本通过
- strategy leg 外部独立复现：无法通过互联网单独完成

## 8. 风险提示

1. 官方 factsheet 的观察窗口与本次完整回测窗口不完全一致，因此它只能用于校准 benchmark 数据质量，不能直接替代回测报告。
2. 外部网站如 Investing 可用于点位交叉验证，但不应替代官方指数公司或交易所数据。
3. 策略净值依赖本地交易逻辑、手续费、滑点和执行规则，互联网资料无法独立验证该部分结果。
