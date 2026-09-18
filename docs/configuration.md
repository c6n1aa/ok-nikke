# 应用配置

面向开发者。应用配置集中在 `src/config.py`，在 `ok.OK(config)` 之前生效。普通用户的任务开关与配置项都在应用主界面选择，无需修改代码。

## 应用信息

| 键 | 说明 |
| --- | --- |
| `gui_title` | 窗口标题，当前为 `ok-nikke` |
| `gui_icon` | 窗口图标路径，替换 `icons/icon.png`（及 `icons/icon.ico`）时保持文件名可免改配置 |
| `gui` | `type` 固定 `'qt'`（本项目不使用 Web UI）+ `window_size` 窗口/最小尺寸 |
| `supported_resolution` | 支持的比例（16:9）、最低分辨率（1600×900）与非 16:9 时的 `resize_to` 目标 |
| `links` | 「关于」页展示的项目主页、分享文案与反馈链接 |
| `version` | 由包根 `version.txt` 提供（build 写入、update.py 更新），取不到时回退源码里的 `"dev"` |
| `screenshots_folder` | 截图输出目录，每次启动清空 |

## 运行目标

本项目**只启用 Windows 原生目标**（《胜利女神：NIKKE》Windows 客户端）。`adb`（模拟器/Android）与 `browser` 目标在 `src/config.py` 中以注释形式保留，未启用：启用浏览器目标需要额外安装 `playwright`，且依赖要重新从 `pyproject.toml` 锁定。

`windows` 部分：

| 键 | 当前值 | 说明 |
| --- | --- | --- |
| `exe` | `['nikke.exe']` | 游戏进程名，启动器据此拉起或匹配窗口 |
| `interaction` | `[SyntheticTouch]` | 输入方式及优先级；`SyntheticTouch` 走合成触控指针（WM_POINTER）绕开游戏输入过滤，需要游戏窗口位于前台，键盘未实现 |
| `capture_method` | `['WGC', 'BitBlt_RenderFull', 'BitBlt']` | 截图方式及优先级，WGC 优先以支持后台运行 |
| `require_bg` | `True` | 要求后台截图能力 |
| `check_hdr` / `force_no_hdr` | `False` | AutoHDR 时是否提示/禁止运行 |
| `start_timeout` | `120` | 启动器等待游戏就绪的超时 |

`SyntheticTouch`（合成触控指针）的限制与系统要求：

- **系统要求**：Windows 10 1809 或更高，合成指针 API（`CreateSyntheticPointerDevice` / `InjectSyntheticPointerInput`）在此版本引入。
- **仅鼠标/触控**：不实现键盘（`send_key` 等）与滚轮，`scroll` 用触控拖动近似。
- **命中判定认桌面 Z 序**：目标点被其他窗口遮挡时点击无效，故每次点击前把游戏窗口提到前台，需要窗口位于前台且不可最小化。
- **走 `WM_POINTER` 消息路径**：仅对接受指针/触控输入的游戏有效，只认传统鼠标消息的游戏不适用。

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

- 依赖源是 `pyproject.toml`：`uv lock` 生成 `uv.lock`，`uv export --format requirements-txt --no-hashes --no-dev -o requirements.txt` 导出交付锁；`[tool.uv] exclude-dependencies` 已剔除 `pyside6-fluent-widgets -> pyside6` 元包边（只装 `pyside6-essentials`）。**框架（`ok-script`）升级时同时 bump `pyproject.toml` 并重新 `uv lock` + `uv export`，与 tag 一起提交**——应用内更新只在依赖指纹变化时重装依赖，不同步就会「界面已更新、框架没升级」。
- 便携包只有一个，更新源与依赖镜像源是运行时配置 `configs/update.json`（`channel`: `auto`/`github`/`cnb`；`pip_index`: `auto`/`pypi`/`tuna`），可在「关于 → 应用更新」切换；`auto` 按系统语言选择（中文 → CNB 镜像 / 清华 pip 镜像，其它 → GitHub / 官方 PyPI）。更新实现见根目录 `update.py`，详见[打包与发布](release.md)。
