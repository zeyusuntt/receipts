# 调研：什么样的东西能赢，以及我们的选题候选

> 一句话：评委多数来自 Nebius/NVIDIA 平台和 DevRel，奖励「深度用平台 + 闭环自治 + 有证据」；最适合我们的是 A 的收敛版：给一个 Python repo 和一个 issue，Nemotron 在 Token Factory Sandbox 里分叉出两条修复分支，只有 patch 和测试执行都有机器可核验回执的那条分支才被采纳，假绿灯当场被拒。它把我们最痛的两件事（agent 静默失败、绿灯掩盖没跑的活）变成产品卖点。Codex 评审意见见第 8 节。
> 需要本人决定：选 A / B / C 之一，或另提。
> 写于 2026-09-29，来源：Devpost 赛事页（overview / rules / updates 46204、46205 / resources）、可比赛事获奖名单、本地项目与 memory。事实以赛事页为准。

## 1. 评委到底看什么

评审两阶段。第一阶段 pass/fail：主题相符 + 真的调用了 Token Factory + 用了 NVIDIA 开源模型。第二阶段四项等权：

| 标准 | 原文关键句 | 对我们的含义 |
|---|---|---|
| Technological Implementation | how effectively does it use Token Factory ... and Nemotron | 用得深不深，不是有没有用 |
| Design | a complete, coherent product experience, not just a technical proof of concept | 完整连贯的产品体验加可访问的 demo URL；规则没有要求 GUI |
| Potential Impact | a credible, specific case for solving a real problem for a real audience | 视频里最好有真实使用场景 |
| Quality of Idea | creative, non-obvious use ... genuine understanding of the problem space | 讲清楚问题空间，别做 chat wrapper |

主办方 update「Here's how judging works」直接给了每个赛道的基线和上限：

- Coding：a code-completion wrapper is a start; **an agent that plans, writes, tests, and iterates on a real repo with minimal human input** is where it gets interesting.
- Apps and Agents：single API call demo works; **a multi-step autonomous workflow that chains tools end to end** stands out.
- Personal AI：chatbot with system prompt is fine; **remembers context across sessions and takes real action** is what we hope to see.
- Physical AI：hardware reacting live to real-world input.

Update「How to build a winning project」：对 Nebius 工具和 NVIDIA 模型的具体、可操作的 feedback 是每份提交的必填项，另有 10 个 $100 的 Most Valuable Feedback 奖。视频顺序：问题 → 可运行的解决方案 → 价值、受众、工具集成。

评委 23 人：Nebius DevRel、PMM、产品和 GTM（含 Token Factory PMM、Serverless AI TPM）、NVIDIA 工程师（含 Jetson、Physical AI）、Tavily 三位 FDE。没有 VC。推断（不是事实）：这批人会认出 Sandbox 分支、checkpoint、模型分层这些平台特性，也会认真读 feedback。规则说评委不必测试项目，但可以测试，所以 demo URL 要真的能跑。

## 2. 可比赛事的赢家长什么样

| 赢家 | 赛事 | 为什么赢 |
|---|---|---|
| LORE | GitLab AI Hackathon 2026 大奖 | 8 agent 知识引擎，评委原话 "feels like a product, not a hackathon project" |
| Time-Traveler | GitLab 最具技术性 | 在生产副本上沙盒测试 DB migration，具体又吓人的开发者问题 |
| DocSync | GitLab Anthropic 奖 | Detector/Writer/Reviewer 三 agent 修文档漂移，不确定时升级给人 |
| OpenCodeReview | NVIDIA NeMo Agent Toolkit 第 2 | 安全代码审查，评委赞「不改 prompt 就能换模型」 |
| TCS Route Agent | NeMo Agent Toolkit 第 1 | 把 NVIDIA 全家桶串到 Jetson，平台叠得最深 |
| PASCAL-MoE (Nota) | Nemotron Developer Days 首尔大奖 | 评委赞 "not only qualitative but also quantitative evaluation" |
| Sentinel | OpenAI Build Week 开发工具 | MCP 安全扫描；赢家共性：领域专家 + 几十到几百个测试 + 约束并校验模型输出 |
| veTriage / Medkit | OpenAI Build Week / Anthropic Opus 4.7 | 领域从业者做的，视频里有真实用户 |
| EcoLafaek | AWS AI Agent Global 第 1 | 具体真实受众 + 用赞助商最新产品用得最深 |
| SalesShortcut | Google ADK 大奖 (477 entries) | 端到端全自动多 agent 工作流 |

## 3. 获胜模式（按出现频率）

