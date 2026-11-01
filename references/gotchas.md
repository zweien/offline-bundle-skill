# Gotchas — 实现中踩过的坑（维护者必读）

本文件记录 offline-bundle-skill 开发过程中**真实遇到过、调试过、已修复**的陷阱。
当你要修改 `pack.py` / `install.bat` / `_check_install.py`，或为这个 skill 新增功能时，
先读这里——能避免重蹈覆辙。

每条都注明：**现象**、**根因**、**当前代码怎么处理的**、**未来要注意什么**。

---

## 类别 A：Windows batch（.bat）陷阱

这些是 install.bat（以及任何未来新增的 .bat 脚本）里反复出现的坑。batch 的解析模型
和直觉差很远，下面 4 个是实测命中的。

### A1. echo 内容里的字面括号会破坏 if/for 块

**现象**：install.bat 跑到某个 `if (...)` 大块时报 `此时不应有 .。`（". was not expected"），
整个脚本崩溃退出，但看不出哪一行错。

**根因**：batch 在解析 `if ... (...)` 或 `for ... (...)` 的**括号块**时，会扫描块内的 `(`/`)`
来定边界。如果块内某行 echo 的文本含字面括号，例如：
```
if "!CHECKFAIL!"=="1" (
    echo   Aborting (run with --dry-run to see details).   ← 这个 ( ) 会被当成块结束符
)
```
cmd 把 echo 里的 `)` 当成 if 块的结束括号，块的边界全乱，后续解析雪崩。

**当前代码处理**：
- 块内 echo 一律不含未转义括号。需要括号的地方改成无括号措辞
  （`Aborting. Run with --dry-run to see details.`）或转义为 `^(`/`^)`。
- 顶层独立 echo（不在括号块内）可以含括号，安全。

**未来注意**：写任何 `if (...)` / `for (...)` 多行块时，**检查块内每个 echo** 是否含 `(`/`)`。
含就转义 `^(`/`^)` 或改措辞。这是 batch 里最高频的崩溃源。

### A2. `node -e "复杂JS"` 的引号会被 cmd 吞掉

**现象**：在 .bat 里写 `node -e "var d=require('docx'); ..."`，node 报
`Unterminated string constant` / `SyntaxError: Invalid or unexpected token`，
收到的脚本断在 `"var`。

**根因**：cmd 对双引号的传递很脆弱，复杂的嵌套引号（外层 `"` 包 JS，内层 `'`）经过 cmd
解析层后引号丢失或错位。同样的 JS 在 bash 里直接跑没问题，但裹进 .bat 就崩。

**当前代码处理**：install-global 类的验证逻辑**不写 `node -e`**，改为：
1. 用 `> file echo ...` 把 JS 语句写进临时 `.js` 文件
2. `node file.js` 跑它
3. 删掉临时文件

引号问题彻底消除。

**未来注意**：在 .bat 里调 node/python 执行多语句脚本时，**优先写临时文件再执行**，
别用 `-e "长脚本"`。单条简单命令（如 `node -e "console.log(1)"`）勉强可用，但凡含
嵌套引号/括号/逻辑运算符，就写文件。

### A3. `!==` 的 `!` 触发 batch 延迟展开

**现象**：在 .bat 里用 `>> file echo if(typeof x!=='function'){...}` 写 JS，
生成的文件里变成 `if(typeof x=='function'`——`!==` 被吞成了 `==`，逻辑反转。

**根因**：`setlocal enabledelayedexpansion` 下，`!` 是延迟变量展开的触发符。
JS 的 `!==` 里的 `!` 被当成变量引用开头，`!==` 解析后变成空或怪值。

**当前代码处理**：生成的 JS 避开 `!==`，改用 `===` 反向判断：
```
var ok = (typeof d.Document === 'function') && (typeof d.Packer === 'function');
if (ok === false) { process.exit(1); }
```

**未来注意**：凡是 .bat 生成或内嵌的代码（JS/Python）里要写 `!=`/`!==`，**改用 `==`/`===`
反向逻辑**，或把 `!` 转义为 `^!`（但很易错，不推荐）。同理，JS 的 `&&`/`||` 在 .bat echo 里
要转义为 `^&^&`/`^|^|`。

