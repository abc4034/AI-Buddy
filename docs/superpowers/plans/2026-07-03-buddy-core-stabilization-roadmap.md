# Buddy Core 第二阶段稳定化与后续服务器替换路线图

## 0. 当前实施进度更新（2026-07-03）

已完成的第一批执行项：

- 阶段 A 的 Windows 本地 demo 脚本已补齐：启动 Buddy Core、启动 XiaoZhi Server、状态检查、备份、停止清理、URL 打印和 smoke test。
- 阶段 A 的 runbook 已补齐：`docs/runbooks/windows-local-demo.md`，包含启动顺序、日志查看、硬件测试步骤和常见排查。
- 阶段 B 的 device/profile/persona/memory 主链路已实现：Buddy Core 按 `device-id` 区分孩子，支持 `config/devices.yaml` 配置 profile 和 persona。
- Memory 面板已支持按设备查看、URL encode、当前设备 reset、client/user/device 信息展示。
- OpenAI-compatible `/v1/chat/completions` 保留为 XiaoZhi 接入和本地调试入口。
- 新增双设备调试脚本：`scripts/smoke_two_devices.ps1`，用于不连硬件时验证两个 `device-id` 的 profile/memory 分离。
- 新增配置/关系/Memory 说明文档：
  - `docs/buddy-core-configuration.md`
  - `docs/buddy-core-and-buddy-brain.md`
  - `docs/runbooks/memory-dashboard.md`
- Buddy Core 非流式回复已增加 TTS 友好清洗兜底，减少 Markdown 和 emoji 进入硬件朗读路径。
- 自动化测试最近一次验证：`89 passed, 1 warning`。

仍需人工或后续阶段确认：

- 真实 ESP32 硬件链路需要在 Buddy Core 重启后再复测一轮，确认 TTS 清洗后的实际语音效果。
- 汇报前建议用户侧按 runbook 多测几轮，尤其是换 WiFi 后的 LAN IP 和 OTA URL。
- 阶段 C 的 Buddy Device Gateway 仍只作为路线图，不在当前执行批次实现。

## 1. 背景与当前状态

我们已经完成第一步局域网 PoC：

```text
ESP32-S3 小智固件
  -> XiaoZhi Server 协议层 / 音频层
  -> BuddyCoreLLM OpenAI-compatible 适配
  -> Buddy Core
  -> LLM / SQLite Memory / Persona
  -> TTS 语音返回硬件
```

当前验证结果：

- Buddy Core 运行在 `8010`，健康检查通过。
- XiaoZhi Server 运行在 `8000` WebSocket 和 `8003` OTA。
- ESP32 能通过局域网 OTA 拿到 WebSocket 地址。
- ESP32 能完成语音输入、ASR、Buddy Core 回复、TTS 播放闭环。
- 真实硬件 `device-id` 已经传入 Buddy Core，并写入 SQLite memory。
- 当前架构图已导出：
  - `docs/architecture/buddy-step1-system-architecture-clean.png`

下一阶段的重点不是马上重写 XiaoZhi Server，而是先把已跑通的 PoC 固化成稳定 demo，同时把 Buddy Core 做得更像正式业务核心。

## 2. 阶段目标

### 近期执行

1. **阶段 A：PoC 稳定化**
   - 让当前局域网 demo 可以稳定复现、稳定演示、稳定排查。

2. **阶段 B：Buddy Core 能力增强**
   - 让 Buddy Core 从“能被硬件调用的大脑原型”升级为更清晰的业务核心。

### 暂不执行，仅作为路线图

3. **阶段 C：自研 Buddy Device Gateway**
   - 设计未来替换 XiaoZhi Server 的整体框架，但本阶段不开始重写协议层。

## 3. 非目标

本计划暂不做这些事情：

- 不重写 ESP32 固件。
- 不立刻替换 XiaoZhi Server。
- 不做公网部署。
- 不做浏览器端正式产品界面。
- 不把 ASR/TTS 全部替换成自研实现。
- 不引入复杂账号体系。

### 3.1 当前执行约束

- 当前阶段只支持 **Windows + PowerShell + conda `xiaozhi-env`**。
- Ubuntu、普通 venv、Docker、公网部署可以保留在 README 或后续文档中，但不作为本阶段验收范围。
- Codex 侧 demo 验收以 **完整跑通一次软硬件链路** 为准；用户可在汇报或演示前自行多测几轮。
- 第三阶段的服务器替换路线，默认继续兼容现有 ESP32 小智固件，不把改固件作为前提。

