# 纯便携化改造方案（去 pyappify）

> 状态：设计草案 **v2（已按仓库与 `.venv` 中 ok-script 2.0.2 / pyappify 1.0.13 源码逐条核实并修订）**，实施中（见 §12 进度）。
> 目标：把发布形态从「pyappify 启动器 + 双便携包」改为「可重定位 Python + 微型入口 exe + 应用内自更新」，做到**解压目录之外零系统写入**，且**只需打一个包**。
>
> v2 相对 v1 的修订集中在：更新源可切的前提（§3.2）、git 命令序列（§5.4 新增 seed commit，`checkout -f` 必需）、等待旧进程退出、依赖变化判定与 pip 回滚、`version.txt` 不得进 git、启动方式对 `sys.path`/cwd 的约束（§4.1），以及 §7 对 ok-script 降级行为的更正。

## 1. 目标

1. 便携包除解压目录外不写任何系统位置（无开始菜单/注册表/Defender 排除）。
2. 保留 git tag 语义的应用内自更新（查版本 → 升级/降级 → 依赖变更自动 pip）。
3. 更新源（GitHub / CNB 镜像）可在应用内切换，**不再需要打两种包**（前提见 §3.2）。
4. 简化 CI：去掉 pyappify-action 的 Tauri 编译（约 12 分钟）。

## 2. 现状 vs 目标

| 维度 | 现状（pyappify） | 目标 |
|---|---|---|
| 入口 | pyappify Tauri 启动器 exe | 微型入口 exe（仅 `pythonw main.py` + UAC manifest + 图标） |
| Python | 启动器第一跑 `setup` 装 | `python-build-standalone`（可重定位）随包分发 |
| 更新 | 启动器 git fetch/checkout + pip | 应用内发起 + `update.py` bootstrap |
| 更新源 | 打包时经 profile 固化（→ 必须双包） | 运行时配置 `configs/update.json`（→ 单包） |
| 系统写入 | 开始菜单 `.lnk`（Tauri 启动器行为，本仓库不可核实）+ 框架「计划任务」页（`schtasks`，见 §7.3） | 无（需保持任务 `support_schedule_task=False`） |
| 版本号 | `PYAPPIFY_APP_VERSION` 环境变量注入 | `version.txt`（build 写、update.py 维护，**不入 git**） |

## 3. 核心结论

### 3.1 「更新 git 路径可自定义」
git 源从「打包时固化的 profile」变成「应用读的普通配置项」，UI 给一个更新源下拉（自动 / GitHub / CNB 镜像 / 自定义）即可。技术上成立（`git remote set-url` + 重新 fetch）。

### 3.2 「回到单包、更新源可切」**有前提**（v1 结论需修正）
已核实：GitHub 仓库**不含** `ok/`、`pyappify/`（`git ls-files ok` = 0 条），`requirements.txt` 也没被裁剪 —— 内联只发生在 CI 工作区，随后由 `deploy.txt` 同步进 **CNB 镜像**（`inline_ok_requirements` 会自动把 `ok`/`pyappify` 追加进 `deploy.txt`）。因此：

- **CNB 镜像 = 自洽的「内联完整树」**；从它更新，`src/`、`assets/`、内联 `ok/`、`pyappify/`、`requirements.txt` 全部一致。
- **从 GitHub 更新 = 半新半旧的混合体**：`src/` 变新，内联 `ok/`/`pyappify/` 不变（框架永远不更新），`requirements.txt` 变回带 `ok-script==2.0.2`/`pyappify` 的版本 → 「依赖变了」每次命中，往 `site-packages` 装一份永远被遮蔽的 ok-script。

所以单包没问题（**包**只需一个），但「更新源随便切」必须先满足下列**任一**前提，否则 CI 只该产出走 CNB 的单包：

| 方案 | 做法 | 代价 |
|---|---|---|
| A（推荐） | CI 在 GitHub 侧也打一个「内联完整树」的 tag（把内联产物提交到一个发布分支，tag 指向它），GitHub/CNB 都能作为更新源 | GitHub 仓库出现内联代码，或需要一个发布分支/tag 规范 |
| B | 更新只走 CNB，`channel` 只提供「CNB / 自定义 URL」，GitHub 仅作下载与源码 | 「自动/ GitHub」选项取消，用户若 CNB 不可达只能重下包 |
| C | 放弃内联，`requirements.txt` 保留 `ok-script`/`pyappify`，框架随 pip 更新 | 失去「内联加速/离线可用」，回归 pip 依赖管理，改动面最大 |

