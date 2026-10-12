# 作业进度记录（Assignment 2 — Sequence Recognition）

课程：STAT6207 Applied Deep Learning　｜　作业：Assignment 2
本文件用于跟踪作业完成进度、结果与待办。

> **续接必读**：新会话请先看 [`docs/HANDOFF.md`](HANDOFF.md)（交接与续接说明，含下一步 prompt 原文与网络备忘）。

---

## 一、作业要求与计分（课件 P89）

| 部分 | 内容 | 分值 |
|---|---|---|
| Basic | 用 prompt 驱动 OpenCode 构建 **LSTM** 预测序列下一个值；处理按时间切分、归一化；画图并检查 MSE | 50% |
| Advanced A | 用 **local LLM** 比较结果 | 15% |
| Advanced B | 用 **Transformer** 比较结果 | 15% |
| Advanced C | 构建可泛化的 prompt，处理**同一数据集的不同时间段（未给出）** | 20% |

**硬性交付物**：prompt + 报告 PDF + session transcripts（提交到 Blackboard，截止 12 Oct）。
**报告必须包含**：列出 **3 个 OpenCode 给出的错误/次优/低效的 code suggestions**，并用本讲知识说明修复。

---

## 二、任务进度总览

| 步骤 | 内容 | 状态 | 产物 |
|---|---|---|---|
| Step 0 | 项目初始化 + EDA | ✅ 完成 | `docs/EDA_report.md`、`results/eda/eda_appliances.png`、`AGENTS.md` |
| Step 1 | 数据处理（按时间切分 + 归一化 + 滑窗） | ✅ 完成（独立验证无泄漏/越界） | `src/data_pipeline.py`、`artifacts/` |
| Step 2a | LSTM 初版（无验证集/无早停） | ✅ 完成（**反例**：过拟合，RMSE 282） | `src/train_lstm.py`、`results/lstm_v1_broken/` |
| Step 2b | LSTM 修复版（验证集 + 早停） | ✅ 完成（RMSE 78.8，优于 naive） | `src/train_lstm_v2.py`、`results/lstm_v2/` |
| Step 3 | Transformer 对比（同协议） | ✅ 完成（RMSE 78.5） | `src/transformer_forecast.py`、`results/transformer/` |
| Step 4 | 可泛化管线（不同时间段） | ✅ 完成（迁移成功） | `src/run_forecast.py`、`data/A2_periodB.csv`、`results/forecast/` |
| Step 4b | 给泛化管线加特征选择（修复 `[CODE] #6`） | 🟡 **prompt 已发出，待运行** | 待产生 |
| Advanced A | local LLM 对比 | ❌ **未完成**（本机 Ollama 下载被网络阻断） | 无 |
| — | 报告 PDF | ⬜ 未开始 | 待写 |
| — | session transcripts | ⬜ 未导出 | 待导出到 `transcripts/` |

图例：✅ 完成　🟡 进行中　⬜ 未开始　❌ 受阻

---

## 三、结果汇总（测试集，原始 Wh 尺度）

### 3.1 发布周（`data/A2_data_release.csv`）

| 模型 | MSE | MAE | RMSE |
|---|---:|---:|---:|
| Naive persistence（基线） | 7500.0 | 33.3 | **86.6** |
| LSTM v1（无验证/无早停） | 79745.3 | 225.4 | **282.4** ❌ |
| LSTM v2（单变量 + 早停） | 6208.4 | 36.0 | **78.8** ✅ |
| Transformer（单变量） | 6165.5 | 40.6 | **78.5** ✅ |
| LSTM（28 特征） | 24821.6 | 113.9 | 157.5 |
| Transformer（28 特征） | 11869.8 | 79.7 | 108.9 |

### 3.2 不同时间段 periodB（`data/A2_periodB.csv`，01-18 15:40 → 01-29 15:20，与发布周无重叠）

| 模型 | RMSE | Naive RMSE |
|---|---:|---:|
| LSTM（全特征） | 17.5 | 11.0 |
| Transformer（全特征） | 16.2 | 11.0 |