## 4. 阶段 A：PoC 稳定化

### 4.1 目标

把当前已经跑通的局域网链路整理成一个可复现、可汇报、可排查的稳定 demo。

### 4.2 工作项

- [ ] 固化运行环境
  - 明确当前阶段使用 `conda activate xiaozhi-env`。
  - 所有 PowerShell 脚本默认使用 `xiaozhi-env`。
  - 文档中避免同时给出多个同等优先级的环境路径，防止再次写错环境名。

- [ ] 增加 demo 数据备份步骤
  - demo 前备份 `data/buddy_memory.db`。
  - 重渲染 XiaoZhi 配置前备份 `.run/xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml`。
  - reset memory 前确认当前选中的 `device-id`，避免误删其他孩子数据。

- [ ] 统一启动入口和命名
  - 保留旧脚本兼容。
  - 对外文档统一叫 `Buddy Core`。
  - 可考虑新增 `start_buddy_core.ps1`，逐步弱化 `start_buddy_brain.ps1` 的命名。

- [ ] 增加停止、重启和端口清理说明
  - 说明如何查看 `8000`、`8003`、`8010` 的占用进程。
  - 说明如何停止 Buddy Core。
  - 说明如何停止 XiaoZhi Server。
  - 可考虑新增 `stop_local_demo.ps1`，统一清理当前 demo 相关进程。

- [ ] 增加 demo 状态检查脚本
  - 检查 `8010` Buddy Core health。
  - 检查 `8000` XiaoZhi WebSocket 端口。
  - 检查 `8003` OTA/HTTP 端口。
  - 打印当前 LAN IP、OTA URL、WebSocket URL、Buddy Core URL。
  - 检查当前 XiaoZhi 配置中的 `BuddyCoreLLM`、`base_url` 和 `forward_device_metadata`。

- [ ] 固化启动顺序
  - `render_xiaozhi_config.ps1`
  - `start_buddy_core.ps1`
  - `smoke_chat.ps1`
  - `start_xiaozhi_server.ps1`
  - ESP32 连接 OTA 地址

- [ ] 固化日志查看方法
  - Buddy Core 前台日志。
  - XiaoZhi Server `tmp/server.log` 实时 tail。
  - 常见乱码说明。
  - 端口占用排查命令。

- [ ] 固化 XiaoZhi runtime patch 验证方法
  - 确认 `.run` 中 OpenAI provider 会把 `device_id`、`client_id`、`session_id` 放入 chat metadata。
  - 确认 `connection.py` 会从硬件连接 headers 读取 `device-id` 和 `client-id`。
  - 确认 `setup_xiaozhi_server.ps1` 可以重复应用这些补丁。
  - 如果 `.run` 被重新下载或覆盖，必须重新运行 `setup_xiaozhi_server.ps1`。

- [ ] 整理硬件测试 Runbook
  - 电脑和 ESP32 必须在同一个 WiFi。
  - OTA URL 示例。
  - 如何确认 OTA 请求到了本机。
  - 如何确认 WebSocket 连接到了本机。
  - 如何确认 ASR/LLM/TTS 三段都工作。
  - 如何在 memory 面板看到真实 `device-id`。

- [ ] 整理汇报材料
  - 第一阶段成果说明。
  - 系统架构图。
  - 已验证测试列表。
  - 当前非阻塞问题。
  - 下一阶段路线。

### 4.3 验收标准

- [ ] 新开一个 Windows PowerShell，可以按文档在 `xiaozhi-env` 下完整启动 demo。
- [ ] `smoke_chat.ps1` 能成功返回 Buddy Core 回复。
- [ ] ESP32 能从本机 OTA 拿到 WebSocket 地址。
- [ ] ESP32 能完成至少一轮语音问答。
- [ ] 本阶段 Codex 侧只要求完整硬件 demo 通过一次；用户侧可在汇报前继续多轮复测。
- [ ] SQLite memory 中能看到真实硬件 `device-id`。
- [ ] XiaoZhi runtime patch 验证通过，`device-id` 能稳定转发到 Buddy Core。
- [ ] 遇到端口占用、IP 变化、日志无输出时，文档有明确处理方法。