### A4. pip / npm 不支持 shell glob 通配符

**现象**：install.bat 写 `pip install --find-links <dir> "<dir>\*.whl"`，
pip 报 `Invalid wheel filename (wrong number of parts): '*'`；
`npm install -g "<dir>\*.tgz"` 同样不展开。

**根因**：cmd 的 `*.whl` **不会**像 shell 那样展开成文件列表传给程序——它把 `*.whl` 当
字面参数。pip/npm 收到字面 `*.whl` 就当成一个非法文件名。

**当前代码处理**：
- pip：用 `for /f` + python one-liner 从 wheel 文件名解析出包名列表，拼成 `pkg1 pkg2 ...` 传给
  `pip install --find-links <dir> pkg1 pkg2 ...`。
- npm：用 `for %%F in (<dir>\*.tgz)`（batch 的 for **会**展开 glob）拼出显式文件路径列表
  `path1.tgz path2.tgz`，传给 `npm install -g path1.tgz path2.tgz`。

**未来注意**：给 pip/npm 传多个文件时，**先在 batch 里用 `for` 展开成显式列表**再传，
别指望 `*.glob` 直接传给程序。注意区分：cmd 的 `for %%F in (*.x)` 会展开，但 `<dir>\*.x`
作为**命令参数**直接传不会展开。

### A5. `ren` 重命名目录在目标已存在时失败；改用 `move`

**现象**：install.bat 的 skill 落盘阶段，备份已存在的 skill 时报
`存在一个重名文件，或是找不到文件。`，然后卡在 `installing skill xxx` 不动了。

**根因**：`ren "!DEST!" "xxx.bak.20260627"` 有两个坑：
1. `ren` 的第二个参数必须是**纯文件名**（不含路径），且目标不能已存在。如果同名备份
   （如上次跑残留的 `xxx.bak.20260627`）已存在，`ren` 直接失败。
2. `ren` 失败后没有 errorlevel 分支，install.bat 继续走到 `xcopy`，但旧目录还在原地，
   `xcopy /i` 可能因冲突卡住或行为异常。

**当前代码处理**：备份改用 `move /Y "!DEST!" "!BAKDEST!"`（完整路径 + `/Y` 确认覆盖），
并在 move 前先 `rmdir` 同名备份、move 失败时 fallback 到 `rmdir` 旧目录。这样无论备份
是否已存在、旧目录是否被占用，新 skill 都能装进去。

**未来注意**：batch 里重命名/移动目录，**用 `move /Y` 而非 `ren`**。`move` 接受完整
路径、能覆盖、错误信息明确。`ren` 的"纯名 + 不能存在"约束在重试/覆盖场景下是地雷。

### A6. `shift` 会把参数移进 `%0`，解析循环之后再读 `%~dp0` 得到的是错的

**现象**：install.bat 里 `python "%~dp0_check_install.py"` 报
`can't open file 'C:\...\mcp-e2e\_check_install.py'`——`%~dp0` 解析成了**调用者所在目录**
而非脚本所在目录。且只在"从别的目录、以相对路径调用 + 带 `--bundle`/`--skill` 参数"时
出现；在脚本目录里直接跑一切正常（所以内网实跑当时没暴露）。

**根因**：cmd 的 `shift` **会把 %1 移入 %0**（实测：`call x.bat aaa bbb` 后第一次 shift
→ `%0=aaa`，第二次 → `%0=bbb`；不像文档暗示的 %0 不变）。install.bat 的 `:parse` 参数
循环 shift 消耗完参数后，`%0` 已变成某个**无目录部分的字符串**（如 `bundle-stdio` 或空），
此时再展开 `%~dp0` 就按 CWD 解析 → 得到调用者目录。

**当前代码处理**：`setlocal` 后、进入 `:parse` 循环**之前**立刻快照
`set "HERE=%~dp0"`，之后所有对脚本目录的引用一律用 `%HERE%`（_check_install.py、
_merge_mcp.py 的调用路径）。

