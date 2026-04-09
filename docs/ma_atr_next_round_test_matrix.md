# MA + ATR 下一轮测试矩阵

日期：2026-03-30

本文档面向第一次接触本项目的人。目标是把上一轮报告里的结论，整理成一份可以直接执行的下一轮测试调优方案。

这份方案不是继续扩大网格，而是做三件事：

- 把大盘/宽基和高波动指数分开测
- 把样本内和样本外分开验
- 把“交易频率抑制”从 `confirm_days / cooldown_days` 前移到信号层

如果你只记住一句话：

> Template A 先保住收益和回撤，Template B 先压掉噪声交易，所有结论必须经过 OOS 验证。

## 1. 这轮为什么要换方案

上一轮全量结果已经说明，继续单独调 `confirm_days`、`cooldown_days`、`min_hold_bars`，边际收益很低。

最新报告里的关键结论是：

- Stage 4 和 Stage 3 已经收敛到同一组参数，说明交易后抑制已经平台化
- `turnover_cap` 仍然把大量结果硬拒绝，门槛本身的解释力不够
- Template A 明显优于 Template B
- Template B 的主要问题是换手高、whipsaw 高、信号噪声重
- 报告强烈建议加入样本内 / 样本外切分和参数平台检查

因此，下一轮不应该继续做“全局一锅扫”，而应该改成：

1. 先在样本内找候选
2. 再用样本外验证稳定性
3. 最后只做邻域微调

## 2. 先看基线

### 2.1 当前全量参考基线

下面这些结果来自上一轮全量汇总，作为本轮对照：

- 全量策略基线：`round6 / full_test`
  - 平均年化超额收益：`+1.3408%`
  - 平均最大回撤：`-19.3237%`
  - 平均交易次数：`64.875`
  - 平均换手率：`65.5281`
  - 平均 whipsaw_rate：`0.2224`

### 2.2 两套模板当前状态

上一轮全量模板测试的 Stage 4 平均值：

- Template A
  - 平均年化超额收益：`+1.92%`
  - 平均最大回撤：`-18.88%`
  - 平均交易次数：`58`
  - 平均换手率：`56.47%`
  - 平均 whipsaw_rate：`15.72%`

- Template B
  - 平均年化超额收益：`+0.37%`
  - 平均最大回撤：`-19.99%`
  - 平均交易次数：`76`
  - 平均换手率：`80.62%`
  - 平均 whipsaw_rate：`33.11%`

这意味着：

- Template A 已经比全局基线更像一个可用模板
- Template B 还不够稳，必须优先压噪声和频次

## 3. 新的测试原则

### 3.1 不再把 `turnover_cap` 当主裁判

`turnover_cap` 还可以保留为告警项，但不要继续把它当成唯一硬拒绝条件。

更合理的做法是：

- 在回测收益里直接加入交易摩擦
- 用净收益排名高换手方案
- 用 `turnover_rate` 做风险标签，不做一刀切淘汰

### 3.2 强制做 OOS

每次参数选择都必须按时间切分：

- `2012-01-01` 到 `2020-12-31`：样本内，用来找候选
- `2021-01-01` 到 `2025-12-31`：样本外，用来验证

如果某组参数只在全量里好看，但 OOS 崩掉，直接淘汰。

### 3.3 先测信号，再测节奏

上一轮已经说明：

- `confirm_days`
- `cooldown_days`
- `min_hold_bars`

这三个参数已经接近平台期。

下一轮应优先测试：

- `atr_deadband`
- `atr_confirm_enabled`
- `slope_threshold`

原因很直接：

- 它们更接近信号质量
- 它们能直接减少假金叉、假死叉
- 它们比单纯延长冷却期更有机会压住换手

### 3.4 这轮测试前必须先补的代码位

当前脚本的固定网格还没把下面这些参数完全放开，所以在正式执行前，先确认代码已经支持它们：

- `src/investment/backtest.py`
  - `atr_deadband`
  - `atr_confirm_enabled`
  - `slope_threshold`
  - 确认交易佣金和滑点仍然启用，建议双边综合摩擦至少落在 `0.001` 到 `0.0015` 的量级
- `scripts/tune_ma_atr_only.py`
  - 把 Template A / B 的种子组合改成本文件定义的矩阵
  - 增加 `2012-2020` 与 `2021-2025` 两段跑法
- `src/investment/tuning.py`
  - 把 `turnover_cap` 从硬拒绝主规则里降级为告警项，或者至少保留净收益排序

## 4. 模板定义

### 4.1 Template A

适用对象：

- `000001.SH`
- `399001.SZ`
- `000016.SH`
- `000300.SH`
- `000905.SH`

特点：

- 趋势更长
- 节奏更慢
- 可以接受更长均线和更重的风控

### 4.2 Template B

适用对象：

- `399006.SZ`
- `000852.SH`
- `932000.SH`

特点：

- 波动更大
- 假突破更多
- 必须更强地压噪声和止盈回吐