## 5. 阶段 B：Buddy Core 能力增强

### 5.1 目标

把 Buddy Core 做成真正的业务核心，而不只是“一个能响应 chat/completions 的转发服务”。

### 5.2 推荐模块边界

```text
Buddy Core
  ├─ OpenAI-compatible API
  ├─ Device Identity
  ├─ Child Profile
  ├─ Persona Config
  ├─ Prompt Builder
  ├─ Memory Repository
  ├─ Memory Dashboard
  └─ Debug Tools
```

### 5.3 工作项

- [ ] 设备身份模型增强
  - 继续用 `device-id` 区分孩子。
  - 明确 `device-id -> user_id -> profile -> memory` 的映射关系。
  - 对未知设备创建默认孩子 profile。
  - 保留后续通过配置文件指定设备名称、孩子昵称、年龄段、语言水平的能力。
  - 实现前先检查现有项目结构，再决定配置文件路径；默认优先考虑 `config/devices.yaml`，如果与现有结构不协调再调整。
  - 配置文件第一版建议包含：`device_id`、`child_name`、`age_group`、`english_level`、`persona`。

- [ ] Persona 配置增强
  - 第一版仍然写在配置文件里。
  - 支持至少三种 persona：
    - `cheerful`
    - `calm`
    - `coach`
  - 每种 persona 要有明确行为差异，而不是只改名字。

- [ ] Prompt Builder 整理
  - 统一从 child profile、persona、memory、当前输入生成 prompt。
  - 控制回复长度，适合 TTS 播放。
  - 减少 Markdown 对 TTS 的干扰。
  - 硬件语音回复尽量使用短句，避免 `**bold**`、复杂列表、过多括号和不适合朗读的格式。
  - 保持中英双语教学风格。

- [ ] Memory 面板增强
  - 保留当前 `/memory` 面板。
  - 支持按设备查看：
    - device-id
    - client-id
    - user-id
    - child profile
    - 最近对话
    - 最近记忆更新时间
  - reset 时只清理当前选中设备。
  - 避免误删所有 demo memory。
  - `/memory?device_id=...` 链接和 reset action 必须做 URL encode，兼容带冒号或特殊字符的真实设备 id。

- [ ] 调试能力增强
  - 保留 OpenAI-compatible `/v1/chat/completions`。
  - 增强 `smoke_chat.ps1`，可以传入不同 `device-id`。
  - 增加不连硬件的调试说明：

    ```text
    模拟设备 A -> 产生 profile A 和 memory A
    模拟设备 B -> 产生 profile B 和 memory B
    ```

- [ ] 测试覆盖
  - device-id 映射测试。
  - persona prompt 测试。
  - memory 面板测试。
  - reset 单设备测试。
  - smoke chat metadata 测试。
  - XiaoZhi config 渲染测试。

### 5.4 验收标准

- [ ] 不连硬件时，可以用脚本模拟两个不同设备，并看到不同 memory。
- [ ] 连硬件时，真实 ESP32 的 `device-id` 能稳定映射到对应 profile。
- [ ] memory 面板能清楚展示当前设备数据。
- [ ] 修改 persona 配置后，Buddy Core 的回复风格有可观察差异。
- [ ] 所有自动化测试通过。
- [ ] 文档能解释 Buddy Core 和旧 Buddy Brain 的关系。

## 6. 阶段 C：自研 Buddy Device Gateway 路线图

> 本阶段只写框架，不执行实现。

### 6.1 目标

未来逐步替换 XiaoZhi Server，把协议层和音频链路迁移到我们自己的服务器中。

第三阶段默认继续兼容现有 ESP32 小智固件。只有在确认协议兼容路线不可行时，才讨论是否修改固件。

### 6.2 推荐目标架构

```text
ESP32-S3 小智固件
  -> Buddy Device Gateway
      -> OTA Handler
      -> WebSocket Session Manager
      -> XiaoZhi Protocol Adapter
      -> Opus Audio Pipeline
      -> ASR Provider
      -> TTS Provider
  -> Buddy Core
      -> Persona
      -> Profile
      -> Memory
      -> LLM
```

### 6.3 模块职责

- **Buddy Device Gateway**
  - 只负责硬件连接、协议兼容、音频收发。
  - 不负责人格、记忆、学习策略。