> **决策（2026-09-10）：采用 C —— 取消内联，`requirements.txt` 保留 `ok-script`/`pyappify`，框架随 pip 更新。**
> 理由：C 是唯一让「双源可切」天然成立的方案（GitHub / CNB 树都自洽），且彻底消除「site-packages 一份 + 内联一份、其中一份被遮蔽」的隐患；A 要把内联产物提交进发布分支并引入 tag 语义问题，B 牺牲可切源。
> C 带来的新约定（必须遵守，见 §8 第 3 步与本页末）：
> 1. **框架升级 = bump `pyproject.toml` + 重新 `pip-compile` 出 `requirements.txt`**，并与 tag 一起提交；否则 tag 里的 lock 还是旧版本，用户界面上「已更新」了但框架没升级（静默）。
> 2. 更新链路多一跳 PyPI（仅当依赖指纹变化时），可用 `pip_index` 走国内镜像。
> 3. `inline_ok_requirements` 不再调用（它顺带的「改写 `src/config.py` 版本号」已由 `version.txt` 接管）。
> 实测确认 C 可行：`python-build-standalone`/NuGet 独立解释器装上 `requirements.txt` 后，`ok`/`pyappify` 均从包内 `Lib/site-packages` 导入，`src/` 的补丁链与 `og.app_path` 全部正常（见 §12）。

## 4. 目标目录布局（解压后）

```
ok-nikke/                      # 解压目录（即仓库根，便携）
├── ok-nikke.exe               # 微型入口：spawn python\pythonw.exe main.py（UAC + 图标）
├── python/                    # python-build-standalone 3.12，可重定位（含 pip）
│   ├── python.exe / pythonw.exe
│   └── Lib/site-packages/...  # 全部依赖（opencv/openvino/onnx/pyside6/…）
├── git/                       # MinGit（git/cmd/git.exe，随包预置；无需 PortableGit）
├── src/  assets/  icons/  i18n/
├── main.py  main_debug.py
├── update.py                  # 更新 bootstrap（零第三方依赖）
├── version.txt                # 版本号（build 写、update.py 维护；不入 git，见 §5.3）
├── version.txt.prev           # 上一版本（用于「已更新 vX → vY」提示；不入 git）
├── logs/update.log            # update.py 日志（logs/ 已 gitignore）
└── configs/
    ├── update.json            # 更新源 / pip 源 / 更新通道
    └── …（ok-script 其它配置）
```

- **不做 venv**：直接装进独立解释器自己的 `Lib/site-packages`，天然可挪（venv 的 `pyvenv.cfg` 绑绝对路径）。`ok-script`/`pyappify` 与其它依赖一样装在这里（方案 C，无内联目录）。
- **不带 `.git`**：代码已随包分发，首跑离线可用；首次更新时 `update.py` 在本地 `git init` + seed commit（§5.4）。
- **`git/` 用 MinGit 即可**（实测 37MB zip / 90MB 解压，含 `cmd/git.exe`），不必预置 PortableGit（56MB / 350MB+）；本项目不用 git-lfs、不需要 bash，MinGit 足够。`update.py` 的 `find_git_exe()` 首选 `<root>/git/cmd/git.exe` 正是这个布局。

### 4.1 启动方式约束（必须遵守，否则内联 `ok/` 静默失效）

已核实框架的路径解析全部基于 **cwd** 与 **`sys.argv[0]`**：

- `og.app_path = get_path_relative_to_exe()` → 取 `os.path.abspath(sys.argv[0])` 的目录（非 frozen 时）；
- `Config.config_file = get_relative_path(folder, ...)` → `os.getcwd()/configs/...`；
- `check_mutex()` 的互斥名、冲突时的 `kill_exe()` 都以 `os.getcwd()` 为基准。

