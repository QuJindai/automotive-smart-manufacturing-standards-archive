# China intelligent-manufacturing standards — engineering implementation layer (Batch 2)

Baseline: 2026-08-25  
Count: 46  
Policy: metadata / lifecycle / adoption / official-entry only. Chinese national-standard fulltext is **not** relayed through Public GitHub Actions artifacts.

## Key findings

- The R05 authoritative 178-record snapshot omitted 7 relevant current series/security nodes found during this official completeness check: `GB/T 23031.1-2022`, `GB/T 23031.2-2023`, `GB/T 23031.4-2023`, `GB/T 23031.6-2023`, `GB/T 33007-2016`, `GB/T 40218-2021`, `GB/T 40682-2021`.
- `GB/T 23031` Industrial Internet platform application guide has six current Parts; R05 had only Parts 3 and 5.
- `20254646-T-604` Open automation system general requirements is now **under review**.
- `20261421-Z-604` and `20261422-Z-604` are now **under review**, adopting IEC TS 62443-6-1:2024 and IEC TS 62443-6-2:2025 respectively.
- Official sources conflict on the adoption year for `20254647-T-604`: one official plan notice says IEC 62443-2-4:2024 while the project adoption page says IEC 62443-2-4:2023. This conflict is retained for later reconciliation rather than silently corrected.

## Industrial communication / SCADA / open automation

- GB/T 38844-2020 — 智能工厂 工业自动化系统时钟同步、管理与测量通用规范 — current; 2025-12-08 review: continue valid
- GB/T 38854-2020 — 智能工厂 生产过程控制数据传输协议 — current
- 20261199-T-604 — 智能工厂 数据采集与监控系统 第1部分：通用技术要求 — drafting
- 20254646-T-604 — 工业过程测量、控制和自动化 开放自动化系统通用要求 — under review
- 20262778-T-604 — 工业过程测量、控制和自动化 数字铭牌 — drafting; IEC 63365:2022

## MOM / MES / shop-floor data

- GB/T 20720.1-2019 — 企业控制系统集成 第1部分：模型和术语 — current; IDT IEC 62264-1:2013
- GB/T 20720.5-2015 — 企业控制系统集成 第5部分：业务与制造间事务 — current; review conclusion: revise
- GB/T 19892.1-2005 — 批控制 第1部分：模型和术语 — current; 2023 review continue valid
- GB/T 19892.2-2007 — 批控制 第2部分：数据结构和语言指南 — current; 2023 review continue valid
- GB/T 19892.3-2022 — 批控制 第3部分：通用和现场处方模型及表述 — current
- GB/T 19892.4-2022 — 批控制 第4部分：批生产记录 — current
- 20262669-T-604 — 离散制造业制造运行管理（MOM）系统 第1部分：参考架构 — drafting
- 20252531-T-604 — 工业自动化系统与集成 工业制造管理数据 第44部分：车间级数据采集的信息建模 — consultation; IDT ISO 15531-44:2017; revises GB/T 19114.44-2012
- SJ/T 11666.1-2016 — 制造执行系统（MES）规范 第1部分：模型和术语 — current
- SJ/T 11666.4-2016 — 制造执行系统（MES）规范 第4部分：接口与信息交换 — current

## Industrial Internet / platforms

- GB/T 23031.1-2022 — 工业互联网平台 应用实施指南 第1部分：总则 — current — R05 gap
- GB/T 23031.2-2023 — 工业互联网平台 应用实施指南 第2部分：数字化管理 — current — R05 gap
- GB/T 23031.3-2023 — 工业互联网平台 应用实施指南 第3部分：智能化制造 — current
- GB/T 23031.4-2023 — 工业互联网平台 应用实施指南 第4部分：网络化协同 — current — R05 gap
- GB/T 23031.5-2023 — 工业互联网平台 应用实施指南 第5部分：个性化定制 — current
- GB/T 23031.6-2023 — 工业互联网平台 应用实施指南 第6部分：服务化延伸 — current — R05 gap
- GB/T 42412-2023 — 基于工业云平台的个性化定制技术要求 — current
- GB/T 45349-2025 — 支持大规模定制生产的网络协同制造服务平台参考架构 — current