**未来注意**：任何带参数解析循环（shift）的 batch，**必须在第一次 shift 前快照
`%~dp0`/%~f0**；循环后出现的 `%~dp0` 一律视为不可信。

---

## 类别 B：pip / 交叉下载陷阱

### B1. `pip install --dry-run` 会用当前解释器拒绝目标平台的 wheel

**现象**：`_check_install.py` 用 `pip install --dry-run --no-index --find-links <dir>` 做
自检，内网 bundle 里明明有 `contourpy-1.3.3-cp312-win_amd64.whl`，却报
`Could not find a version that satisfies the requirement contourpy`。

**根因**：`pip --dry-run` 用**当前运行 pip 的解释器**（开发机是 Python 3.14）去匹配 wheel
标签。bundle 里的 wheel 是 cp312 的，3.14 的 pip 认为 cp312 wheel 不兼容当前解释器，拒绝。
这跟"包在不在池里"无关，是版本标签不匹配。

**当前代码处理**：`_check_install.py` **不再用 `pip --dry-run`**，改为**直接检查 wheel
文件名标签**：解析每个 wheel 名 `{dist}-{ver}-{pythontag}-{abitag}-{platformtag}.whl`，
判断 `pythontag` 是否为 `py3`/`py2.py3`（纯 Python，跨版本）或等于目标 `cp312`、
`platformtag` 含 `win_amd64`。纯文件检查，不依赖当前解释器。

**未来注意**：任何"校验离线 wheel 是否匹配目标环境"的逻辑，**用文件名标签判断**，
别用 `pip --dry-run`（它绑死当前解释器）。目标 Python 版本可能和校验机器不同。

### B2. `pip download` 交叉下载用 `--only-binary :all:` 是硬约束

**现象**：某包对目标 Python 版本没有预编译 wheel（只有 sdist 源码包），`pip download
--only-binary :all:` 直接失败。

**根因**：内网机没有编译器（无 MSVC/无 `gcc`），sdist 装不上。所以打包阶段就必须只要 wheel，
`--only-binary :all:` 强制如此。这是设计决策，不是 bug。

**当前代码处理**：pack.py 的 `download_pip` 用 `--only-binary :all:`，失败时打印明确建议
（"某包无此环境的 wheel，可降级 Python 版本或换包"）。

**未来注意**：如果遇到某包真的只有 sdist，**别去掉 `--only-binary` 去拉 sdist**（内网装不上）。
正确做法：在 manifest 里给该包 pin 一个有 wheel 的版本，或换等价纯 Python 包。

### B3. npm 裸 tgz 不含传递依赖，内网 `npm install -g` 会联网失败

**现象**：install.bat 跑 `npm install -g docx-9.7.1.tgz`，内网报：
```
npm error request to https://registry.npmjs.org/@types%2fnode failed,
reason: getaddrinfo ENOENT registry.npmjs.org
```
即使内网有 node，也装不上。

**根因**：`npm pack docx` 只打包 docx 自己，**不含它的传递依赖**（docx 的 dependencies
里有 hash.js/jszip/nanoid/xml/xml-js/@types/node）。`npm install -g docx.tgz` 时 npm 会去
registry 解析并拉取这些依赖——内网无网就失败。pip 的 wheel 有传递依赖解析
（`--find-links` + resolver），但 npm 的 tgz 没有等价机制。

**当前代码处理**：`download_npm` 改为用 `npm install <pkg> --omit=dev`（而非 `npm pack`），
在联网机把**整棵依赖树**落盘到 `wheelhouse/npm/node_modules/`。install.bat 不再调
`npm install -g`，而是**拷贝这个 node_modules 到全局路径**（`%ProgramData%\node-global-libs`）
+ `setx NODE_PATH` 指向它。这样内网零 npm、零网络，require 即用。

**未来注意**：npm 包**永远要整树安装**，别用裸 tgz。新增 npm 依赖走 `download_npm` 即可
（已改对）。如果看到 install.bat 里出现 `npm install -g <*.tgz>`，那就是旧逻辑的残留，必须改回
"拷 node_modules + NODE_PATH"。

### B4. 检查导入名要从 wheel 元数据读，不能从文件名猜

