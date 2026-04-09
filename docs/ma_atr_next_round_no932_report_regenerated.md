# MA+ATR 下一轮测试报告（修正版）

**生成时间**: 2026-03-30 16:48:09

## 一、口径说明

- 本报告中的“年化收益”使用 `annualized_return`
- 本报告中的“年化超额收益”使用 `annualized_excess_return`
- 本报告中的 turnover_rate 为累计换手率
- 本报告中的 annualized_turnover_rate 为年化换手率（累计换手 / 投资年数）
- turnover_cap 门槛用于判断 eligible，使用 annualized_turnover_rate
- turnover_gap = annualized_turnover_rate - turnover_cap
- 报告生成时不再混用收益口径

## 二、执行结果

## Template A 样本内

- 数据源: `output/ma_atr_next_round_no932/a_is/summary/ma_atr_stage4_best_20260330_144859.csv`

| symbol    | annualized_return   | annualized_excess_return   | max_drawdown   |   trade_count | turnover_rate   |   whipsaw_rate | eligible   |   objective_score |
|:----------|:--------------------|:---------------------------|:---------------|--------------:|:----------------|---------------:|:-----------|------------------:|
| 000001.SH | 10.04%              | 4.47%                      | -11.40%        |            41 | 41.13%          |         0.0667 | ❌         |                -1 |
| 399001.SZ | 8.07%               | 2.03%                      | -12.32%        |            76 | 47.38%          |         0.2857 | ❌         |                -1 |
| 000016.SH | 9.29%               | -0.68%                     | -11.87%        |            19 | 13.01%          |         0.25   | ❌         |                -1 |
| 000300.SH | 11.68%              | 1.79%                      | -16.47%        |            54 | 52.64%          |         0.1905 | ❌         |                -1 |
| 000905.SH | 10.87%              | 2.59%                      | -10.45%        |            56 | 49.20%          |         0.2857 | ❌         |                -1 |

- 平均年化收益: 9.99%
- 平均年化超额收益: 2.04%
- 平均最大回撤: -12.50%
- 平均交易次数: 49.20
- 平均换手率(累计): 40.67%
- 平均换手率(年化): 4.52%
- turnover_cap: 8.0%
- turnover_gap: -3.48% (年化换手 - turnover_cap)
- 平均 whipsaw_rate: 0.2157
- Eligible: 0/5

## Template B 样本内

- 数据源: `output/ma_atr_next_round_no932/b_is/summary/ma_atr_stage4_best_20260330_144955.csv`

| symbol    | annualized_return   | annualized_excess_return   | max_drawdown   |   trade_count | turnover_rate   |   whipsaw_rate | eligible   |   objective_score |
|:----------|:--------------------|:---------------------------|:---------------|--------------:|:----------------|---------------:|:-----------|------------------:|
| 399006.SZ | 15.53%              | -2.42%                     | -24.73%        |            24 | 20.77%          |         0.1111 | ❌         |                -1 |
| 000852.SH | 13.95%              | 5.78%                      | -27.32%        |            19 | 19.09%          |         0.1429 | ❌         |                -1 |

- 平均年化收益: 14.74%
- 平均年化超额收益: 1.68%
- 平均最大回撤: -26.03%
- 平均交易次数: 21.50
- 平均换手率(累计): 19.93%
- 平均换手率(年化): 2.22%
- turnover_cap: 8.0%
- turnover_gap: -5.78% (年化换手 - turnover_cap)
- 平均 whipsaw_rate: 0.1270
- Eligible: 0/2

## Template A 样本外

- 数据源: `output/ma_atr_next_round_no932/a_oos/summary/ma_atr_stage4_best_20260330_145210.csv`

| symbol    | annualized_return   | annualized_excess_return   | max_drawdown   |   trade_count | turnover_rate   |   whipsaw_rate | eligible   |   objective_score |
|:----------|:--------------------|:---------------------------|:---------------|--------------:|:----------------|---------------:|:-----------|------------------:|
| 000001.SH | 3.00%               | 0.37%                      | -5.22%         |             6 | 3.17%           |          0     | ✅         |            0.5104 |
| 399001.SZ | 3.00%               | 4.89%                      | -4.93%         |            19 | 9.42%           |          0.375 | ✅         |            0.5208 |
| 000016.SH | 1.97%               | 5.72%                      | -4.24%         |             4 | 2.10%           |          0     | ✅         |            0.5104 |
| 000300.SH | 1.08%               | 3.72%                      | -5.65%         |             8 | 3.91%           |          0     | ✅         |            0.5104 |
| 000905.SH | 3.19%               | 0.21%                      | -8.17%         |            12 | 6.17%           |          0.25  | ✅         |            0.5104 |

