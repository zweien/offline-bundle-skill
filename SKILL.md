---
name: offline-bundle-skill
description: 当用户提到"离线准备/离线打包/内网部署 zcode skill 的依赖"，或要把某个 skill 的依赖弄到无网络环境使用，或需要在不联网的机器上安装 skill 及其依赖，或要离线部署 MCP server（如 NocoDB）时使用本 skill。覆盖场景：为 docx/pdf/Excel/PPT 等文档 skill 或任何开源 zcode skill 准备离线安装包；在内网机离线安装这些 skill；离线打包/配置 MCP server 并合并进 zcode 配置。
---

# offline-bundle-skill

为 zcode skill 离线准备依赖 + skill 本体，并支持 MCP server 的离线打包与配置合并。清单（manifest）是产品，pack.py/install.bat 是执行器，AI 分析方法是产线。

## 何时使用

- 用户要把某个 skill 部署到无网络的内网
- 用户要"离线打包 / 离线准备依赖"
- 新接入一个开源 skill，需要它的依赖清单
- 用户要在内网用 MCP server（zcode 配置里的 `mcp.servers`），如 NocoDB

## 整体流程

```
联网机                          内网机
  │                               │
  ├─ AI 分析 skill → manifest     │
  ├─ python pack.py add ...       │
  ├─ python pack.py mcp ...  ← MCP 清单（可单独、可叠加）
  │     ↓ 产出 offline-bundle/    │
  │           含 wheelhouse/      │ ──拷贝──►
  │           skills/ mcp/        │           install.bat → ~/.agents/skills/
  │           mcp-servers.json    │                     + ~/.zcode/cli/config.json
  │           install.bat         │                       (mcp.servers 合并)
```

## 命令速查

**打包（联网机）：**
```cmd
python "%~dp0scripts\pack.py" add <skill-dir> --manifest <manifest.json> [--target "py:3.12,os:win,arch:amd64,node:20"] [--bundle <bundle-dir>]
python "%~dp0scripts\pack.py" mcp --manifest <mcp.json> [--bundle <bundle-dir>]
```

**安装（内网机）：**
```cmd
install.bat --bundle <bundle-dir> [--dry-run] [--skill <name>]
REM MCP 单独安装（不走 install.bat 时）：
python _merge_mcp.py <bundle-dir> [--dry-run] [--set NAME=VALUE ...] [--no-prompt]
```

## 工作流（详见 references/）

1. **接入新 skill**：AI 读 `references/how-to-analyze.md` 分析依赖 → 产出 manifest → 你确认 → 跑 pack.py add
2. **追加新 skill（增量）**：pack.py 累加进同一个 bundle → 内网 robocopy /MIR → install.bat
3. **补缺包**：改 manifest → 重跑 pack.py（去重只补缺）→ robocopy → install.bat 重跑
4. **部署 MCP server**：按 `templates/mcp.template.json` 写 MCP 清单 → 跑 pack.py mcp →
   install.bat（或 `_merge_mcp.py`）把配置合并进 `~/.zcode/cli/config.json`，重启 zcode

## 关键概念

- **manifest.json**：一 skill 一清单，唯一输入。schema 见 `templates/manifest.template.json`。
- **MCP manifest**：`pack.py mcp` 的输入（`templates/mcp.template.json`）。两种 transport：
  - `http`：server 已在内网跑着（如 NocoDB ≥0.265.0 内置 MCP）→ **零文件打包**，只生成配置片段；
  - `stdio-npm`：独立 npm MCP server → 整树打包到 `bundle/mcp/<name>/`，
    **独立子树而非共享 wheelhouse**（配置按绝对路径引用入口，Node 标准 upward 解析依赖，
    ESM 也能解析——ESM 不走 NODE_PATH，见 gotchas E1）。
  - **ask: 占位符**：内网才有的值（NocoDB token 等）写成 `ask:VAR`，安装时由
    `_merge_mcp.py` 交互填入或 `--set` 传入，**secret 永不落 bundle**。
  - zcode 的 MCP 配置 schema 严格（未知键→整条丢弃）且不展开 `${...}`，
    片段只用规范字段 + 绝对路径（gotchas E2）。