## 5. 下一轮测试矩阵

这一轮只测“有意义的组合”，不要再做全量笛卡尔积。

### 5.1 Stage 0: 代码预检

先确认这些功能都还正常：

- 金叉买入
- 死叉卖出
- ATR 低波动确认
- ATR 持续放大卖出
- 趋势过滤
- 回撤停机
- 冷却期
- 最小持有期

建议命令：

```bash
.venv/bin/python -m unittest tests.unit.test_investment_backtest
```

### 5.2 Stage 1: 样本内寻优

先只跑 `2012-01-01` 到 `2020-12-31`。

本阶段默认把 `atr_confirm_enabled=true` 固定开启，不再单独扫开关值。

#### 5.2.1 Template A 样本内种子

优先测试以下 4 组：

| 组别 | fast / slow | atr_period / atr_ma_window | buy_volatility_cap | vol_breakout_mult | atr_deadband | slope_threshold | regime_filter_ma | regime_filter_buffer | risk_drawdown_stop_threshold | risk_drawdown_lookback | confirm_days | cooldown_days | min_hold_bars |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | `10 / 120` | `14 / 40` | `1.03` | `1.03` | `0.02` | `0.00` | `180` | `0.98` | `0.15` | `240` | `2` | `8` | `5` |
| A2 | `20 / 120` | `14 / 60` | `1.03` | `1.05` | `0.03` | `0.01` | `240` | `1.00` | `0.20` | `240` | `2` | `8` | `5` |
| A3 | `30 / 120` | `20 / 60` | `1.00` | `1.03` | `0.03` | `0.01` | `240` | `1.00` | `0.20` | `240` | `2` | `10` | `5` |
| A4 | `10 / 60` | `14 / 40` | `1.03` | `1.05` | `0.02` | `0.01` | `180` | `0.98` | `0.15` | `180` | `2` | `8` | `5` |

#### 5.2.2 Template B 样本内种子

优先测试以下 4 组：

Template B 同样固定 `atr_confirm_enabled=true`。

| 组别 | fast / slow | atr_period / atr_ma_window | buy_volatility_cap | vol_breakout_mult | atr_deadband | slope_threshold | regime_filter_ma | regime_filter_buffer | risk_drawdown_stop_threshold | risk_drawdown_lookback | confirm_days | cooldown_days | min_hold_bars |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B1 | `10 / 60` | `10 / 40` | `1.00` | `1.05` | `0.05` | `0.01` | `120` | `0.98` | `0.15` | `180` | `2` | `8` | `5` |
| B2 | `10 / 120` | `14 / 40` | `1.00` | `1.05` | `0.08` | `0.02` | `180` | `0.98` | `0.18` | `180` | `2` | `8` | `5` |
| B3 | `20 / 120` | `14 / 40` | `1.03` | `1.05` | `0.08` | `0.02` | `180` | `0.98` | `0.18` | `240` | `2` | `10` | `5` |
| B4 | `20 / 60` | `10 / 40` | `1.00` | `1.05` | `0.05` | `0.01` | `120` | `0.98` | `0.15` | `180` | `2` | `8` | `5` |

### 5.3 Stage 2: 样本外验证

把 Stage 1 里每个模板排名前 2 到 3 组的参数，直接拿去跑 `2021-01-01` 到 `2025-12-31`。

注意：

- 这里的 OOS 不是重新扫一遍网格
- OOS 必须固定使用 Stage 1 选出来的具体参数组
- 如果脚本不支持直接传参，就先把 Top 参数写入一个单独的 `yaml` 或 `json`，再做单次回测

建议优先复用仓库里支持固定参数回测的入口，例如 `src/cli/index_investment_analysis.py`；如果你要复用当前项目里的参数配置能力，先把 Stage 1 的胜出参数整理成一个可读取的配置文件，再运行样本外盲测。下面的 `config/optimal_params.yaml` 只是路径占位，实际执行时应替换为你导出的样本内胜出参数文件。

示例命令模板：

```bash
.venv/bin/python src/cli/index_investment_analysis.py \
  --symbol 000300.SH \
  --start-date 2021-01-01 \
  --end-date 2025-12-31 \
  --use-optimal-config \
  --optimal-config-path <stage1_top_params.yaml> \
  --output output/ma_atr_next_round_a_oos
```

样本内仍然可以继续用调优脚本生成候选：

```bash
.venv/bin/python scripts/tune_ma_atr_only.py \
  --start-date 2012-01-01 \
  --end-date 2020-12-31 \
  --output output/ma_atr_next_round_a_is
```

Template B 的样本外单次回测同理，只替换参数配置或输出目录即可：

```bash
.venv/bin/python src/cli/index_investment_analysis.py \
  --symbol 399006.SZ \
  --start-date 2021-01-01 \
  --end-date 2025-12-31 \
  --use-optimal-config \
  --optimal-config-path <stage1_top_params.yaml> \
  --output output/ma_atr_next_round_b_oos
```