**现象**：`_check_install.py` 的 import 测试报一堆假阳性失败：
```
!! could not import fonttools        ← 真名是 fontTools（大写 F）
!! could not import python-docx      ← 真名是 docx
!! could not import pillow           ← 真名是 PIL
!! could not import pdfminer-six     ← 真名是 pdfminer
!! require('image') failed           ← 真名是 image-size
!! require('pdf') failed             ← 真名是 pdf-lib
```
包其实都装好了，只是检查代码用"文件名推导导入名"猜错了。

**根因**：pip 包名（wheel 文件名）和 Python 导入名经常不一致（`Pillow`→`PIL`、
`python-docx`→`docx`、`pdfminer.six`→`pdfminer`）；npm 同理（`image-size` 包名 ≠
`require('image-size')`，但 `pdf-lib` 的子包叫 `@pdf-lib/*`）。从文件名 `replace('_','-')`
去猜导入名，命中率很低。

**当前代码处理**：
- pip：读每个 wheel 的 `*.dist-info/top_level.txt`（wheel 自带的、权威的顶层模块清单），
  按它列的模块名去 import。
- npm：读 `node_modules/<pkg>/package.json` 的 `name` 字段，按真实包名 require。

**未来注意**：任何"验证某包能否 import"的逻辑，**从包自带的元数据拿导入名**，
别从文件名猜。Python 看 top_level.txt，Node 看 package.json 的 name。

---

## 类别 C：manifest / JSON 处理陷阱

### C1. URL 里的 `//` 不能当注释剥离

**现象**：manifest 含 `"url_template": "https://github.com/..."`，pack.py 报
`Unterminated string starting at...`，URL 被截断成 `https:`。

**根因**：初版 `_strip_json_comments` 把每行第一个 `//` 之后都当注释删掉——但 URL 里的
`https://` 的 `//` 被误判为注释起点，整个 URL 被截。

**当前代码处理**：注释剥离**只删整行 `//` 开头**的行（`line.lstrip().startswith("//")`），
绝不删行内 `//`。而且模板用的是合法 JSON key `"//": "说明"`，根本不需要注释剥离——
直接 `json.loads`，失败才回退到整行注释剥离。

**未来注意**：JSON 里**不要支持行内 `//` 注释**（JSON 标准本就不支持）。URL、正则、路径
都可能含 `//`。需要注释就用 `"//": "..."` 这种合法 key 形式。

---

## 类别 D：finalize / bundle 自包含陷阱

### D1. install.bat 依赖的辅助文件要一并拷进 bundle

**现象**：内网机跑 bundle 根的 `install.bat`，报
`python: can't open file '_check_install.py': No such file or directory`。

**根因**：install.bat 调用同目录的 `_check_install.py`（batch 不擅长解析 JSON/dry-run，
外包给 python）。但初版 `finalize_bundle` 只把 `install.bat` 拷进 bundle，漏了 `_check_install.py`。

**当前代码处理**：`finalize_bundle` 把 `install.bat` **和** `_check_install.py` 都拷进
bundle 根。

**未来注意**：bundle 必须**自包含**——install.bat 跑起来依赖的**所有**文件（脚本、配置、
辅助 py）都要在 `finalize_bundle` 里显式拷进去。新增任何 install.bat 的依赖文件，同步更新
`finalize_bundle` 的拷贝列表。

---

## 类别 E：MCP server 离线部署陷阱

### E1. ESM 包的 import 不走 NODE_PATH，stdio MCP server 必须用独立子树

**现象**：如果把 stdio MCP server（如 `nocodb-mcp`，`"type": "module"` 的 ESM 包）装进
共享 `wheelhouse/npm/node_modules/`，内网拷到 `%ProgramData%\node-global-libs` 后，
配置里 `node <该包入口>` 启动报 `ERR_MODULE_NOT_FOUND: Cannot find package
'@modelcontextprotocol/sdk'`，虽然 NODE_PATH 里明明有它。

