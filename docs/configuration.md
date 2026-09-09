# 应用配置

应用配置集中在 `src/config.py`，在 `ok.OK(config)` 之前生效。

## 应用信息

| 键 | 说明 |
| --- | --- |
| `gui_title` | 窗口标题，当前为 `ok-nikke` |
| `gui_icon` | 窗口图标路径，替换 `icons/icon.png`（及 `icons/icon.ico`）时保持文件名可免改配置 |
| `gui` | `type` 固定 `'qt'`（本项目不使用 Web UI）+ `window_size` 窗口/最小尺寸 |
| `supported_resolution` | 支持的比例（16:9）、最低分辨率（1600×900）与非 16:9 时的 `resize_to` 目标 |
| `links` | 「关于」页展示的项目主页、分享文案与反馈链接 |
| `version` | 由打包工作流自动改写，源码中保持 `"dev"` |
| `screenshots_folder` | 截图输出目录，每次启动清空 |

## 运行目标

本项目**只启用 Windows 原生目标**（《NIKKE》Windows 客户端）。`adb`（模拟器/Android）与 `browser` 目标在 `src/config.py` 中以注释形式保留，未启用：启用浏览器目标需要额外安装 `playwright`，且依赖要重新从 `pyproject.toml` 锁定。

`windows` 部分：

| 键 | 当前值 | 说明 |
| --- | --- | --- |
| `exe` | `['nikke.exe']` | 游戏进程名，启动器据此拉起或匹配窗口 |
| `interaction` | `['Pynput', 'PyDirect']` | 输入方式及优先级 |
| `capture_method` | `['WGC', 'BitBlt_RenderFull', 'BitBlt']` | 截图方式及优先级，WGC 优先以支持后台运行 |
| `require_bg` | `True` | 要求后台截图能力 |
| `check_hdr` / `force_no_hdr` | `False` | AutoHDR 时是否提示/禁止运行 |
| `start_timeout` | `120` | 启动器等待游戏就绪的超时 |

## 识别相关

- `ocr`：使用 `onnxocr`，开启 `use_openvino`。
- `template_matching`：指定 `coco_feature_json`（`assets/coco_annotations.json`）与默认阈值/偏移。素材约定见[界面识别与失败恢复](screen-and-recovery.md)。

## 任务与界面

- `onetime_tasks`：用户点击执行的一次性任务清单，与 `src/tasks/` 中的任务类一一对应。
- `trigger_tasks`：后台周期任务，当前为空。
- `custom_tabs`：自定义 Tab，当前注册 `src/ui/DailyTab.py` 的 `DailyTab`。
- `custom_tasks`：关闭状态，正式版不显示「脚本」「模板」Tab。

新增或修改任务后在此注册，详见[任务开发](tasks.md)。

## 框架补丁

`src/config.py` 顶部调用 `src/patches.apply_all()`，在 `ok.OK(config)` 构造前统一应用对 ok-script 的猴子补丁（启动器、运行时、任务列表等）。

- 扩展或修正框架行为一律写入 `src/patches/`，并在 `apply_all()` 中注册；各补丁职责见 `src/patches/README.md`。
- 不要在任务或其他模块中直接 monkey-patch `ok.*`。

## 依赖与更新源

- 依赖源是 `pyproject.toml`：`pip-compile pyproject.toml -o requirements.txt`，生成后删除 `pyside6`/`pyside6-addons` 条目（只装 `pyside6-essentials`）。
- 更新仓库地址在 `pyappify.yml` 的 `git_url`；便携包附带的 `pyappify-cn.yml` / `pyappify-global.yml` 供用户选择更新源。详见[打包与发布](release.md)。