1. 闭环自治：plan、act、verify、iterate、escalate。不是 chat wrapper。
2. 把赞助商最新的产品用到最深。这次就是 Token Factory Sandboxes（contree-sdk，Git 式 branching、checkpoint、预装 7000 个 SWE-bench / SWE-rebench 环境）和 Nemotron Nano / Super / Ultra 分层。
3. 具体真实受众，视频里能看到人用。
4. 量化证据：README 和视频里有 eval 表。少见，但被评委点名表扬。
5. 像个产品：UI、onboarding、README、可访问的 URL。
6. 视频 60 到 90 秒内出现 wow moment，屏幕上点名赞助商技术。
7. 一件事做好，不堆五个功能。
8. 把「校验模型输出」本身当功能（Sentinel、DocSync 的升级机制）。

## 4. 会输的

Chat wrapper、code-completion wrapper、单次 API 调用 demo；模板换皮；只有后端没有 demo URL；视频里 live 调用卡住；feedback 空泛；scope creep；repo 里有 key、没 license。Coding 赛道已经拥挤的方向：SWE-bench 式 fix-an-issue 单 agent、code review bot。

## 5. 我们的本钱和痛点

Zeyu 的优势：benchmark 和 eval 基建（Harbor 贡献者、AERead runtime、Terminal-Bench-Science）；agent-postmortem（11 个 detector、590 tests）；Foreman（130 tests、Check DSL、verifier、Harbor runner、sabotage demo）；每天同时开 Claude Code 和 Codex。自述短板是 pitch，而本赛事只看提交材料。

亲身经历的痛点，按出现次数：

1. coding agent 静默失败且无法证明原因（110 runs 里 39 次 silent retry，一台 Mac 上损失约 38 小时）。
2. 绿灯掩盖没做的活（74 条 Codex 评审因 truthy return 丢失、31 个测试静默跳过、harness 缺陷被记成模型失败）。
3. 不知道怎么验证 agent 做对了、自我修复没跑偏（「agent 越修越糟糕」）。
4. 多个并行 agent session 分散注意力。
5. 冷启动和交接。

## 6. 候选（排序）

### A（推荐）：分叉核验式修 repo agent

一句话：给一个 repo 和一个 issue，Nemotron 规划后把 Token Factory Sandbox 分叉成 N 条分支，每条分支独立写 patch、跑测试；每条分支的「我修好了」都要过一道证据核验（测试真的跑了吗、exit code、diff 是否存在、日志里有没有静默重试），假绿灯当场被抓；通过核验的分支才进入下一轮或出 PR。

- 为什么能赢：逐字命中 Coding 赛道上限句；Sandbox 分叉和 checkpoint 只有这个平台能演示，评委是平台人；Nano 写 patch、Super 做规划和裁判，正好是规则里的模型分层指引；wow moment 是「一条分支声称通过，核验器发现测试根本没跑」，这是我们亲身经历过的事；可以在 Sandbox 预装的 SWE-rebench 环境上跑出 eval 表（单分支 vs 分叉、有无核验）。
- 复用：agent-postmortem 的 detector 思路和 fixtures 改造成 trace 核验；Foreman 的 verifier 和 sabotage demo 形态；Harbor 经验。
- 赛道：Coding and Agentic Engineering。
- 风险：规划循环从零写；Nemotron 3 Super 的 tau-bench 公开成绩 56 到 64 提示 tool calling 需要防守（json_schema 约束、每轮一个 tool call、一次修复重试、硬步数上限），但这不是 Token Factory 上 tool-call 保真度的直接证据；Sandbox 处于 Beta，每条命令生成新的文件系统镜像，分支 DAG 和当前镜像 UUID 要自己维护；时间与 Oct 5 TB-Science、Oct 11 Talent Hunt、Oct 15 到 20 Open Agent 冲突。
- 保底：如果分叉在 48 小时内验证不通，退到单分支循环加证据核验。这保住 wow moment，但失去「分叉比较」的新意，所以分叉要最先验证。

### B：Foreman on Nemotron + Sandboxes runner

一句话：职位描述进，agent 加生成的 benchmark 出，benchmark 在 Token Factory Sandbox 里跑，通过才解锁 Deploy；破坏版 agent 被生成的测试抓住。

- 为什么能赢：复用最多（约 80%），sabotage demo 现成，「agent 建 agent 并自证」是非显然的想法。
- 弱点：真实受众不如 A 直观；Zeyu 已经撤回过一次；live builder 写的 check 还脆。
- 赛道：Coding。

### C：Sandbox 取证 agent（agent-postmortem 上 Nemotron）

一句话：读别的 coding agent 的运行记录，在 Sandbox 里重放，给出带 path:line 引用的失败原因。

