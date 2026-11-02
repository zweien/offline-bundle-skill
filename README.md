# offline-bundle-skill

> 一个 zcode / Claude Code skill，用于在**联网机离线打包** zcode skill 的依赖（pip / npm / playwright / 外部 exe）+ skill 本体，以及 **MCP server（http 配置直达 / npm stdio 整树）**，拷进**无网内网机**一键安装。

专为「内网（无互联网）+ 自有大模型」环境设计。把"离线准备依赖"这件反复做的事，固化成 **一份清单（manifest）+ 两个脚本**。

中文文档 / Chinese docs. This skill targets Windows intranet + Python 3.x + Node.

---

## 解决什么问题

在内网用 zcode 的 skill（docx / pdf / ppt-master 等文档处理，或任何开源 skill），需要预先在联网机把所有依赖离线准备好，整体拷进内网安装；内网要用 MCP server（如 NocoDB）时同样面临"依赖怎么进去、配置怎么写"的问题。这个"打包 → 拷贝 → 安装"的工作流会反复发生、且需求持续增长。

本 skill 把它固化成可复用、可扩展的流程：**清单是产品，pack.py / install.bat 是执行器，AI 分析方法是产线**。加新 skill 的成本极低——写一份新 manifest，跑一次 `pack.py add`；加 MCP server 写一份 MCP 清单，跑一次 `pack.py mcp`。

## 工作流

```
联网机（打包）                         内网机（安装）
  │                                      │
  ├─ AI 分析 skill → manifest.json       │
  ├─ python pack.py add ...              │
  ├─ python pack.py mcp ...  ← MCP 清单  │
  │     ↓ 产出 offline-bundle/           │
  │        wheelhouse/ skills/ mcp/      │ ──拷贝──►
  │        mcp-servers.json install.bat  │           install.bat → ~/.agents/skills/
  │                                      │                     + ~/.zcode/cli/config.json
```

- **接入新 skill**：AI 读 `references/how-to-analyze.md` 分析依赖 → 产出 manifest → 你确认 → `pack.py add`
- **追加新 skill（增量）**：pack.py 累加进同一个 bundle → 内网 `robocopy /MIR` → `install.bat`
- **补缺包**：改 manifest → 重跑 pack.py（去重，只补缺的）→ robocopy → `install.bat` 重跑
- **部署 MCP server**：写 MCP 清单 → `pack.py mcp` → `install.bat`（或 `_merge_mcp.py`）
  合并进 `~/.zcode/cli/config.json` 的 `mcp.servers`，重启 zcode

## 快速开始

**打包（联网机）：**
```cmd
python scripts\pack.py add <skill-dir> --manifest <manifest.json> --target "py:3.13,os:win,arch:amd64,node:20" --bundle <bundle-dir>
python scripts\pack.py mcp --manifest <mcp.json> --bundle <bundle-dir>
```

**安装（内网机）：**
```cmd
install.bat --dry-run      REM 自检
install.bat                REM 真装（含 MCP 配置合并，token 交互输入）
```

## 目录结构

```
offline-bundle-skill/
├── SKILL.md                          # 主文档：触发描述、工作流、命令速查
├── scripts/
│   ├── _schema.py                    # manifest 校验（纯函数，含 MCP manifest）
│   ├── _test_schema.py               # TDD 测试
│   ├── pack.py                       # 联网机打包器（add=skill，mcp=MCP server）
│   ├── install.bat                   # 内网机安装器
│   ├── _check_install.py             # install.bat 的自检助手
│   └── _merge_mcp.py                 # MCP 配置合并器（ask: 占位符解析 + config.json 合并）
├── templates/
│   ├── manifest.template.json        # 空 manifest 模板
│   └── mcp.template.json             # MCP manifest 模板（含 NocoDB 示例）
└── references/
    ├── how-to-analyze.md             # AI 逆向分析方法论（skill + MCP）
    ├── known-recipes.md              # docx/pdf/ppt-master/NocoDB MCP 现成 manifest
    └── gotchas.md                    # 实现陷阱库（修改脚本前必读）
```

## 关键设计

- **manifest 驱动**：一 skill 一清单，pack.py / install.bat 是不含 skill 知识的哑巴执行器。加新 skill 不改脚本，只写清单。
- **统一 wheelhouse 池**：pip wheel + npm 整树 node_modules 跨 skill 共享、自动去重。
- **交叉下载**：manifest 写死 `target.python`，`pack.py` 用 `pip download --python-version/--platform` 为目标环境拉对应 wheel（打包机不必和内网同版本）。
- **npm 整树方案**：npm 包带传递依赖整树落盘到 `node_modules/`，内网靠"拷贝 + NODE_PATH"使用，零 npm 零网络（裸 tgz 内网装不上）。
- **MCP 双路线**：`http` transport 零文件打包（服务已在内网跑着，如 NocoDB 内置 MCP）；
  `stdio-npm` 每 server 独立 node_modules 子树（ESM 不走 NODE_PATH，入口按绝对路径标准解析）。
  内网才有的 token/地址用 `ask:` 占位符，安装时交互填入，secret 不落 bundle。
- **manual 工具**：体大/来源不稳的 exe（LibreOffice）标 manual，只 warn 不阻断。

## 已验证的 skill / MCP 清单

`references/known-recipes.md` 内含现成 manifest：

| Skill | 技术栈 | 备注 |
|---|---|---|
| docx | Node.js (docx-js) | Word 生成 |
| pdf | Node.js (playwright) + Python | PDF 生成/转换 |
| ppt-master | Python (python-pptx 等) | PPT 生成 |
| minimax-docx | .NET 8 + NuGet | 评估后暂不接入（成本说明见 recipes） |
| NocoDB MCP（路线 A） | http（NocoDB ≥0.265.0 内置） | 零文件打包，x-api-key 认证 |
| NocoDB MCP（路线 B） | stdio-npm（zoyak-tech/nocodb-mcp） | v3 API，注意社区版许可限制（见 recipes） |

## License

MIT
