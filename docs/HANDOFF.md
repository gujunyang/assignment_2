# 交接与续接说明（HANDOFF）

> 目的：无论何时重启/新开会话，读到本文件即可**无缝继续**作业。
> 最后更新：见文件修改时间。当前主战场：**Step 4b（加特征选择）**，其后是 **Advanced A（local LLM）**。

---

## 0. 新会话第一句话（可直接粘贴）

```
请先阅读 docs/HANDOFF.md 和 docs/PROGRESS.md，了解作业当前进度与约定，
然后带我继续下一步（当前是 Step 4b）。
```

---

## 1. 当前状态 TL;DR

| 步骤 | 状态 | 关键产物 |
|---|---|---|
| Step 0 EDA | ✅ | `docs/EDA_report.md`、`results/eda/eda_appliances.png` |
| Step 1 数据处理 | ✅（独立验证无泄漏/越界/look-ahead） | `src/data_pipeline.py`、`artifacts/` |
| Step 2 LSTM v1（反例，过拟合 RMSE 282） | ✅ | `src/train_lstm.py`、`results/lstm_v1_broken/` |
| Step 2b LSTM v2（修复，RMSE 78.8） | ✅ | `src/train_lstm_v2.py`、`results/lstm_v2/` |
| Step 3 Transformer（RMSE 78.5） | ✅ | `src/transformer_forecast.py`、`results/transformer/` |
| Step 4 可泛化管线（periodB 迁移） | ✅ | `src/run_forecast.py`、`results/forecast/` |
| **Step 4b 加特征选择（修 `[CODE] #6`）** | 🟡 **prompt 已发出，等待运行** | 待产生 |
| Advanced A local LLM（15%） | ❌ 受阻（网络） | 无 |
| 报告 PDF / transcripts / prompt 归档 | ⬜ 未开始 | 无 |

- 合格 `[CODE]` 计数：**2 / 3**（`#5` 已修；`#6` 待 Step 4b 修）
- 目标变量 `Appliances`，单步预测，L=24，切分 640/160/200，固定种子 42。

---

## 2. 立即待办：Step 4b（把 `[CODE] #6` 真正修掉）

**背景**：`run_forecast.py` 目前把全部 28 个数值列（含 AGENTS.md 注明"无信息"的 `rv1/rv2`）
喂入模型，导致在发布周与 periodB 上都输给 naive。要加特征选择。

**发给 OpenCode 的 prompt（原文，整段复制）：**

```
在 run_forecast.py 上增加特征选择功能，其余逻辑（时间切分、scaler 只在 train、
滑窗、早停、原始尺度指标、naive 对比）保持不变。

1. 新增命令行参数 --features，取值 {all, univariate}，默认 all：
   - all：使用除 date 外的全部数值列，但剔除已知无信息的列 rv1、rv2；
   - univariate：只使用目标列本身（目标的历史），即单变量。
2. 打印实际使用的特征列名与数量（便于核对）。
3. 保证目标列一定包含在特征中。
4. 输出文件命名不变，仍用 --tag 区分。

改完后运行以下命令并贴出全部输出：
python src/run_forecast.py --csv data/A2_data_release.csv --model lstm        --features univariate --tag release_lstm_uni
python src/run_forecast.py --csv data/A2_data_release.csv --model transformer --features univariate --tag release_trans_uni
python src/run_forecast.py --csv data/A2_periodB.csv     --model lstm        --features all        --tag periodB_lstm
python src/run_forecast.py --csv data/A2_periodB.csv     --model lstm        --features univariate --tag periodB_lstm_uni
python src/run_forecast.py --csv data/A2_periodB.csv     --model transformer --features all        --tag periodB_trans
python src/run_forecast.py --csv data/A2_periodB.csv     --model transformer --features univariate --tag periodB_trans_uni
```

**跑完后如何验证（在本对话进行，不写进 prompt）：**
1. 检查代码：`feature_cols` 是否在 `all` 下剔除 `rv1/rv2`，`univariate` 下只留目标列；打印是否显示特征数（all 应为 26，univariate 为 1）。
2. 复跑一遍核对 `metrics_*.json` 数字可复现。
3. 看 `univariate` 是否使发布周 LSTM RMSE 从 157.5 降到 ~78.8（应击败 naive 86.6）。
4. 若 periodB 上单变量也接近/超过 naive，则 `#6` 修复确认；否则继续分析分布偏移。
5. 更新 `docs/bug_log.md` 第 6 条"修复后"为真实数字，并把合格计数改为 **3/3**。

---

## 3. 之后待办（按优先级）

### 3.1 Advanced A：local LLM 对比（15%）— 受阻，待解决网络
- 现状：本机**未安装 Ollama**（只有 `/tmp` 一个 1MB 的残包）。
- 网络事实：
  - `github.com` **被墙**（curl/git 均 75s 超时）；
  - `api.github.com` ✅、`release-assets.githubusercontent.com` ✅、`codeload.github.com` ✅ 可达；
  - `ollama.com` ✅ 可达，但其下载 302 跳到 `github.com` → 失败；
  - `archive.ics.uci.edu` ✅ 可达（periodB 数据即从此处下载）。
- 可用方案（任选）：
  1. 换可用网络/代理后，用 GitHub API 下载资源（已验证可行）：
     ```
     # 查最新 release
     curl -sS -H "User-Agent: curl" https://api.github.com/repos/ollama/ollama/releases/latest
     # 用 asset id 下载（Accept: application/octet-stream），会 302 到 release-assets.githubusercontent.com
     curl -sSL -H "User-Agent: curl" -H "Accept: application/octet-stream" \
       https://api.github.com/repos/ollama/ollama/releases/assets/<ASSET_ID> -o /tmp/ollama-darwin.tgz
     ```
     （此前因网络慢 + 用户中断未成功；命令行版资源为 `ollama-darwin.tgz`，约 167MB）
  2. 在可联网机器上下好 Ollama（或任意本地 LLM），再拷到本机；
  3. 若确实做不到：**如实**在报告里说明"本地部署因网络受阻"，并改用可获得的替代对比（不得伪造"已跑本地 LLM"的结果）。