- 为什么能赢：差异化最强，痛点最真。让 Nemotron 提出假设并选择重放，而不是只总结日志，criterion 1 就站得住。
- 弱点：与 Oct 15 到 20 的 Open Agent 参赛作品重叠，两个 repo 的「新工作」界线要分清，规则要求 Aug 26 之后有显著更新。
- 赛道：Best Apps and Agents。

### D（Codex 提出）：issue 到最小复现 agent

一句话：给 issue、错误栈和 repo，Nemotron 在 Sandbox 里分叉「依赖版本假设」和「代码假设」两类分支，Tavily 抓上游文档，输出一个最小失败测试、一个锁定的环境和一份可重放的证据包。

- 为什么能赢：比修任意 bug 窄，正确性标准干净（复现了就是复现了），天然用到分叉和 Tavily，三家赞助商都沾。
- 弱点：从零；「复现器」比「修复器」离赛道上限句远一步；wow moment 不如假绿灯被抓直观。
- 赛道：Coding。

### 不推荐

- Nemotron harness 调优（有数字但不像产品）。
- Personal AI 记忆助手（赛道拥挤，之前已否）。
- 签证/报税等个人事务助手（无复用资产、材料敏感）。

## 7. 不管选哪个都要做的

- `FEEDBACK.md` 从第一天记，每条带复现；最好的三条填进 Devpost，当天发到 Nebius 社区。
- Oct 9 SF Builders & Brews 到场（$500 City Winner 的条件，还有额外 credits）。
- Tavily 可选：用 map + extract 给 issue 做上下文检索，冲 $3k Best Use of Tavily。
- eval 表只有几条任务时，叫它 pilot 或描述性证据，公开每条任务、seed、trace 和结果，不要叫 benchmark。
- demo 用录好的 cassette，视频不依赖 live 延迟。
- README 让陌生人从 clean clone 四个环境变量跑起来。

## 8. Codex 对抗性评审的结论（2026-09-29，读后修订）

Codex 读了本文和 HANDOVER.md 后的判断，已按它的意见修改了上面的措辞：

- A 只有在「证据核验就是分支选择规则」时才是一个产品，否则是「修 repo agent」和「取证系统」两个产品粘在一起。砍掉：迭代树、自动 PR、模型分层、通用 trace 取证、任意 repo。保留：固定两条分支、一轮修复、确定性的晋升规则。
- 一句话产品：Given a Python repository and an issue, Nemotron creates two sandboxed fixes and returns only the branch whose patch and intended test execution are proven by machine-verifiable receipts.
- 最小高分版本：一种 issue 格式；一个或一小族预备好的公开 Python repo；一个 Sandbox checkpoint 分叉成恰好两条分支；Nemotron 输出结构化 plan 和 patch；由我们的 executor（不是模型）记录命令、exit code、测试收集数、skip、超时、diff 和产物；一个确定性 gate 拒掉「声称成功但没有有效测试证据」的分支；一个小 web demo 显示两张分支卡、被拒的假绿灯、被选中的 patch 和可展开的证据包。
- 建造顺序：Day 1 到 4，单分支的完整 live 竖切（Token Factory 推理、校验过的 tool call、Sandbox 执行、打 patch、跑测试、导出回执），分叉当作 48 小时 kill gate；Day 5 到 9，第二条分支、固定预算、确定性核验、一个受控假绿灯 fixture、一次修复；Day 10 到 15，评委视角 UI、托管的 replay、README、feedback 日志、原始证据、评估、视频。
- 评估：3 个真实 issue 加约 6 个对抗性 verifier fixture；比较单分支 vs 两分支、核验关 vs 开，指标是任务成功、假绿灯检出、延迟、token 成本。
- 主要失败点和对策：模型评模型不算独立核验（只有 executor 的谓词能决定晋升）；tool call 形状对但流程错（有界状态机、每轮一个 call、一次修复重试、硬上限）；Sandbox 语义可能出乎意料（先测 clone、装依赖、分叉、日志、取产物、取消、超时，再写 agent 循环）；分支树三分钟看不懂（固定两分支，大字 PASS / REJECTED / SELECTED，不滚终端）；并行分支放大延迟和 credits（上限两条，视频用 cassette）；任意 repo 有密钥和供应链风险（只用预备的公开 repo，不注入凭据，命令白名单）。
- B 的最强说法是「deploy 必须先过可执行的 benchmark」，四项等权之下，打磨好的 Foreman 可能赢过半成品 A。C 最有差异化，但存在项目重叠和 Aug 26 显著更新边界的提交风险。
