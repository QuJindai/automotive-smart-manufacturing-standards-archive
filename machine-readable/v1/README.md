# 汽车智能制造机器可执行 Profile V1

本目录是《汽车智能制造国内外标准体系全景研究》工程化资产层，目标是把研究结论编译为可验证对象，而不是在 Git 仓库存放标准原文。

## 当前 V1

- `profile.schema.json`：Profile 包 JSON Schema，Draft 2020-12。
- `evidence.schema.json`：C0-C3 符合性证据包 JSON Schema，Draft 2020-12。
- `index.json`：完整机器资产索引、SHA-256、逻辑 Drive 路径和公开/私有存储策略。

完整 V1 还包括：

- `automotive-manufacturing-profile.v1.json`：P-AAS + P-AI 共 26 条规则；
- `test-cases.yaml`：39 个 C0-C3 测试用例；
- `procurement-FAT-SAT-checklist.xlsx`：采购、实验室、FAT/SAT、C3 持续符合性验收工作簿。

上述完整包长期归档在 Google Drive 的 `05_Profile与符合性工程/02_机器可执行Profile_V1`。公共仓不记录任何 Drive 私有文件 ID 或私有 URL。

## Profile

- **P-AAS**：汽车制造装备开放数据与数字化工程交付 Profile。
- **P-AI**：汽车制造工业 AI Assurance Profile。

## 符合性层级

- C0：自声明/文档与清单；
- C1：实验室/Profile 协议、语义、API、模型与红队；
- C2：FAT/SAT 和真实制造场景；
- C3：量产持续符合性、漂移、事件、变更和复审。

## 治理边界

来源标准/指南的要求与汽车制造工程扩展必须分开标记；AI 性能、安全、时延等数值阈值必须由具体项目 Profile 配置，V1 不凭空设定。
