# AGENTS.md

## 项目

STAT6207 Applied Deep Learning — 作业二：序列识别（Sequence Recognition）。

目标：从过去的时间步预测 `Appliances` 的下一个值（单步预测）。使用 LSTM（Basic）
与 Transformer（Advanced），并包含 local LLM 对比，以及一个可泛化到**不同时间段**的管线。

## 数据

- `data/A2_data_release.csv` — 1000 行，10 分钟采样，2016-01-11 17:00 → 2016-01-18 15:30，29 列，无缺失值。
- 目标列：`Appliances`（Wh）。**不要**把 `date` 当作数值特征。
- `rv1` 与 `rv2` 是两个完全相同的随机列（无信息）。

## 硬性规则（时间序列正确性）

1. **按时间切分，绝不 shuffle。** 较早的数据作训练，较晚的数据作测试。
2. **scaler 只在训练集上 fit**，再 transform 测试集。绝不在全量数据上 fit（数据泄漏）。
3. **无 look-ahead。** 在时间 `t` 结束的窗口只预测 `t+1`。
4. 窗口不得跨越训练/测试切分边界。
5. 指标要在**原始（反归一化）尺度**上报告。
6. **始终与 naive persistence 基线对比**（用当前值预测下一值）。
7. 固定随机种子以保证可复现。

## 项目结构

- `data/` — 原始数据集。
- `docs/` — 课件 PDF、EDA 报告、`bug_log.md`、`PROGRESS.md`。
- `src/` — 全部 Python 脚本（通过 `pathlib` 基于项目根目录解析路径）。
- `artifacts/` — 中间产物（`data_windows.npz`、`scaler.pkl`）。
- `results/` — 各实验的输出（`metrics*.json`、`*.png`、模型）。
- `transcripts/` — OpenCode 会话记录。

脚本可从任意位置运行；它们基于仓库根目录解析路径。

## 约定

- Python + PyTorch、pandas、numpy、scikit-learn、matplotlib。
- 把目标列、窗口长度、切分比例作为文件顶部的顶层参数。
- 把图和指标保存为文件（png / json），放在 `results/` 下。

## 记录

把每一条不正确 / 次优 / 低效的建议记入 `bug_log.md`，
并附上支撑修复的本讲知识（标注课件页码）。