样本外只看三件事：

- 年化超额收益是否还能保持正值
- 最大回撤是否没有明显失控
- 换手和 whipsaw 是否没有明显恶化

不要因为样本内特别好，就直接认定可用。

### 5.4 Stage 3: 邻域鲁棒性检查

对样本外胜出的参数，再做小范围邻域验证，确认不是“参数孤岛”。

#### Template A 邻域

只围绕样本外胜出组做下面这些小扰动：

- `fast_ma` 上下各偏一档
- `slow_ma` 只测试 `120` 和 `240`
- `atr_deadband` 测 `0.02 / 0.03 / 0.05`
- `slope_threshold` 测 `0.00 / 0.01 / 0.02`
- `risk_drawdown_stop_threshold` 测 `0.15 / 0.20`

执行方式：

- 临时把网格生成器缩到上述局部范围
- 不要再保留全局 21 组均线组合
- 每次只保留一个模板的邻域，避免算力浪费

#### Template B 邻域

只围绕样本外胜出组做下面这些小扰动：

- `fast_ma` 只测 `10` 和 `20`
- `slow_ma` 只测 `60` 和 `120`
- `atr_deadband` 测 `0.05 / 0.08`
- `slope_threshold` 测 `0.01 / 0.02`
- `regime_filter_ma` 测 `120 / 180 / 240`

执行方式：

- 仅保留 Template B 胜出参数的局部网格
- 先测 `atr_deadband`，再测 `fast/slow`，最后才动 `regime_filter_ma`
- 如果结果对 `atr_deadband` 极端敏感，直接视为不稳定参数组

### 5.5 Stage 4: 全量复核

最后再把胜出的参数放回 8 个指数全量测试。

全量指数：

- `000001.SH`
- `399001.SZ`
- `399006.SZ`
- `000016.SH`
- `000300.SH`
- `000905.SH`
- `000852.SH`
- `932000.SH`

全量测试的意义只有两个：

- 验证模板分组是否真能泛化
- 验证某个指数是不是应该单独分组

## 6. 怎么判断好坏

### 6.1 Template A 的目标

Template A 的优先级是：

1. 保住正收益
2. 控制回撤
3. 再压换手和 whipsaw

建议达标线：

- OOS 年化超额收益不低于当前 Template A 基线太多
- OOS 最大回撤不要明显差于 `-20%`
- OOS `turnover_rate` 尽量压到 `50%` 附近或以下
- OOS `whipsaw_rate` 尽量低于当前 Template A 基线

### 6.2 Template B 的目标

Template B 的优先级是：

1. 明显压掉噪声交易
2. 把 whipsaw 压下来
3. 再去争取正收益

建议达标线：

- OOS `trade_count` 明显低于当前 Template B 基线
- OOS `turnover_rate` 至少比当前 Template B 基线下降一档
- OOS `whipsaw_rate` 至少比当前 Template B 基线下降一档
- OOS 年化超额收益不能长期维持明显负值

### 6.3 失败判定

以下情况直接判失败：

- 样本内很好，样本外明显崩掉
- 换手下降了，但收益直接转负且回撤没有改善
- 只在单个指数上成立，其他指数全失效
- 最优参数点在邻域里一点鲁棒性都没有

## 7. 推荐执行顺序

按下面顺序跑，最省时间：

1. 单测
2. 样本内 Template A
3. 样本内 Template B
4. 样本外复跑前 2 到 3 组
5. 邻域鲁棒性检查
6. 全量 8 指数复核

如果时间有限，优先级是：

1. Template A 的样本外验证
2. Template B 的样本外验证
3. 全量复核

因为当前结果已经说明：

- Template A 更接近可用模板
- Template B 仍然需要重做信号过滤

## 8. 输出目录建议

建议新一轮按下面目录保存：

- `output/ma_atr_next_round_a_is`
- `output/ma_atr_next_round_b_is`
- `output/ma_atr_next_round_a_oos`
- `output/ma_atr_next_round_b_oos`
- `output/ma_atr_next_round_full`

每次都保留：

- `summary/`
- `reports/`
- `plots/`

这样后续复盘会很清楚。

## 9. 对新人最重要的提醒

1. 不要只看全量最优，先看样本外。
2. 不要只看收益，必须一起看回撤和换手。
3. 不要把 `turnover_cap` 当成唯一结论来源。
4. Template A 和 Template B 不要共用一套参数。
5. 如果某组参数只在某个指数上成立，先别急着推广。

## 10. 最终建议

下一轮最有效的方向不是“继续扩大网格”，而是：

- 用 `atr_deadband` 和 `slope_threshold` 先压掉假信号
- 用 `atr_confirm_enabled` 进一步确认高波动突破
- 用 OOS 检验模板是否真的成立
- 用邻域鲁棒性确认参数不是孤岛

如果这一轮跑完后，Template A 在 OOS 里还能保住正收益并继续压低换手，那它就可以作为主模板继续推进。
