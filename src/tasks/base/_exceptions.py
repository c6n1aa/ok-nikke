from ok.task.exceptions import WaitFailedException


class InterruptedByDialogException(WaitFailedException):
    """长等待期间命中致命中断弹窗（断线/维护/登录过期等）时抛出。

    继承 WaitFailedException：try_step/_recover_to_lobby 的现有捕获与
    恢复路径自动兼容，无需任何改动。
    """