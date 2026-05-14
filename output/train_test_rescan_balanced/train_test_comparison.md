# balanced Train/Test Comparison Report

- 训练集: 2012-01-01 ~ 2019-12-31
- 测试集: 2020-01-01 ~ 2026-01-01

## Train Set Top 5

- ma=10/250|atr=14/40|buy=1.00|sell=1.10|vol_on|tv=0.18 eligible=0/2 excess=-0.30% dd=-46.75% trades=10.5 score=-0.010
- ma=10/250|atr=14/40|buy=1.00|sell=1.15|vol_on|tv=0.18 eligible=0/2 excess=-0.30% dd=-46.75% trades=10.5 score=-0.010
- ma=10/250|atr=14/60|buy=1.00|sell=1.05|vol_on|tv=0.18 eligible=0/2 excess=-0.39% dd=-46.75% trades=12.0 score=-0.010
- ma=10/250|atr=14/60|buy=1.05|sell=1.05|vol_on|tv=0.18 eligible=0/2 excess=-0.39% dd=-46.75% trades=12.0 score=-0.010
- ma=10/250|atr=14/40|buy=1.00|sell=1.10|vol_off|tv=0.15 eligible=0/2 excess=-0.44% dd=-50.19% trades=6.5 score=-0.010

## Test Set Results

- ma=10/250|atr=14/40|buy=1.00|sell=1.10|vol_off|tv=0.15 eligible=0/2 excess=-5.44% dd=-27.52% trades=4.0
- ma=10/250|atr=14/40|buy=1.00|sell=1.10|vol_on|tv=0.18 eligible=0/2 excess=-6.28% dd=-25.36% trades=4.0
- ma=10/250|atr=14/40|buy=1.00|sell=1.15|vol_on|tv=0.18 eligible=0/2 excess=-7.64% dd=-30.07% trades=3.0
- ma=10/250|atr=14/60|buy=1.00|sell=1.05|vol_on|tv=0.18 eligible=0/2 excess=-6.28% dd=-25.36% trades=4.0
- ma=10/250|atr=14/60|buy=1.05|sell=1.05|vol_on|tv=0.18 eligible=0/2 excess=-6.28% dd=-25.36% trades=4.0

## Overfitting Check

- ma=10/250|atr=14/40|buy=1.00|sell=1.10|vol_on|tv=0.18: train=-0.30%, test=-6.28%, diff=-5.98% [OVERFIT]
- ma=10/250|atr=14/40|buy=1.00|sell=1.15|vol_on|tv=0.18: train=-0.30%, test=-7.64%, diff=-7.34% [OVERFIT]
- ma=10/250|atr=14/60|buy=1.00|sell=1.05|vol_on|tv=0.18: train=-0.39%, test=-6.28%, diff=-5.89% [OVERFIT]
