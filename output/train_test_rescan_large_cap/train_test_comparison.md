# large_cap Train/Test Comparison Report

- 训练集: 2012-01-01 ~ 2019-12-31
- 测试集: 2020-01-01 ~ 2026-01-01

## Train Set Top 5

- ma=20/120|atr=14/40|buy=1.05|sell=1.15|vol_on|tv=0.12 eligible=1/3 excess=-0.11% dd=-33.68% trades=11.7 score=0.866
- ma=20/120|atr=14/40|buy=1.05|sell=1.15|vol_on|tv=0.15 eligible=1/3 excess=0.00% dd=-36.61% trades=10.7 score=0.819
- ma=20/120|atr=14/40|buy=1.05|sell=1.05|vol_on|tv=0.12 eligible=0/3 excess=-0.38% dd=-29.94% trades=13.3 score=-0.010
- ma=20/120|atr=14/40|buy=1.05|sell=1.05|vol_on|tv=0.15 eligible=0/3 excess=-0.38% dd=-32.78% trades=12.3 score=-0.010
- ma=20/120|atr=14/20|buy=1.05|sell=1.15|vol_on|tv=0.12 eligible=0/3 excess=-0.74% dd=-34.51% trades=10.3 score=-0.010

## Test Set Results

- ma=20/120|atr=14/20|buy=1.05|sell=1.15|vol_on|tv=0.12 eligible=1/3 excess=0.45% dd=-33.59% trades=9.0
- ma=20/120|atr=14/40|buy=1.05|sell=1.05|vol_on|tv=0.12 eligible=2/3 excess=1.70% dd=-29.65% trades=9.7
- ma=20/120|atr=14/40|buy=1.05|sell=1.05|vol_on|tv=0.15 eligible=1/3 excess=1.77% dd=-33.16% trades=8.3
- ma=20/120|atr=14/40|buy=1.05|sell=1.15|vol_on|tv=0.12 eligible=0/3 excess=0.69% dd=-33.69% trades=8.7
- ma=20/120|atr=14/40|buy=1.05|sell=1.15|vol_on|tv=0.15 eligible=0/3 excess=0.60% dd=-37.38% trades=7.3

## Overfitting Check

- ma=20/120|atr=14/40|buy=1.05|sell=1.15|vol_on|tv=0.12: train=-0.11%, test=0.69%, diff=+0.80% [ROBUST]
- ma=20/120|atr=14/40|buy=1.05|sell=1.15|vol_on|tv=0.15: train=0.00%, test=0.60%, diff=+0.60% [ROBUST]
- ma=20/120|atr=14/40|buy=1.05|sell=1.05|vol_on|tv=0.12: train=-0.38%, test=1.70%, diff=+2.07% [ROBUST]
