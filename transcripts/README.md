# Session Transcripts (for submission)

This directory stores the OpenCode session records for each stage of this assignment (Markdown format, exported by OpenCode).
Each file name is the session ID; the "Stages covered / related bug_log" column below was annotated after manually checking the transcript contents.

| File                                          | Machine                   | Model                             | Stages covered                                                                                                                                    | Related `bug_log`      |
| --------------------------------------------- | ------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------- |
| `session_ses_ecfe1d76cffeFXkR4UhF919VsK.md` | macOS (`/Users/gu/...`) | big-pickle (opencode free model)  | **Main experiment session**: Step 0 EDA → Step 1 data processing → Step 2 LSTM v1 → Step 2b LSTM v2 → Step 3 Transformer → Step 4 generalizable pipeline → export this session | `#1`–`#5`, `#7` |
| `session_ses_ecf6aab1dffe9TrI5dirH4narT.md` | Windows                   | big-pickle (opencode free model)  | **Step 4b feature selection** (fixing `#6`) + Advanced A local LLM installation attempt and actual deployment                              | `#6`                 |
| `session_ses_ecf6cf53effeDP3ie6Gr4zOzp3.md` | Windows                   | big-pickle (opencode free model)  | Continued session: Step 4b result acceptance + Advanced A discussion (local LLM plan)                                                          | `#6`                 |
| `session_ses_ed05f4596ffeupDaEUn3uolw38.md` | Windows                   | big-pickle (opencode free model)  | Initialize git and push the remote repository                                                                                                     | — (engineering process) |
| `session_ses_ecf6daf88ffe8Pc7Istneu3XqR.md` | Windows                   | big-pickle (opencode free model)  | Pull the content of the remote repository                                                                                                         | — (engineering process) |

## Notes

- The **3 erroneous/suboptimal code suggestions** required by the report correspond respectively to:
  - `#5` (no validation set / no early stopping → overfitting) and `#7` (test-set leakage) — see the macOS main session `ses_ecfe1d76...`;
  - `#6` (generalizable pipeline without feature selection) — see `ses_ecf6aab1...` and `ses_ecf6cf53...`.
- The sessions preserve the complete "going astray → correction" process, corresponding entry by entry to `report/bug_log.md`.
- The main experiment took place on a macOS machine (path `/Users/gu/Desktop/assignment_2`), then migrated to Windows (this repository's path) to continue Step 4b and Advanced A.
- To re-export: use `opencode session list` to find the sessionID, then `opencode export <sessionID>`.
