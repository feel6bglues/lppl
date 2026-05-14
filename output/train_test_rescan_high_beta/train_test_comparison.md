# high_beta Train/Test Comparison Report

- 训练集: 2012-01-01 ~ 2019-12-31
- 测试集: 2020-01-01 ~ 2026-01-01

## Train Set Top 5

- ma=20/120|atr=20/20|buy=1.05|sell=1.05|vol_on|tv=0.20 eligible=0/3 excess=-4.57% dd=-47.26% trades=11.0 score=-0.010
- ma=10/120|atr=20/60|buy=1.05|sell=1.05|vol_on|tv=0.20 eligible=0/3 excess=-4.66% dd=-47.26% trades=15.0 score=-0.010
- ma=10/120|atr=20/60|buy=1.05|sell=1.10|vol_on|tv=0.20 eligible=0/3 excess=-4.66% dd=-47.26% trades=15.0 score=-0.010
- ma=10/120|atr=20/60|buy=1.05|sell=1.15|vol_on|tv=0.20 eligible=0/3 excess=-4.66% dd=-47.26% trades=15.0 score=-0.010
- ma=5/120|atr=20/40|buy=1.05|sell=1.10|vol_on|tv=0.20 eligible=0/3 excess=-4.72% dd=-48.00% trades=17.7 score=-0.010

## Test Set Results

- ma=10/120|atr=20/60|buy=1.05|sell=1.05|vol_on|tv=0.20 eligible=0/3 excess=-5.28% dd=-41.79% trades=9.0
- ma=10/120|atr=20/60|buy=1.05|sell=1.10|vol_on|tv=0.20 eligible=0/3 excess=-5.69% dd=-48.32% trades=8.3
- ma=10/120|atr=20/60|buy=1.05|sell=1.15|vol_on|tv=0.20 eligible=0/3 excess=-5.17% dd=-48.32% trades=8.0
- ma=20/120|atr=20/20|buy=1.05|sell=1.05|vol_on|tv=0.20 eligible=1/3 excess=-1.76% dd=-30.71% trades=7.7
- ma=5/120|atr=20/40|buy=1.05|sell=1.10|vol_on|tv=0.20 eligible=0/3 excess=-4.93% dd=-41.36% trades=10.7

## Overfitting Check

- ma=20/120|atr=20/20|buy=1.05|sell=1.05|vol_on|tv=0.20: train=-4.57%, test=-1.76%, diff=+2.81% [ROBUST]
- ma=10/120|atr=20/60|buy=1.05|sell=1.05|vol_on|tv=0.20: train=-4.66%, test=-5.28%, diff=-0.63% [ROBUST]
- ma=10/120|atr=20/60|buy=1.05|sell=1.10|vol_on|tv=0.20: train=-4.66%, test=-5.69%, diff=-1.04% [BORDERLINE]
