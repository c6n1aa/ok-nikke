import ctypes
import os
import sys


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def request_admin():
    # 以管理员权限重新启动当前脚本，返回是否成功（失败通常是用户取消了 UAC）
    script = os.path.abspath(sys.argv[0])
    params = f'"{script}"'
    if len(sys.argv) > 1:
        params += ' ' + ' '.join(f'"{a}"' if ' ' in a else a for a in sys.argv[1:])
    ret = ctypes.windll.shell32.ShellExecuteW(None, 'runas', sys.executable, params, None, 1)
    return ret > 32


if __name__ == '__main__':
    if not is_admin():
        if not request_admin():
            print('需要管理员权限！请在弹出的 UAC 窗口中点击"是"，或手动以管理员身份运行本程序。')
            sys.exit(1)
        # 已请求提权，由新的管理员进程运行，当前进程退出
        sys.exit(0)

    import ok
    from src.config import config

    config = config
    config['debug'] = True
    ok = ok.OK(config)
    ok.start()