- **Buddy Core**
  - 只负责业务逻辑、孩子身份、人格、记忆、LLM 调用。
  - 不直接处理 Opus、WebSocket 细节。

- **ASR/TTS Provider**
  - 作为可替换模块。
  - 第一版可以复用已验证方案。
  - 后续再切换 integrated-v1 中的本地能力。

### 6.4 未来迁移顺序

- [ ] 从 XiaoZhi Server 日志和源码中整理协议行为。
- [ ] 抽出 OTA 响应最小实现。
- [ ] 实现 WebSocket hello/listen 基础握手。
- [ ] 实现文本级调试链路，不先处理完整音频。
- [ ] 接入 Opus 音频收发。
- [ ] 接入 ASR。
- [ ] 接入 Buddy Core。
- [ ] 接入 TTS。
- [ ] 和 XiaoZhi Server 做并行对比测试。
- [ ] 稳定后再替换 XiaoZhi Server。

### 6.5 阶段 C 启动条件

只有当以下条件满足后，才开始执行阶段 C：

- [ ] 阶段 A demo 已经可以稳定复现。
- [ ] 阶段 B Buddy Core 的 profile/persona/memory 基本稳定。
- [ ] 已经收集足够 XiaoZhi 协议日志。
- [ ] 继续兼容现有 ESP32 小智固件的前提没有被推翻。
- [ ] 明确 ASR/TTS 第一版使用本地还是外部服务。

## 7. 风险与处理

### 7.1 当前命名混乱

代码目录仍叫 `buddy_brain`，但对外我们已经叫 `Buddy Core`。

处理方式：

- 短期：文档说明 Buddy Core 是从 Buddy Brain 演进来的核心服务。
- 中期：增加兼容入口或包别名。
- 长期：再考虑重命名 Python package，避免在当前阶段引入大范围改动。

### 7.2 XiaoZhi Server 仍是外部依赖

当前第一步只是替换业务大脑，不是完全替换服务器。

处理方式：

- 汇报时明确说：XiaoZhi Server 当前作为协议层保留。
- 不把第一步描述成“已经完成自研服务器”。
- 阶段 C 再处理完整替换。

### 7.3 局域网 IP 变化

换 WiFi 后 LAN IP 会变化，OTA URL 也要变化。

处理方式：

- 脚本自动检测 LAN IP。
- 文档保留 `-HostIp` 手动覆盖方案。
- Demo 前固定同一 WiFi。

### 7.4 Windows 日志编码问题

部分 XiaoZhi 日志在 PowerShell 中可能显示乱码。

处理方式：

- 不把乱码当作链路失败。
- 通过关键英文、端口、device-id、时间戳确认链路。
- 后续可以单独整理日志编码。

### 7.5 XiaoZhi runtime patch 被覆盖

如果 `.run` 目录被删除、重新下载或手动覆盖，`device-id` 转发补丁可能丢失。

处理方式：

- demo 前运行状态检查，确认 `forward_device_metadata` 和 provider patch 存在。
- 重新运行 `setup_xiaozhi_server.ps1` 应能恢复补丁。
- 把补丁验证写入硬件测试 runbook。

### 7.6 Demo 数据误删

memory reset 或重新渲染配置时，可能误删真实硬件设备的记忆或覆盖可用配置。

处理方式：

- demo 前备份 SQLite 和 XiaoZhi config。
- reset 操作默认只作用于当前选中的 `device-id`。
- 文档明确区分 debug 设备和真实 ESP32 设备。

## 8. 推荐执行顺序

1. 完成阶段 A 的启动、检查、日志和文档固化。
2. 跑一遍完整硬件 demo，记录真实测试结果。
3. 完成阶段 B 的 device/profile/persona/memory 增强。
4. 再跑一遍双设备模拟测试和真实硬件测试。
5. 更新汇报材料。
6. 等阶段 A/B 稳定后，再决定是否启动阶段 C。

## 9. 最终交付物

- [ ] 稳定 demo 启动文档。
- [ ] 硬件测试 runbook。
- [ ] Buddy Core 与 Buddy Brain 关系说明。
- [ ] 系统架构图。
- [ ] Buddy Core 配置说明。
- [ ] Memory 面板说明。
- [ ] 自动化测试。
- [ ] 第三阶段 Buddy Device Gateway 路线图。