因此入口 exe 必须：**cwd = exe 所在目录**、以「脚本路径」形式启动（`python\pythonw.exe main.py`，让 `sys.path[0]` = 包根）、不要用 `-m`、也不要把 cwd 设成 `python\`。否则 `import ok` 会落到 `python/Lib/site-packages` 里的另一份 ok-script/pyappify（永不更新），且 `configs/`、`screenshots/` 会写到别处 —— 属"看着能跑"的隐性故障。

## 5. 组件设计

### 5.1 入口 exe（微型，C + manifest）

职责只有：以自身目录为 cwd，`CreateProcess` 启动 `python\pythonw.exe main.py`，自带 UAC 提权与图标。

- 语言：**C**（单文件 100 余行，含中文注释）。备选 Go（可读性好、无需 windres，但 exe 大 100 倍且要 `go-winres` 之类的第三方工具才能嵌 manifest/图标）、C++（无额外收益）、Rust/Zig（多一个工具链）。**维护成本主要由「构建胶水 + 验证脚本」决定，而不是语言**：shim 逻辑十年不变，真正的坑是 manifest/图标嵌入与工具链差异（下面两条实测就是从这儿来的）。
- 构建脚本用 **Python**（`launcher/build.py`）：不依赖 shell 细节，MinGW/MSVC 自动探测、可单独跑。
- **本地/IDE 里跑 shell 命令与脚本统一用 `pwsh`（PowerShell 7）**：Windows PowerShell 5.1 会按 ANSI 读取无 BOM 的脚本与命令，含中文即乱码甚至语法报错（实测踩到三次：`.ps1`、`Set-Content`、含中文的清理命令）。**CI 不需要为此做任何特殊处理**——GitHub 托管 Windows runner 上 `run` 步骤的默认 shell 本来就是 `pwsh`（仅自托管且未装 PowerShell Core 时才回退到 5.1），workflow 里也刻意只用两版行为一致的写法（`[System.IO.File]::WriteAllText`、`ConvertTo-Json`、`Invoke-RestMethod`、`Expand-Archive`、外部 `tar`），不依赖输出编码差异。
- 实测两种工具链的 manifest 差异：
  - MinGW：gcc 的 `*endfile` spec 会自动链接它自带的 `default-manifest.o`（`asInvoker`，资源 ID 同样是 1），与我们的 `requireAdministrator` 冲突（`ld: .rsrc merge failure: multiple non-default manifests`）→ 解决：把 `launcher.manifest` 编译成同名 `default-manifest.o` 放进 `launcher/build-stamp/`，用 `-B` 让 spec 优先找到它，最终 exe 里只有唯一一份 manifest。
  - MSVC：`rc.exe` 把 `1 24 "launcher.manifest"` 直接编进资源即可（link.exe 不会自动加 manifest）。
  - **两种工具链都必须做成品校验**：`launcher/build.py` 链接后检查 exe 含 `requireAdministrator` 且**不含** `asInvoker`，否则直接报错退出——提权是 shim 存在的理由，绝不能静默产出不提权的 exe（MinGW 的冲突就是「两个 manifest 都在 exe 里」）。
- 实测体积：不带 manifest 22KB，带图标+manifest 150KB。
- UAC：资源文件加 manifest `requestedExecutionPolicy=requireAdministrator`。**必需** —— NIKKE 游戏进程以管理员运行，抓屏/模拟输入需同级权限；子进程继承提权，故应用内更新/重启不会再弹 UAC。
- 图标：`icons/icon.ico` 打进资源。
- spawn 细节：**不等待子进程、不持有句柄、无控制台窗口**（否则会拖住退出、闪黑框）；`GetModuleFileNameW` 取自身目录作为 cwd。
- 未签名时 UAC 弹「未知发布者」，后续可接代码签名。
- 限制（写入文档，避免误解）：**入口 exe 自身无法被 git 更新**（改 shim/manifest/图标必须重下整包）；`git`/`python` 目录同理。
- 降级路径：直接 `python\pythonw.exe main.py` 也能跑（不自动提权，ok 的 `restart_as_admin` 会用 `sys.executable`+argv 自助提权，只是 UAC 提示显示 `pythonw.exe`）。开发/排障用这个。

### 5.2 更新源配置 `configs/update.json`

```json
{
  "channel": "auto",                                   // auto | github | cnb | custom
  "custom_git_url": "",                                // 仅 channel=custom 时使用
  "pip_index": "",                                     // 空 = 用默认源；否则清华/阿里等镜像
  "update_method": "manual"                            // manual | auto（预留启动自检）
}
```

- **只存 `channel` + `custom_git_url`**，实际 git 地址由代码推导（默认值硬编码在 `update.py`，文件缺失/损坏也能跑），避免 v1 里 `channel` 与 `git_url` 双份状态不一致。
- `pip_index` 为空时**不要**拼 `-i ''`（`pip` 会报错），要条件拼接。
- 应用设置页提供「更新源」下拉：自动（按 locale）/ GitHub / CNB 镜像 / 自定义 URL。设置页与 `update.py` 读写同一份文件。

### 5.3 版本号 `version.txt`

- 构建时写当前 tag；`main.py`（或 `src/config.py`）读它填入 `config['version']`。
- 每次 `update.py` checkout 成功后改写为新 tag，并把旧值写入 `version.txt.prev`。
- **不得进 git、不得进 `deploy.txt`**：它由 build 与 update.py 共同维护，一旦被跟踪，update.py 改写后工作区即 dirty，下次 `checkout` 会撞「local changes would be overwritten」；也会与「checkout 覆盖仓库快照」互相打架。已加入 `.gitignore`，并由 `update.py` 写 `.git/info/exclude` 双保险。
- 已核实：`OK.__init__` 里 `pyappify.app_version` 为真才覆盖 `config['version']`（无环境变量时不覆盖），所以 `version.txt` 路线可行；同时建议**停用** `inline_ok_requirements` 对 `src/config.py` 的 `version = "..."` 改写，避免两个版本来源并存。
- 「已更新 vX → vY」提示需要旧值：读 `version.txt.prev`（v1 只写「读 version.txt 前后差」是缺实现的）。
- **读取时必须 lstrip BOM**：CI 里用 PowerShell `Set-Content -Encoding utf8` 写 `version.txt` 会带 BOM，不清理会让版本号变成 `"\ufeffvX"`，版本比较/更新提示全部失真（实测踩到，`src/config.py` 与 `update.py` 均已加固，并有单测覆盖）。

### 5.4 更新 bootstrap `update.py`（零依赖：只 import 标准库）

```text
输入: --target <tag>（必填） / --root（默认本文件目录） / --git-exe（默认 <root>/git/cmd/git.exe）
      / --python-exe（pip 用，默认 <root>/python/python.exe） / --pythonw-exe（重启用）
      / --wait-pid（旧进程 PID）/ --wait-timeout / --git-url / --pip-index
      / --no-pip / --force-pip / --pip-attempts / --pip-retry-delay
      / --no-relaunch / --dry-run / --list-tags（检查更新，输出远端 tag 的 JSON）
