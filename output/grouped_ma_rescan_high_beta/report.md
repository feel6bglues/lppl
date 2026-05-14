# high_beta MA rescan report

- 覆盖指数: 399006.SZ, 000852.SH, 932000.SH
- 目标通过线: 至少 1/3 eligible
- 约束: excess>0, max_drawdown>-40%, trade_count>=3, turnover<8.0, whipsaw<=0.35
- 说明: 优先寻找正超额；若仍无法转正，则保留回撤明显收敛且交易次数恢复到 >= 3 的组合。

## Top Candidates

- MA20/120 ATR20/20 buy=1.00 sell=1.05 vol_scale=on tv=0.20 eligible_count=1/3 avg_excess=-1.70% avg_dd=-28.17% score=0.735
- MA20/120 ATR20/20 buy=1.00 sell=1.05 vol_scale=on tv=0.18 eligible_count=1/3 avg_excess=-2.29% avg_dd=-26.36% score=0.692
- MA20/120 ATR20/20 buy=1.00 sell=1.10 vol_scale=on tv=0.20 eligible_count=1/3 avg_excess=-4.49% avg_dd=-39.48% score=0.587
- MA20/120 ATR20/20 buy=1.00 sell=1.10 vol_scale=on tv=0.18 eligible_count=1/3 avg_excess=-5.06% avg_dd=-38.26% score=0.544
- MA30/250 ATR20/20 buy=1.00 sell=1.15 vol_scale=on tv=0.18 eligible_count=0/3 avg_excess=-6.21% avg_dd=-25.82% score=0.738
- MA30/250 ATR20/20 buy=1.00 sell=1.15 vol_scale=on tv=0.20 eligible_count=0/3 avg_excess=-6.21% avg_dd=-25.82% score=0.738
- MA30/250 ATR20/40 buy=1.00 sell=1.10 vol_scale=on tv=0.18 eligible_count=0/3 avg_excess=-6.21% avg_dd=-25.82% score=0.738
- MA30/250 ATR20/40 buy=1.00 sell=1.10 vol_scale=on tv=0.20 eligible_count=0/3 avg_excess=-6.21% avg_dd=-25.82% score=0.738
- MA30/250 ATR20/40 buy=1.00 sell=1.15 vol_scale=on tv=0.18 eligible_count=0/3 avg_excess=-6.21% avg_dd=-25.82% score=0.738
- MA30/250 ATR20/40 buy=1.00 sell=1.15 vol_scale=on tv=0.20 eligible_count=0/3 avg_excess=-6.21% avg_dd=-25.82% score=0.738