**根因**：skill 脚本的 `require()` 是 CJS 解析，找不到本地 node_modules 时会退回查
NODE_PATH——所以共享池 + NODE_PATH 对 CJS 有效。但 **ESM 的 bare import
（`import ... from '@modelcontextprotocol/sdk'`）完全忽略 NODE_PATH**，只做标准目录向上
查找（入口所在目录逐级找 `node_modules/`）。MCP server 包大量是 ESM，共享池方案对它们
天然失效。

**当前代码处理**：`pack.py mcp`（`pack_mcp_stdio`）给每个 stdio server 建**独立子树**
`bundle/mcp/<name>/package.json + node_modules/`（含整棵传递依赖树）。zcode 配置按
绝对路径引用入口 `<安装根>/<name>/node_modules/<pkg>/<bin>`，入口向上一步就是本 server
的 `node_modules/`，CJS/ESM 都能标准解析，与 NODE_PATH 彻底无关。

**未来注意**：任何"按绝对路径启动入口脚本"的 node 程序（MCP server、工具脚本）都别依赖
NODE_PATH——只有 CJS require 认它。要么独立子树，要么把入口放进能向上找到依赖的目录。

### E2. zcode MCP 配置 schema 严格且不展开 `${...}` 模板

**现象**：手工往 `~/.zcode/cli/config.json` 的 `mcp.servers` 里塞了带自定义键（如
`description`）或 `command: ["npx", "-y", "x"]`（数组）的条目，server 在
Settings → MCP 里**整个不出现**或被丢弃。

**根因**：zcode 配置文件的 MCP schema 是**严格校验**：未知键→该 server 被丢弃；
`type` 与字段不匹配（`command`/`url` 二选一）、`command` 必须是字符串（args 才是数组）
都会静默失败。且配置文件里的 server **不展开 `${...}` 模板变量**（那是 plugin 专属能力），
模板会原样传给进程。

**当前代码处理**：`build_mcp_record` 渲染片段时**只用规范字段**
（`type/url/headers/command/args/env/timeoutMs`），stdio 的 `args` 用
`{{INSTALL_DIR}}` 自有占位符，由 `_merge_mcp.py` 在内网展开成绝对路径后再写入
config——不依赖 zcode 展开任何东西。

**未来注意**：改片段渲染逻辑时，**别引入任何非规范键**；需要变量替换就用自己的占位符
在写入前展开。

### E3. 内网才有的 secret（token）不能在打包时写死

**现象**：NocoDB 的 MCP token 是在内网 NocoDB GUI 里创建的，联网打包时根本不存在；
即使知道，把 token 写进 bundle 拷来拷去也会泄漏。

**根因**：离线打包发生在联网机、安装发生在内网机，两台机器的"已知信息"不同——认证类
值（MCP token、API token）只能在内网安装时产生/输入。

**当前代码处理**：manifest 里任何字符串值可写 `ask:VAR_NAME` 占位符（headers/env 里的
值、甚至 url 子串）。占位符随片段存进 bundle（无 secret 值），`_merge_mcp.py` 在内网
交互提示输入（名字含 TOKEN/SECRET/PASSWORD/KEY 的用隐藏输入）或 `--set VAR=值`
非交互传入，写入 config 前才替换。

**未来注意**：新增依赖内网信息的字段时，沿用 `ask:` 机制；**任何 secret 不落 bundle**。

### E4. http 路线的 URL/tokenId 是内网 GUI 生成的，打包机填不了

**现象**：NocoDB 内置 MCP 的 url 是 `http://<内网主机>/api/v2/mcp/<mcpTokenId>`，
其中 `mcpTokenId` 是内网 GUI 创建 token 时才有的 id；联网机打包时这两段都是未知。

**根因**：同 E3——server 地址和 token 标识都是内网侧信息。

**当前代码处理**：模板/配方里把未知段写成 `ask:` 占位符或 `<占位>` 提示；
`_merge_mcp.py` 同样支持在 url 子串里替换 `ask:`。另注意：该端点是**无状态
streamable HTTP，只收 POST**，客户端 GET 探测收到 405 是正常的，不是配置错误。

**未来注意**：分析新 MCP server 时，先分清"打包机可知"（npm 包名、公有 url）与
"内网才知"（主机地址、token），后者一律 `ask:`。