0. 若给了 --wait-pid：等旧进程真正退出（ctypes OpenProcess(SYNCHRONIZE)+WaitForSingleObject）。
   必须做：Windows 下 .pyd/.dll（opencv/PySide6/pywin32…）被占用时，checkout/pip 会随机失败。
1. 读 configs/update.json 解析 git_url / pip_index（缺失则用硬编码默认值）。
2. 写「更新中」标记 configs/.updating；把自己备份到 configs/.update_runner.py。
3. 【首次】无 .git → git init；向 .git/info/exclude 追加 version.txt / version.txt.prev /
   python / ok / git / configs / logs / __pycache__（防 seed 把这些提交进去）。
4. remote: 无 origin → git remote add origin <url>；有 → git remote set-url origin <url>。
   （v1 只写了 set-url，首跑会直接报错。）
5. 【首次】无 HEAD → seed commit：git add -A + git -c user.name=ok-nikke -c user.email=update@local
   commit -m "seed <当前版本>"。
   作用：把「包里的旧代码」变成 tracked 基线。否则首次 checkout 会因「未跟踪文件将被覆盖」直接失败，
   且**在新版本里被删除的文件永远清不掉**（已用 v0.1.0→v0.1.2 验证：10 个被删文件会残留）。
6. old_ref = git rev-parse HEAD（诊断/日志用）；old_version = version.txt；依赖指纹在下一步现算。
7. git fetch --depth=1 origin tag <target>（失败 → 保留旧代码、拉起应用、记日志）。
8. 依赖（**在 checkout 之前**）：用 `git show <target>:requirements.txt` 取目标清单写到包内临时文件
   `configs/.requirements.target.txt`；与当前 requirements.txt 比「条目指纹」（去注释/空行、排序后 sha256，
   注释或行序变化不触发）；变了或 `--force-pip` 才
   `python\python.exe -m pip install --no-deps --disable-pip-version-check -r <临时文件> [-i <index>]`（失败重试 3 次）。
   - **必须 --no-deps**（与 CI/AGENTS.md 一致），否则会拉 pyside6 元包/addons，体积爆炸。
   - **pip 放在 checkout 之前**：失败时工作区仍是旧代码，**无需回滚**；成功才切代码。
     （v1 是先切代码再 pip，失败会停在「新代码 + 旧依赖」的坏状态，已改进。）
9. git -c advice.detachedHead=false checkout -f <target>（失败 → 保留旧代码、拉起应用、记日志）。
   -f 必需：包内文件相对 index 仍是「未跟踪」，`-f` 是唯一能安全覆盖它们、
   且同时能覆盖 `.gitignore` 忽略但目标 tag 里被跟踪的路径（如 CNB 源的 ok/）的方式。
   不要用 git clean -fdx（会删掉 python/ ok/ configs/）。
