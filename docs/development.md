# 开发环境

面向开发者：从源码运行、运行测试与开发文档地图。

## 从源码运行

仅支持 Python 3.12（其他版本未测试）：

```powershell
git clone https://github.com/c6n1aa/ok-nikke.git
cd ok-nikke
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements.txt --upgrade
```

必须用 `--no-deps`：依赖已在 `requirements.txt` 中锁定（含全部传递依赖），让 pip 解析依赖会装到 `pyside6` 元包与 addons 模块（本项目只装 `pyside6-essentials`）。

随后启动：

```powershell
.\.venv\Scripts\python.exe main_debug.py   # Debug 模式，含截图/标注等开发工具
.\.venv\Scripts\python.exe main.py         # 普通模式
```

## 运行测试

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestMain   # 单个测试文件
.\run_tests.ps1                                         # 全量，逐文件独立进程
```

全量必须逐文件独立进程执行：同一进程内连跑多个测试文件时，ok 单例无法重建，会产生假错误。

## 开发文档

环境就绪后，按需继续：

1. [应用配置](configuration.md)：运行目标、任务清单、自定义 Tab 与补丁入口。
2. [任务开发](tasks.md)：新增任务、注册任务与编写测试。
3. [界面识别与失败恢复](screen-and-recovery.md)：任务开发的核心约定，写任务前必读。
4. [任务简报模板](task_brief_template.md)：用简报驱动 AI 生成任务代码。
5. [打包与发布](release.md)：tag 触发的便携包发布流程。
6. [文档网站](documentation.md)：本地预览与 GitHub Pages 部署。

仓库内置 Agent Skills：`ok-script-tasks`（创建/修改/注册任务类）、`ok-script-codegen`（根据需求或截图生成 `run()` 逻辑）、`ok-script-i18n`（同步翻译）、`deploy`（发版打 tag）。