- 平均年化收益: 2.45%
- 平均年化超额收益: 2.98%
- 平均最大回撤: -5.64%
- 平均交易次数: 9.80
- 平均换手率(累计): 4.95%
- 平均换手率(年化): 0.99%
- turnover_cap: 8.0%
- turnover_gap: -7.01% (年化换手 - turnover_cap)
- 平均 whipsaw_rate: 0.1250
- Eligible: 5/5

## Template B 样本外

- 数据源: `output/ma_atr_next_round_no932/b_oos/summary/ma_atr_stage4_best_20260330_145259.csv`

| symbol    | annualized_return   | annualized_excess_return   | max_drawdown   |   trade_count | turnover_rate   |   whipsaw_rate | eligible   |   objective_score |
|:----------|:--------------------|:---------------------------|:---------------|--------------:|:----------------|---------------:|:-----------|------------------:|
| 399006.SZ | 4.87%               | 4.03%                      | -9.97%         |            10 | 4.95%           |         0      | ✅         |            0.5104 |
| 000852.SH | 3.88%               | 1.55%                      | -9.03%         |            18 | 9.15%           |         0.2857 | ✅         |            0.5104 |

- 平均年化收益: 4.37%
- 平均年化超额收益: 2.79%
- 平均最大回撤: -9.50%
- 平均交易次数: 14.00
- 平均换手率(累计): 7.05%
- 平均换手率(年化): 1.41%
- turnover_cap: 8.0%
- turnover_gap: -6.59% (年化换手 - turnover_cap)
- 平均 whipsaw_rate: 0.1429
- Eligible: 2/2

## 全量 7 指数复核

- 数据源: `output/ma_atr_next_round_no932/full/summary/ma_atr_stage4_best_20260330_145709.csv`

| symbol    | annualized_return   | annualized_excess_return   | max_drawdown   |   trade_count | turnover_rate   |   whipsaw_rate | eligible   |   objective_score |
|:----------|:--------------------|:---------------------------|:---------------|--------------:|:----------------|---------------:|:-----------|------------------:|
| 000001.SH | 5.96%               | 1.38%                      | -23.63%        |            60 | 51.24%          |         0.2083 | ❌         |                -1 |
| 399001.SZ | 5.56%               | 2.23%                      | -28.64%        |            41 | 36.97%          |         0.1176 | ❌         |                -1 |
| 399006.SZ | 10.18%              | -1.67%                     | -19.35%        |           126 | 126.07%         |         0.48   | ❌         |                -1 |
| 000016.SH | 6.02%               | 1.15%                      | -11.87%        |            21 | 18.05%          |         0      | ❌         |                -1 |
| 000300.SH | 7.86%               | 2.54%                      | -16.47%        |            80 | 88.22%          |         0.2667 | ❌         |                -1 |
| 000905.SH | 8.81%               | 2.31%                      | -14.00%        |            88 | 87.89%          |         0.1935 | ❌         |                -1 |
| 000852.SH | 9.90%               | 3.67%                      | -27.46%        |            36 | 44.97%          |         0.1429 | ❌         |                -1 |

- 平均年化收益: 7.76%
- 平均年化超额收益: 1.66%
- 平均最大回撤: -20.20%
- 平均交易次数: 64.57
- 平均换手率(累计): 64.77%
- 平均换手率(年化): 4.63%
- turnover_cap: 8.0%
- turnover_gap: -3.37% (年化换手 - turnover_cap)
- 平均 whipsaw_rate: 0.2013
- Eligible: 0/7

## 三、关键结论

- Template A 样本外平均年化超额收益: 2.98%
- Template A 样本外平均年化换手率: 0.99%
- Template B 样本外平均年化超额收益: 2.79%
- Template B 样本外平均年化换手率: 1.41%
- 全量平均年化超额收益: 1.66%
- 全量平均最大回撤: -20.20%
- 全量平均年化换手率: 4.63%
- turnover_cap: 8.0%
- 全量 turnover_gap: -3.37%
