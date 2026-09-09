# 快速开始

## 使用发布包（推荐）

从 [GitHub Releases](https://github.com/c6n1aa/ok-nikke/releases) 下载 `ok-nikke-win32-portable.zip`，解压到任意目录后运行其中的 `ok-nikke.exe`。

- **必须以管理员身份启动**：如果游戏以管理员权限运行，自动化程序也需要同等权限，否则截图或输入可能失效。
- 便携包根目录附带 `pyappify-cn.yml` 与 `pyappify-global.yml`，首次运行前按网络环境把其中一个重命名为 `pyappify.yml`（与 exe 同目录）作为更新源配置。
- 游戏分辨率需为 16:9 且不低于 1600×900。

## 从源码运行

仅支持 Python 3.12（其他版本未测试）：

```powershell
git clone https://github.com/c6n1aa/ok-nikke.git
cd ok-nikke
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements.txt --upgrade
```

必须用 `--no-deps`：依赖已在 `requirements.txt` 中锁定（含全部传递依赖），让 pip 解析依赖会装到 `pyside6` 元包与 addons 模块。

随后启动：

```powershell
.\.venv\Scripts\python.exe main_debug.py   # Debug 模式，含截图/标注等开发工具
.\.venv\Scripts\python.exe main.py         # 普通模式
```

环境就绪后，按需继续：

- 调整运行目标、任务清单或应用信息：见[应用配置](configuration.md)。
- 新增或修改任务：见[任务开发](tasks.md)。
- 生成发布包：见[打包与发布](release.md)。

## 运行测试

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestMain   # 单个测试文件
.\run_tests.ps1                                         # 全量，逐文件独立进程
```

全量必须逐文件独立进程执行：同一进程内连跑多个测试文件时，ok 单例无法重建，会产生假错误。

## 常见问题

- **截图全黑或识别不到画面**：确认程序与游戏权限一致（同为非管理员或同为管理员），并关闭 HDR 或允许 AutoHDR 提示。
- **分辨率不匹配**：确认游戏窗口为 16:9 且不低于 1600×900；素材以 2560×1440 为基准，低分辨率截图不适合用来调模板。
- **更新后打不开**：删除 `configs/` 目录下的配置后重启（会重置任务配置），仍失败则从 Releases 重新下载便携包。