> periodB 测试段（01-27→29）Appliances 均值仅 37、std 10，naive 极强，全特征模型仍不敌基线。

---

## 四、核心结论

1. **过拟合教训**：没有验证集/早停时，LSTM 训练出一个**比 naive 基线还差 3.3 倍**的模型（RMSE 282 vs 86.6）。加入按时间的验证集 + 早停后修复。
2. **特征选择 > 换架构**：单变量（只用目标历史）让 LSTM/Transformer 都击败 naive（78.8 / 78.5）；喂入全部 28 列（含无信息的 `rv1/rv2`）反而更差。
3. **架构对比**：单变量下 LSTM 与 Transformer 几乎打平；Transformer 对噪声特征更鲁棒但参数约 2 倍（约 100k vs 50k），呼应课件 P59。
4. **泛化性**：`run_forecast.py` 可对任意时间段直接运行（无需改代码），在 periodB 上迁移成功。

---

## 五、OpenCode 错误记录（报告 "3 code suggestions"）

详见 `docs/bug_log.md`。

- 合格 `[CODE]` 计数：**2 / 3**
  - `#5` 无验证集/无早停导致过拟合（已修复）
  - `#6` 泛化管线喂入全部特征（含噪声列），修复方案已验证，待应用到 `run_forecast.py`
- 另有 4 条 `[EDA/流程]` 补充素材（EDA 事实/数值错误、`/init` 遗漏），不计入那 3 条。

> 仍需再补 ≥1 个合格 `[CODE]` 条目（可来自 Step 4b 的结果，或用不同 free model 重跑捕获）。

---

## 六、待办清单

- [ ] **Step 4b**：运行已发出的 prompt，给 `run_forecast.py` 加 `--features {all,univariate}`、默认丢弃 `rv1/rv2`，重跑 periodB，确认 `[CODE] #6` 修复。
- [ ] **Advanced A（15%）**：本地 LLM 对比。当前本机 Ollama 因 `github.com` 被墙无法下载；备选：换可用网络/镜像安装 Ollama，或如实说明并在报告中选择替代方案。
- [ ] 补齐第 3 个合格 `[CODE]` 条目。
- [ ] 撰写 **报告 PDF**（结构见下）。
- [ ] 导出 **session transcripts** 到 `transcripts/`。
- [ ] 整理 **prompt** 用于提交（当前 prompt 仅存在于对话中）。
- [ ] 打包提交到 Blackboard（截止 12 Oct）。

---

## 七、报告建议结构

1. 引言：任务定义、数据描述
2. 方法与 prompt 设计（时间切分、只 fit train 的 scaler、滑窗、早停）
3. Basic：LSTM 结果（含 v1 反例 → v2 修复）+ naive 基线
4. Advanced B：Transformer 对比（位置编码、参数量、训练时间）
5. Advanced C：可泛化管线设计 + periodB 迁移证据
6. Advanced A：local LLM 对比（或说明受阻原因）
7. **3 个错误建议分析**：原始片段 → 问题 → 课件依据 → 修复 → 指标变化
8. 结论与局限（仅 7 天数据、单步预测、分布偏移等）
9. 附录：完整 prompt、transcripts、代码清单

---

## 八、文件清单

- `docs/`：`EDA_report.md`、`bug_log.md`、`PROGRESS.md`（本文件）、课件 PDF
- `src/`：`data_pipeline.py`、`train_lstm.py`、`train_lstm_v2.py`、`transformer_forecast.py`、`run_forecast.py`
- `artifacts/`：`data_windows.npz`、`scaler.pkl`
- `results/`：`eda/`、`lstm_v1_broken/`、`lstm_v2/`、`transformer/`、`forecast/`
- `data/`：`A2_data_release.csv`、`A2_periodB.csv`、`uci_appliances_jan2016.csv`
- 根目录：`README.md`、`AGENTS.md`