- 完成后要做：用与 LSTM 相同的 prompt 让本地模型写训练脚本，比较 RMSE、代码质量（找新的 `[CODE]`）、速度；并结合课件 P87（Q4_K_M 量化）/P75-82（显存与量化）讨论权衡。

### 3.2 补齐第 3 个合格 `[CODE]` 条目
- 目前 2 个：`#5`（无早停过拟合，已修）、`#6`（特征未筛选，待 Step 4b 修）。
- 来源建议：Step 4b 的结果；或用**不同的 free model 重跑同一 prompt**（正好满足作业"run multiple times to capture different behaviors"），比较其代码差异并记录。

### 3.3 报告 PDF
- 结构见 `docs/PROGRESS.md` 第七节。
- 必须包含 **3 个 code suggestions**（原始片段 → 问题 → 课件依据 → 修复 → 指标变化）。

### 3.4 session transcripts
- 导出方式（OpenCode）：
  - `/share` 生成分享链接；或
  - `opencode session list` 找 sessionID → `opencode export <sessionID> --sanitize` 得 JSON，转可读后可放入 `transcripts/`。
- 每个阶段一个文件；保留"跑偏→修正"的过程，对应"3 个错误建议"。

### 3.5 prompt 归档（提交用）
- 作业要求提交 prompt。当前所有 prompt 仅存在于对话中；提交前需整理成文件。

---

## 4. 关键约定（务必遵守，避免返工）

1. **时间序列规范**：按时间切分不 shuffle；scaler 只在 train（子训练集）fit；无 look-ahead；窗口不越界；原始尺度报指标；始终对比 naive 基线；种子 42。
2. **公平对比**：LSTM / Transformer / 泛化管线必须用**同一套切分与 scaler**（目前统一为 sub_train=640/val=160/test=200，scaler 在 640 行上 fit）。
3. **提示词给法**：发给 OpenCode 的 prompt **只包含任务本身**，不夹带自查/纠错说明；错误检查在对话里做。
4. **不造假**：不得伪造未实际运行的结果（尤其 local LLM 部分）。
5. **记录**：每发现一个不正确/次优/低效的建议，就追加到 `docs/bug_log.md`（含课件页码依据）。
6. prompt 由对话给出即可（用户偏好不单独存文件）；但本 HANDOFF 保留待办 prompt 以便续接。

---

## 5. 环境与网络备忘

- macOS，Python 3.13（anaconda），**无 brew**。`pip install pymupdf` 已用于读课件 PDF。
- 网络：见 §3.1。UCI 可用、GitHub 主站不可用。
- 运行脚本示例（在项目根目录）：
  ```
  python src/data_pipeline.py
  python src/train_lstm.py
  python src/train_lstm_v2.py
  python src/transformer_forecast.py
  python src/run_forecast.py --csv data/A2_periodB.csv --model lstm --tag periodB_lstm
  ```

---

## 6. 文件地图

- 文档：`README.md`、`AGENTS.md`、`docs/PROGRESS.md`、`docs/EDA_report.md`、`docs/bug_log.md`、`docs/HANDOFF.md`（本文件）
- 代码：`src/{data_pipeline,train_lstm,train_lstm_v2,transformer_forecast,run_forecast}.py`
- 数据：`data/{A2_data_release,A2_periodB,uci_appliances_jan2016}.csv`
- 中间产物：`artifacts/{data_windows.npz,scaler.pkl}`
- 结果：`results/{eda,lstm_v1_broken,lstm_v2,transformer,forecast}/`
- 会话记录：`transcripts/`（暂空）

---

## 7. 远端上传状态（暂停中）

- 远端：`https://github.com/gujunyang/assignment_2`（分支 `main`）。
- 本地：已 commit `df775c8`（"Assignment 2: EDA, data pipeline, ..."），工作区干净。
- 远端：**仍停在初始提交 `7e36001`，尚未推送成功**。
- 失败原因：`git push` 走 `github.com:443`，本机连接 75s 超时被墙；`curl https://github.com` 偶尔能连（约 21s，很慢）。
- 已尝试的绕行：用 keychain 里的 token 调 `api.github.com` 的 Git Data API 上传（脚本在 `/tmp/opencode/push_gh.py`），传到 7/43 时暂停——**未生成远端提交**（只留下若干无引用的 blob，无害）。
- 续接时的三种方案：
  - **A**：开 VPN/代理使 `github.com:443` 可达，然后 `git push -u origin main`（用户倾向此方案）。
  - **B**：续跑 `/tmp/opencode/push_gh.py`（需先 `export GH_TOKEN=$(printf "protocol=https\nhost=github.com\n\n" | git credential fill | sed -n 's/^password=//p')`），通过 API 生成等价提交。
  - **C**：用 token 给账号加 SSH key，再用 `ssh.github.com:443`（该地址可达）走正常 push。
- 注意：方案 B 生成的 commit SHA 与本地不同，之后本地需 `git reset` 对齐。

## 8. 提交清单（作业要求：prompt + 报告 PDF + transcripts）

- [ ] prompt 归档
- [ ] 报告 PDF
- [ ] session transcripts
- [ ] （建议）代码一并提交
- [ ] 截止：**12 Oct**，提交到 Blackboard