- **target 环境**：manifest 强制记录，pack.py 据此交叉下载。优先级：`--target` > manifest.target > 探测本机。
- **wheelhouse 池**：跨 skill 共享 pip/npm 文件池。
  - pip：`.whl` 文件名天然去重。
  - npm：**整棵依赖树**落盘到 `wheelhouse/npm/node_modules/`（不是裸 tgz）。
    npm 包有传递依赖，裸 tgz 内网 `npm install -g` 会联网失败，所以必须整树安装，
    内网靠"拷 node_modules + NODE_PATH"使用，零 npm 零网络。
- **manual 项**：体大/不稳的 exe（libreoffice），只 warn 不阻断。

详见 `references/how-to-analyze.md`（分析方法）、`references/known-recipes.md`（docx/pdf/NocoDB MCP 现成清单）、
`references/gotchas.md`（**实现陷阱库——修改脚本前必读**）。

## 给维护者：修改脚本前

如果你要改 `pack.py` / `install.bat` / `_check_install.py` / `_merge_mcp.py`，或给本 skill 加功能，
**先读 `references/gotchas.md`**。它记录了开发中真实踩过的 batch 引号/括号陷阱、
pip dry-run 跨版本误判、URL 注释误删、ESM/NODE_PATH 等问题。重蹈这些覆辙会浪费大量调试时间。

## 验收状态（开发机）

以下在联网开发机（Python 3.14，为目标 cp313/win_amd64 交叉下载）验证通过：
- `pack.py add docx/pdf` 端到端打包（pip/npm/playwright/tools/skill 本体）
- **npm 整树方案**：docx/image-size/pdf-lib/playwright 连传递依赖落盘到共享
  `node_modules/`（28 包），内网靠"拷贝 + NODE_PATH"使用，不调 npm install
- wheelhouse 跨 skill 去重（reportlab 只 1 份）
- manifest-index 累加（docx + pdf 共存，target=3.13）
- playwright chromium 下载到 pw-browser/
- `install.bat` 真实安装：pip 装、npm node_modules 拷全局、skill 落盘 `~/.agents/skills/`、
  **重装备份用 `move /Y`（ren 会在同名备份已存在时卡死）**
- **内网实跑通过**（Python 3.13.9 + Anaconda）：install.bat 全流程完成，skill 装入

MCP 支持（`pack.py mcp`，开发机验证）：
- **http 路线**（NocoDB 内置 MCP 清单）：零下载打包，片段只含规范字段，MCP-only bundle
  的 manifest-index 正确创建
- **stdio 路线**（`nocodb-mcp`，ESM 包）：npm 整树 92 包装进 `bundle/mcp/<name>/`，bin
  自动解析到 `dist/index-stdio.js`
- **MCP initialize 握手实测通过**：按合并产物里的 command/args/env 从安装子树拉起
  server，19 组工具注册成功——独立子树方案下 ESM 依赖解析零 NODE_PATH
- `_merge_mcp.py`：`--set` 非交互、管道 stdin 提示、`--no-prompt` 跳过、外键保留
  （hooks/plugins/其他 server 原样）、config 与树双备份、幂等重跑
- `install.bat --dry-run` 含 MCP 自检；`-test` 模式对入口跑 `node --check`
- 顺手修复的**原版潜伏 bug**：① `shift` 污染 `%~dp0`（gotchas A6，从非脚本目录带参调用
  必炸）；② 无 skill 名时 `-test` 落 argv[2] 不被识别；③ GBK 管道/控制台下符号输出崩溃；
  ④ Windows `getpass` 在非 tty stdin 下挂死

**内网部署要点（target 必须匹配内网 Python 版本）**：
- bundle 的 pip wheel 按 target.python 的 cp 标签下载（cp312 ≠ cp313，装不上就换版本重打）
- 内网跑 `install.bat --dry-run` 先自检；npm 装完**新开终端**让 NODE_PATH 生效
