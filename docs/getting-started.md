# 快速开始

## 1. 从模板创建仓库

点击 GitHub 上的 [Use this template](https://github.com/ok-oldking/ok-script-app/generate)，创建自己的 repository，然后 clone：

```bash
git clone https://github.com/<你的 GitHub 用户名>/<你的仓库名>.git
cd <你的仓库名>
```

clone 完成后，可以选择以下任一方式初始化项目：

- **使用 AI 编程工具（推荐）**：在 Codex 中输入 `使用 $initialize-ok-script-app 初始化这个仓库`。使用其他工具时，让它先阅读 `.agents/skills/initialize-ok-script-app/SKILL.md`。初始化助手会先询问游戏名、运行目标、仓库地址、图标和首个任务，再修改项目。
- **手动初始化**：继续完成本文和后续页面中的步骤。

## 2. 安装 Python 3.12

安装 [Python 3.12.10](https://www.python.org/downloads/release/python-31210/)，然后在仓库目录中执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install --no-deps -r requirements.txt --upgrade
```

通常不需要管理员权限。如果目标游戏以管理员权限运行，自动化程序也需要以相同权限启动，否则截图或输入可能无法生效。

## 3. 初始化应用

接下来完成以下工作：

1. 按[应用配置](configuration.md)修改应用名称、运行目标、图标和更新仓库。
2. 按[任务开发](tasks.md)创建并注册第一个任务。
3. 启动 Debug 模式：

```powershell
python main_debug.py
```

4. 运行测试：

```powershell
python -m unittest tests.TestMain
```

5. 验证完成后，按[打包与发布](release.md)配置工作流并推送 tag。
