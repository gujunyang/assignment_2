# STAT6207 作业二 — 序列识别（Sequence Recognition）

基于过去 10 分钟时间步，对家庭用电量 `Appliances`（Wh）做**单步预测**。使用
**LSTM**（Basic）与 **Transformer**（Advanced），全程由 OpenCode 辅助构建。
项目包含 EDA、naive 基线、Transformer 对比，以及一个可泛化到**不同时间段**的预测管线。

> 进度与待办详见 **[`docs/PROGRESS.md`](docs/PROGRESS.md)**；
> 续接作业请先看 **[`docs/HANDOFF.md`](docs/HANDOFF.md)**（含下一步 prompt 原文与网络备忘）。

## 任务定义

- **目标变量**：`Appliances`（Wh），采样间隔 10 分钟。
- **形式**：单步预测（one-step-ahead）。输入 = 过去 `L=24` 个时间步（4 小时），标签 = `t+1` 时刻的 `Appliances`。
- **切分（按时间、不 shuffle）**：前 800 行为训练段，后 200 行为测试段；训练段末尾 160 行作为**验证集**用于早停：
  - 子训练集：行 0–639（2016-01-11 17:00 → 2016-01-16 03:30）
  - 验证集：行 640–799（2016-01-16 03:40 → 2016-01-17 06:10）
  - 测试集：行 800–999（2016-01-17 06:20 → 2016-01-18 15:30）
- **归一化**：`StandardScaler` 只在子训练集上 `fit`，再 `transform` 验证/测试集。
- **指标**：均在原始（反归一化）Wh 尺度上计算。
- **基线**：naive persistence（直接沿用当前值）。

## 目录结构

```
assignment_2/
├── README.md
├── AGENTS.md                     # OpenCode 项目指令
├── data/
│   ├── A2_data_release.csv       # 发布的原始数据集（1000 行）
│   ├── A2_periodB.csv            # 不同时间段（与发布周无重叠，01-18 → 01-29）
│   └── uci_appliances_jan2016.csv# UCI 源文件抽取（01-11 → 01-29，部分下载）
├── docs/
│   ├── 2026_6207_Lecture_L4_v3.pdf
│   ├── EDA_report.md             # 探索性分析报告
│   ├── bug_log.md                # OpenCode 错误与修复（报告素材）
│   └── PROGRESS.md               # 作业进度记录
├── src/
│   ├── data_pipeline.py          # 切分 + 归一化 + 滑窗（写入 artifacts/）
│   ├── train_lstm.py             # LSTM v1（刻意保留的过拟合反例）
│   ├── train_lstm_v2.py          # LSTM v2（验证集 + 早停）← 主结果
│   ├── transformer_forecast.py   # Transformer 编码器，同协议
│   └── run_forecast.py           # 可泛化管线（任意时间段）
├── artifacts/
│   ├── data_windows.npz          # 生成的 X/y 窗口
│   └── scaler.pkl                # 生成的 scaler
└── results/
    ├── eda/eda_appliances.png
    ├── lstm_v1_broken/           # 修复前（metrics.json、png、模型）
    ├── lstm_v2/                  # 修复后的 LSTM（metrics_v2.json、png）
    ├── transformer/              # Transformer（metrics_transformer.json、png）
    └── forecast/                 # 泛化管线输出（多时间段）
```

所有脚本都基于项目根目录解析路径，可从任意位置运行。

## 运行方式

```bash
python src/data_pipeline.py          # -> artifacts/data_windows.npz, scaler.pkl
python src/train_lstm.py             # -> results/lstm_v1_broken/   （过拟合反例）
python src/train_lstm_v2.py          # -> results/lstm_v2/         （修复后的 LSTM）
python src/transformer_forecast.py   # -> results/transformer/     （需先跑 lstm_v2）
python src/run_forecast.py --csv data/A2_periodB.csv --model lstm --tag periodB_lstm
```

## 结果（测试集，原始 Wh 尺度）

| 模型 | MSE | MAE | RMSE |
|---|---:|---:|---:|
| Naive persistence（基线） | 7500.0 | 33.3 | **86.6** |
| LSTM v1（无验证/无早停） | 79745.3 | 225.4 | **282.4** ❌ |
| LSTM v2（单变量 + 早停） | 6208.4 | 36.0 | **78.8** |
| Transformer（单变量） | 6165.5 | 40.6 | **78.5** |
| LSTM（全部 28 特征） | 24821.6 | 113.9 | 157.5 |
| Transformer（全部 28 特征） | 11869.8 | 79.7 | 108.9 |

主要发现：

1. 没有验证集/早停时，LSTM **严重过拟合**，最终**比 naive 基线还差**（RMSE 282 vs 87）。加入按时间的验证集与早停后修复。
2. 单变量输入下，LSTM 与 Transformer 都**击败 naive**，且两者几乎打平（78.5 vs 78.8）。
3. 喂入全部 28 个特征（含无信息的 `rv1`/`rv2`）反而拖累两个模型；**目标自身的历史是最有效的信号**。

相关 OpenCode 错误与修复见 [`docs/bug_log.md`](docs/bug_log.md)。

## 可泛化管线（`src/run_forecast.py`）

参数化命令行工具，**无需改代码即可对任意时间段运行**：
`--csv --target --window --test-ratio --model {lstm,transformer} --start --end --tag`。
自动解析日期、推断采样间隔、修复缺失值（前向填充 + 线性插值）、按时间切分、
只在训练部分拟合 scaler，并用验证集早停。

```bash
python src/run_forecast.py --csv data/A2_periodB.csv --model lstm        --tag periodB_lstm
python src/run_forecast.py --csv data/A2_periodB.csv --model transformer --tag periodB_trans
```

| 时间段 | 模型 | RMSE | Naive RMSE |
|---|---|---:|---:|
| 发布周 | LSTM（全特征） | 157.6 | 86.6 |
| 发布周 | Transformer（全特征） | 109.0 | 86.6 |
| periodB（01-27→29） | LSTM（全特征） | 17.5 | 11.0 |
| periodB（01-27→29） | Transformer（全特征） | 16.2 | 11.0 |

管线可成功迁移到不同时间段，但**全特征**模型仍不敌 naive 基线——与上述"特征选择更重要"的结论一致。详见 `docs/bug_log.md` #6。

## 时间序列正确性规则（本项目强制遵守）

1. 按时间切分，绝不 shuffle。
2. scaler 只在训练集上拟合。
3. 无 look-ahead：在 `t` 结束的窗口只预测 `t+1`。
4. 窗口不跨越训练/测试边界。
5. 指标在原始尺度上计算。
6. 始终与 naive persistence 基线对比。
7. 固定随机种子（42）。

## 进度

- [x] EDA + 报告
- [x] 数据处理管线（时间切分 + 归一化 + 滑窗）
- [x] LSTM（修复版）+ naive 基线
- [x] Transformer 对比
- [x] 可泛化管线（不同时间段）
- [ ] local LLM 对比（受阻：本网络无法下载 Ollama）
- [ ] 报告 PDF、session transcripts、prompt 归档

完整进度见 [`docs/PROGRESS.md`](docs/PROGRESS.md)。