## Digital / virtual factory

- GB/T 43064.1-2023 — 智能工厂建设导则 第1部分：物理工厂智能化系统 — current
- GB/T 43064.2-2024 — 智能工厂建设导则 第2部分：虚拟工厂建设 — current
- GB/T 43064.4-2024 — 智能工厂建设导则 第4部分：智能工厂设计文件编制 — current
- GB/T 40648-2021 — 智能制造 虚拟工厂参考架构 — current
- GB/T 40654-2021 — 智能制造 虚拟工厂信息模型 — current

## Robotics / intelligent assembly / HMI

- GB/T 47472-2026 — 复杂产品智能装配平台体系架构 — published; effective 2026-11-01
- GB/T 47860-2026 — 工业机器人集成应用 智能制造单元 成熟度评估方法 — published; effective 2027-02-01
- 20255816-T-604 — 智能制造 人机协同制造系统参考架构 — drafting
- 20255960-T-604 — 智能制造 多模态人机交互系统技术要求 — drafting

## Smart logistics / supply chain

- 20256537-T-604 — 智能物流服务系统集成通用要求 — drafting
- 20261191-T-469 — 智能制造 智慧供应链 风险管理指南 — drafting
- 20261204-T-469 — 智能制造 智慧供应链管理平台 通用技术要求 — drafting

## IACS cybersecurity / conformity assessment

- GB/T 33007-2016 — 工业通信网络 网络和系统安全 建立工业自动化和控制系统安全程序 — current; revision 20254645-T-604 under consultation — R05 gap
- GB/T 35673-2017 — 工业通信网络 网络和系统安全 系统安全要求和安全等级 — current; 2025 review continue valid; IDT IEC 62443-3-3:2013
- GB/T 40211-2021 — 工业通信网络 网络和系统安全 术语、概念和模型 — current; IDT IEC/TS 62443-1-1:2009
- GB/T 40218-2021 — 工业通信网络 网络和系统安全 工业自动化和控制系统信息安全技术 — current — R05 gap
- GB/T 40682-2021 — 工业自动化和控制系统安全 IACS服务提供商的安全程序要求 — current; revision 20254647-T-604 under consultation — R05 gap
- GB/T 42445-2023 — 工业自动化和控制系统安全 IACS环境下的补丁管理 — current; IDT IEC TR 62443-2-3:2015
- GB/T 44861-2024 — 工业自动化和控制系统安全 系统设计的安全风险评估 — current; IDT IEC 62443-3-2:2020
- 20254645-T-604 — 工业自动化和控制系统安全 第2-1部分：资产所有者的安全程序要求 — consultation; IDT IEC 62443-2-1:2024; replaces GB/T 33007-2016
- 20254647-T-604 — 工业自动化和控制系统安全 第2-4部分：服务提供商的安全程序要求 — consultation; adoption-year conflict retained; revises GB/T 40682-2021
- 20261421-Z-604 — 工业自动化和控制系统安全 第6-1部分：IEC62443-2-4安全评估方法 — under review; IDT IEC TS 62443-6-1:2024
- 20261422-Z-604 — 工业自动化和控制系统安全 第6-2部分：IEC62443-4-2安全评价方法 — under review; IDT IEC TS 62443-6-2:2025

## Official sources

Primary sources are the National Standard Information Public Service Platform (`std.samr.gov.cn`) and the National Standard Fulltext Disclosure System (`openstd.samr.gov.cn`). Official fulltext pages state copyright restrictions; adoption-standard disclosure additionally follows international copyright policy. Fulltext is therefore excluded from Public GitHub artifact relay.
