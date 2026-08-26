# 汽车智能制造机器可执行 Profile V1

本目录是《汽车智能制造国内外标准体系全景研究》工程化资产层，目标是把研究结论编译为可验证对象，而不是在 Git 仓库存放标准原文。

## 当前 V1

- `profile.schema.json`：Profile 包 JSON Schema，Draft 2020-12。
- `evidence.schema.json`：C0-C3 符合性证据包 JSON Schema，Draft 2020-12。
- `index.json`：完整机器资产索引、SHA-256、逻辑归档路径和公开/私有存储策略。

完整 V1 资产还包括：

- `automotive-manufacturing-profile.v1.json`：P-AAS + P-AI 共 26 条规则；
- `test-cases.yaml`：39 个 C0-C3 测试用例；
- `procurement-FAT-SAT-checklist.xlsx`：采购、实验室、FAT/SAT、C3 持续符合性验收工作簿。

完整机器资产包长期沉淀在项目持久资产库；公共仓不记录任何 Google Drive 私有文件 ID 或私有 URL。

## Profile

- **P-AAS**：汽车制造装备开放数据与数字化工程交付 Profile。
- **P-AI**：汽车制造工业 AI Assurance Profile。

## P-AAS 可执行参考实现

`reference-implementation/p-aas-v1/` 提供一个纯 Python 标准库、合成数据驱动的参考执行器。公共仓只提交执行 P-AAS 所需的 14 条规则子集和 19 个 AAS 测试定义；完整 P-AAS + P-AI 资产仍由长期资产包治理。

参考执行器可以在嵌入式合成 AAS 服务上运行 `AAS-T001` 到 `AAS-T019`，生成 `evidence-bundle.json`、`test-summary.json` 和运行时 `sample.aasx`。生成的 AASX / evidence 仅作为短期 CI artifact 和持久证据归档，不提交进 Git 历史。

## 符合性层级

- C0：自声明/文档与清单；
- C1：实验室/Profile 协议、语义、API、模型与红队；
- C2：FAT/SAT 和真实制造场景；
- C3：量产持续符合性、漂移、事件、变更和复审。

## 治理边界

来源标准/指南的要求与汽车制造工程扩展必须分开标记；AI 性能、安全、时延等数值阈值必须由具体项目 Profile 配置，V1 不凭空设定。
