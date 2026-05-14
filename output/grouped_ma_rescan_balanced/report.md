# balanced MA rescan report

- 覆盖指数: 399001.SZ, 000905.SH
- 目标通过线: 至少 1/2 eligible
- 约束: excess>0, max_drawdown>-35%, trade_count>=3, turnover<8.0, whipsaw<=0.35
- 说明: 优先寻找 annualized_excess_return > 0，且回撤不超过 -35% 的 MA 主组合。

## Top Candidates

- MA10/120 ATR14/40 buy=1.00 sell=1.05 vol_scale=on tv=0.15 eligible_count=1/2 avg_excess=1.88% avg_dd=-24.00% score=0.823
- MA10/120 ATR14/40 buy=1.05 sell=1.05 vol_scale=on tv=0.15 eligible_count=1/2 avg_excess=1.39% avg_dd=-24.05% score=0.821
- MA10/120 ATR14/40 buy=1.05 sell=1.05 vol_scale=on tv=0.18 eligible_count=1/2 avg_excess=1.68% avg_dd=-27.12% score=0.811
- MA10/120 ATR14/40 buy=1.00 sell=1.05 vol_scale=on tv=0.18 eligible_count=1/2 avg_excess=2.28% avg_dd=-27.08% score=0.804
- MA10/120 ATR14/20 buy=1.00 sell=1.15 vol_scale=off tv=0.15 eligible_count=1/2 avg_excess=2.00% avg_dd=-36.88% score=0.740
- MA10/120 ATR14/20 buy=1.05 sell=1.15 vol_scale=off tv=0.15 eligible_count=1/2 avg_excess=2.00% avg_dd=-36.88% score=0.740
- MA20/120 ATR14/40 buy=1.05 sell=1.10 vol_scale=on tv=0.15 eligible_count=1/2 avg_excess=-0.54% avg_dd=-37.07% score=0.685
- MA20/120 ATR14/40 buy=1.05 sell=1.05 vol_scale=on tv=0.15 eligible_count=1/2 avg_excess=-0.84% avg_dd=-37.07% score=0.658
- MA10/120 ATR14/60 buy=1.00 sell=1.10 vol_scale=off tv=0.15 eligible_count=1/2 avg_excess=-0.24% avg_dd=-42.65% score=0.627
- MA10/120 ATR14/60 buy=1.00 sell=1.15 vol_scale=off tv=0.15 eligible_count=1/2 avg_excess=-0.24% avg_dd=-42.65% score=0.627