10. 写 version.txt = <target>、version.txt.prev = old_version；清标记。
11. 顺带清理：删除除当前 tag 外的 refs/tags/* 并 git gc --prune=now（--depth=1 每次都会带来一份
    完整快照，不清理 .git 会随更新次数线性膨胀）。
12. 若 <root>/update.py 不存在（目标 tag 早于引入本文件的版本）→ 从 configs/.update_runner.py 恢复。
13. spawn python\pythonw.exe main.py（cwd=<root>，继承提权，免二次 UAC）→ 自身退出。

失败兜底：标记 configs/.updating 存在时，启动流程先清理并提示上一次更新失败（借 NKAS atomic_failure_cleanup 思路）；
git/pip 任一步失败都以旧版本拉起，绝不留下「起不来的包」。
日志：logs/update.log（update.py 用 pythonw 跑时无 stdout，必须落盘）。
```

### 5.5 应用内更新发起（Qt 内）

- 「检查更新」：后台线程（不要阻塞 UI）跑 `git\git.exe ls-remote --tags <git_url>`；**必须过滤注释 tag 的 `^{}` 行**（本仓库 tag 均为 annotated，已核实），再排序展示。
- changelog：`git log <cur>..<tag>` **在 `--depth=1` 下只能看到目标那一个提交**（祖先图不存在，已核实），不要用它当更新日志。改用 GitHub/CNB Release API 或 `docs/`。
- 「更新/降级」：确认后 `Popen([<root>/python/python.exe, "update.py", "--target", tag, "--wait-pid", str(os.getpid())], cwd=<root>)`，随后优雅收尾（`communicate.quit` / `executor.destroy`）再 `os._exit(0)`。
  - 已核实 `Config.__setitem__` 是即写即存，硬退不会丢配置；但直接 `os._exit` 会跳过 `TaskExecutor.destroy` 的线程收尾（`src/patches/runtime.py` 专门加了 join），建议先优雅退再硬退。
  - 用 `python.exe`（有控制台）还是 `pythonw.exe` 跑 update.py 需定：pythonw 无输出 → 统一写 `logs/update.log`，并给 CreateProcess 加 `CREATE_NO_WINDOW` 避免闪黑框。
- 更新完成下次启动弹「已更新 vX → vY」（读 `version.txt` 与 `version.txt.prev`）。
- 这些逻辑写在 ok-nikke 自己的「关于/更新」面板里，**不改用 ok 库**。

## 6. 更新时序

```text
[Qt 应用]                        [update.py]                        [新 Qt 应用]
   │  后台检查 tag
   │  用户确认
   │  Popen(update.py, --wait-pid) ──► 等旧进程退出
   │  优雅收尾 + os._exit(0)           git init/seed(首次)
   │                                   fetch tag + checkout -f
   │                                   pip（依赖变/强制）
   │                                   写 version.txt[.prev]
   │                                   Popen(pythonw main.py) ─────► 启动(新版本)
   │                                   退出
```

## 7. 与 ok-script / pyappify 桥的兼容（已核实）

1. `pyappify` 是 ok-script 的**硬 import**（`ok/__init__.py`、`ok/ui/qt/MainWindow.py`），必须保留安装或 inline。无 launcher 时：`app_version`/`app_profile` 为 `None` → `OK.__init__` 不覆盖 `config['version']`；`hide_pyappify()`/`kill_pyappify()`（`pid` 为 None）静默返回 False；`get_startup_version_change()` 无 `PYAPPIFY_*` 时返回 `None`。**均不崩**。
2. **`register_app_launcher_options` 不需要 patch**（v1 判断有误）：`create_app_launcher_options()` 在 `get_app_json_path()` 为 None（无 `PYAPPIFY_APP_JSON_PATH`）时**直接 return None**，设置里的「启动器」组**根本不会注册**；`KILL_LAUNCHER_AFTER_START` 也由 `src/patches/basic_options.py` 现有补丁移除，无系统写入风险。
3. **需要 patch 的是「关于」页的更新卡片**：`AboutTab` 只要 `pyappify.get_version_list` 可调用就建 `UpdateCard`（它是模块函数，恒可调用），而 `MainWindow` 首次显示后 **30 秒**必定调度一次检查 → `get_version_list` 抛 `RuntimeError("...pyappify_version: None")` → 卡片内红字「Failed to check for updates」。不崩，但每次启动必报一次。自建更新面板时必须一并：屏蔽 `MainWindow._schedule_update_check`（或让 `about_tab.update_card` 为 None）、屏蔽 `update_available_changed` 的导航徽标连接。
4. 「零系统写入」还剩一处框架侧写入：`ok/util/windows_schedule.py` 的「计划任务」页（COM/`schtasks`，写系统任务计划），仅当有一次性任务 `support_schedule_task=True` 时出现（`MainWindow` 按此判断是否加 Schedule tab）。当前 `src/tasks` 无人开启（默认 `False`）→ 成立，但属易被后人破坏的前提，已写入 §13 红线。另：真正的「开机自启」必然要写系统位置，与零写入互斥，故 `update_method=auto` 只做**应用内启动自检**，不做开机自启。

## 8. CI 与打包改造（build.yml）

删除：`pyappify-action`（Build launcher）、`USE_RELEASE`、`Reuse launcher` 步骤、`pyappify.yml`/`pyappify-cn.yml`/`pyappify-global.yml`、双便携包 + `.git` 重克隆 hack + launcher zip 发布、`.gitattributes` 相关的 `lfs: true`（本仓库无 LFS，已核实：无 `.gitattributes`，`advise.db` 为 1.8MB 实体 blob）。

新增/改为（**顺序重要**）：

1. 拉独立解释器 → `python/`。**CI（Actions 直连 GitHub）用官方 `python-build-standalone` win x64 3.12 的 `install_only` 资产**，固定 release 标签与文件名、校验 sha256；**本地复现用镜像**：官方 NuGet 包 `https://www.nuget.org/api/v2/package/python/3.12.10`（13.8MB / 解压 42MB / 自带 pip 25.0.1 / 可重定位，已实测），因为本机 hosts 屏蔽了 GitHub 资产域 `objects.githubusercontent.com`。
2. 拉 git → `git/`。CI 用 git-for-windows 的 **MinGit `<ver>-64-bit.zip`**（37MB，含 `cmd/git.exe`，无需 PortableGit）；本地同款走镜像 `registry.npmmirror.com/-/binary/git-for-windows/` 或 TUNA `github-release/git-for-windows/git/`（均实测可达）。**锁定版本并校验 sha256**。
3. （方案 C）**删掉 `inline_ok_requirements` 步骤**；`requirements.txt` 保持包含 `ok-script`/`pyappify`。框架升级时记得 bump `pyproject.toml` 并重新 `pip-compile`。
4. `python\python.exe -m pip install --no-deps --no-cache-dir -r requirements.txt`。`--no-deps` 必须：`PySide6-Fluent-Widgets` 的 `Requires-Dist` 直接依赖 `PySide6` 元包，不加会拉 addons 几百 MB（已核实）；`--no-cache-dir` 保证零系统写入（本机实测 pip 缓存已达 4GB）。
5. 编译入口 exe：`python launcher/build.py`（自动探测 MinGW/MSVC，链接后校验 manifest）→ 根目录。
6. 生成 `version.txt`（= tag）与 `configs/update.json` 默认模板；`version.txt` **不进 deploy.txt**。
7. 压缩单包 `ok-nikke-win32-portable.zip`（顶层 `ok-nikke/`）：~1GB 树用 `Compress-Archive` 慢且有历史体积坑，建议 `tar -a -c -f`（bsdtar，runner 自带）或 7z。
8. 保留「同步到 CNB 镜像」：`deploy.txt` 去掉 `pyappify.yml`，加上 `update.py`（不再有内联的 `ok`/`pyappify`）。CNB 的 tag 同步本身可用（现网无 tag 是手动删除所致）；仍建议加一步 `git ls-remote --tags <cnb>` 断言目标 tag 存在——CNB 无 tag 时从它更新只会静默失败（`fetch tag` 报错 → 保留旧代码）。
9. 更新 `docs/release.md`、`docs/getting-started.md`、`docs/configuration.md`、`AGENTS.md`（CI 段）中所有 pyappify/双包/内联描述。

单包命名：`ok-nikke-win32-portable.zip`。CN/Global 的区别不再是两个 zip，而是 `update.json` 的 `channel` 默认值 + 用户可切（受 §3.2 前提约束）。

## 9. 保留 / 删除 / 新增清单

| 类别 | 项 |
|---|---|
| 保留 | 测试、`inline_ok_requirements`、CNB 同步（deploy.txt）、`pyappify` pip 包（占位，ok-script 硬依赖）、ok-script 全部 |
| 删除 | `pyappify.yml`、build.yml 里 pyappify-action / USE_RELEASE / 双包 / `.git` 重克隆 / launcher zip / `lfs: true`；`.update_repo_gitignore`（去 pyappify 后成死文件，`ok`/`pyappify` 包内无引用，`.gitignore` 已覆盖 `__pycache__`） |
| 新增 | `update.py`、入口 exe 源码（`launcher/`）、`configs/update.json`、`version.txt`（+`.prev`）、应用内更新面板、`git/` 预置逻辑 |
| 修改 | `.gitignore`（`git/`、`version.txt`、`version.txt.prev`、`launcher/*.exe` 等）、`src/config.py` 或 `main.py`（读 `version.txt`）、`src/patches/`（关于页更新卡片）、`deploy.txt` |

## 10. 影响与风险

收益：零系统写入；单包；CI 去约 12 分钟 Tauri 编译；更新源可切换（受 §3.2 前提）。

风险 / 待确认：

1. 未签名 exe 的 UAC 黄色提示（可接代码签名）。
2. UAC 为必需（已定，入口 exe 负责提权）；因此入口 exe/git/python 无法经更新替换。
3. 预置 PortableGit（约 50MB）换首更离线可用（已定）。
4. 体积口径：`python-build-standalone` 本体约百兆级，包内大头是 `site-packages`（openvino/opencv/PySide6），与现有数据包相当。
5. `.git` 膨胀：`--depth=1` 每次更新带来一份完整快照（含 assets），需按 §5.4 第 11 步清理 tag + gc；否则长期使用后 `.git` 会显著增长。
6. 用户「覆盖解压」升级：旧 `.git` 会保留（`set-url` 处理），但被删除的历史文件与新包文件会混在一起 —— 首次由 update.py 的 seed 流程接管；文档需提示「推荐解压到新目录」。
7. `update.py` 自身被 checkout 覆盖/删除：本进程已把代码读入内存，实测无碍；仍按 §5.4 第 12 步从 runner 备份自愈。
8. 分发源可达性：`python-build-standalone` 与 git-for-windows 的 release 资产都在 GitHub 资产域，**实测本机（hosts 屏蔽 GitHub）拿不到**，必须走 NuGet / npmmirror / TUNA 并锁 sha256（§8 第 1-2 步）。CI 在 GitHub Actions 上不受影响，但本地复现构建会。
9. 更新源可用性：CNB 镜像的 tag 同步正常（手动删除过 tag，故当时现网无 tag）；从无 tag 的源更新会静默失败，CI 里加断言兜底（§8 第 8 步）。GitHub 走 git 自带的代理配置（`http.https://github.com.proxy`）实测可用：`ls-remote`/`clone`/`fetch` 均正常。出厂 `channel=auto`（按系统语言：中文 → CNB，其它 → GitHub），用户可随时在「关于 → 应用更新」里切换。

## 11. 实施分阶段

1. **P0 流程验证**：用真实 tag 跑通 `git init → seed → fetch → checkout -f`，确认「首次可覆盖、被删文件能清除、`ok/`/`configs/`/`python/` 存活、降级可行、pip 失败可回滚」（`dev_tools/` 下的 POC 脚本，不动 ok-script）。
2. `update.py` + 单测（命令序列/URL 解析/hash 比较/回滚/版本号读写，纯标准库，可离线跑）。
3. 入口 exe + standalone Python + `main.py` 直跑（含 §4.1 的 cwd/`sys.path` 验证）。
4. 应用内更新面板 + `version.txt` 接入 + 关于页 patch。
5. 重写 build.yml（去 pyappify、单包、CNB 同步、文档同步）。
6. 全量测试（逐文件独立进程）+ 发一个版本实机验证。

## 12. 进度与待决策

- [x] 代码核实（ok-script 2.0.2 / pyappify 1.0.13 / 框架路径与降级行为 / 仓库 tag 与内联归属）
- [x] **更新源策略已定：方案 C**（取消内联，保留 `ok-script` 依赖）——理由与影响见 §3.2
- [x] **P0 流程验证**：`dev_tools/poc_update_flow.py`（**29 项断言全通过**，用本仓库 tag + `file://` 本地远端，仅操作临时目录）
  - A 负向对照已复现 v1 硬伤：不 seed 直接 `checkout` → `error: The following untracked working tree files would be overwritten by checkout ... Aborting`
  - B 首次更新 v0.1.0→v0.1.2：10 个被删文件清除、17 个新增文件就位、`ok/`/`pyappify/`/`python/`/`configs/update.json` 存活、`version.txt[.prev]` 正确、标记清理、工作区仅剩过渡期未跟踪的 `update.py`
  - C 降级 v0.1.2→v0.1.0：17 个该删文件清除、本地 tag 只剩当前（`.git` 不膨胀）
  - D pip 失败（`--force-pip` + 假解释器）：退出码非 0、工作区与版本号保持旧值、标记清理
  - E `--list-tags`：`^{}` 行过滤、版本倒序
- [x] `update.py` 初版（零第三方依赖）+ 单测 `tests/TestUpdateScript.py`（26 项，含「只允许标准库 import」「version.txt 必须在 .gitignore」两条红线断言）
- [x] `version.txt` 接入：`src/config.py` 读包根 `version.txt`，缺失回退 `dev`（已实测两种情形）；两处读取均做 **BOM 加固**（PowerShell `Set-Content -Encoding utf8` 会带 BOM）
- [x] **决策：方案 C**（取消内联，保留 `ok-script` 依赖）
- [x] **入口 exe + 独立解释器 POC 完成**（`dev_tools/poc-portable/`，全部在 gitignore 目录内）

**POC 实测数据（2026-09-10，本机）**

| 项 | 结果 |
|---|---|
| 独立解释器 | 官方 NuGet `python/3.12.10`：13.8MB 下载 / 42MB 解压，自带 **pip 25.0.1**，**移动目录后仍可用**（可重定位），布局 `python/{python.exe,pythonw.exe,Lib/site-packages}` 与设计一致 |
| 依赖安装（方案 C） | `pip install --no-deps --no-cache-dir -i TUNA -r requirements.txt` 成功，耗时 **297s**，`site-packages` **707MB**；`ok`/`pyappify` 均来自包内 `site-packages`（无内联目录） |
| 冒烟（cwd=包根） | `og.app_path` = 包根、补丁链全部生效、`version.txt` 读到 `v0.1.0` |
| MinGit | `MinGit-2.55.0.5-64-bit.zip` 37MB / 解压 90MB，`git/cmd/git.exe` 版本与设计一致（无需 PortableGit） |
| 随包 git 更新 | 假便携包内 `seed → fetch --depth=1 → checkout -f → 自愈 update.py` 全流程 **3.6s** 成功；`.git` 仅 **24MB**（seed 未吞掉 707MB 的 `python/`：tracked 163 个文件，`python/`、`git/`、`version.txt` 均为 0） |
| 入口 shim | MinGW 编译：无 manifest 22KB / 带图标+manifest 150KB；启动语义全部通过——**0.01s 返回不等待子进程**、cwd=包根、`sys.path[0]`=包根、`argv[0]`=包根下 `main.py`、`sys.executable`=`python\pythonw.exe`、`-t 1 -e` 原样转发 |
| 零系统写入 | pip 未写缓存（`--no-cache-dir`）；git 只写包内 `.git/config`（15 条本地项）与 `.git/info/exclude`，全局 `~/.gitconfig` 只读不改 |
| 网络可达性 | GitHub 直连（curl）被 hosts 屏蔽，但 **git 走全局代理实测可用**（ls-remote/clone/fetch 正常）；CNB 匿名可读、无 tag；nuget.org / npmmirror / TUNA 均可达 |

- [x] **更新面板**：`src/ui/UpdateCard.py`（`NikkeUpdateCard`）+ `src/patches/about_update.py`
  - 只换 `AboutTab` 里那个模块级名字 `UpdateCard` → 框架的「30 秒自动检查 + 导航徽标」原样复用（我们的卡片同名提供 `update_available_changed`/`check_started`/`check_for_updates()`），**没有改 MainWindow**；
  - `get_startup_version_change` 改为读 `version.txt` / `version.txt.prev`（首次调用即消费 `.prev`，避免每次启动重复提示）；
  - 更新源下拉（auto/github/cnb/custom + 自定义 URL）直接写 `configs/update.json`，与 `update.py` 共用字段；
  - UI 里零 git/pip 逻辑：检查更新 = `update.py --list-tags` 子进程，执行更新 = `update.py --target <tag> --wait-pid <本进程>` 子进程 + 优雅退出（3s 兜底硬退）；
  - 验证：`tests/TestUpdateConfig.py` 15 项 + `dev_tools/smoke_update_card.py` 13 项（真实拉到 GitHub tag `['v0.1.2','v0.1.1']`、徽标信号为 True、选中后按钮文案「更新」、切源写回配置并还原）
- [x] 重写 `.github/workflows/build.yml`（方案 C）：删 inline；CI 直连 GitHub 取 python-build-standalone + MinGit；依赖装进包内解释器并**断言来自 site-packages**；MSVC（vswhere + DevShell）编入口 exe；写 `version.txt` 与默认 `configs/update.json` 并冒烟校验；CNB 同步后**断言 tag 存在**；bsdtar 打单包。`deploy.txt` 同步（去 `ok`，加 `update.py`/`launcher`；过渡期保留 `pyappify.yml`）。YAML 已校验（13 个 step 全部含 run/uses）
- [x] 全量测试：**21/21 文件通过**（逐文件独立进程，`run_tests.ps1`）
- [x] 文档同步：`docs/release.md`、`docs/getting-started.md`、`docs/configuration.md`、`docs/en/{release,getting-started,configuration}.md`、`AGENTS.md`（CI 段 / 架构概览 / 命令表 / 新增更新相关红线）
- [ ] 实机发版验证（真实 tag 构建一次：解释器与 MinGit 下载、MSVC 编译、包内 `main.py` 首跑、应用内更新一次）
- [ ] 老用户迁移：过渡期保留 `pyappify.yml`（仓库 + `deploy.txt`），确认迁移完成后删除

## 13. 新增红线（**已并入 AGENTS.md 红线清单**）

1. 入口必须以「cwd = 包根、`sys.path[0]` = 包根、脚本路径方式」启动（见 §4.1）；禁止 `-m` 或改 cwd。
2. `version.txt`/`version.txt.prev` 绝不入 git、绝不进 `deploy.txt`。
3. `update.py` 只 import 标准库；任何新增依赖都必须走「包内 python + pip」而不能引入环境要求。
4. `update.py` 的 pip 调用必须 `--no-deps`，与 CI 保持一致。
5. 新任务不得设置 `support_schedule_task=True`（会写系统任务计划，破坏零系统写入）。
