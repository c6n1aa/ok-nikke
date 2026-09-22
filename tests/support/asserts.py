"""按语义匹配 mock 调用的断言工具。

任务源码里的等待时长（after_sleep、time_out、wait_confirm、settle_time、check_interval、
duration）属于运行时调参，测试把它们抄进断言会让「调参」误报失败。这里只比对调用目标与
语义参数：

- 目标：位置参数（特征名、Box、坐标等）；
- 语义参数：调用方显式传入的 kwarg（raise_if_not_found、box、match、click、wait_for_popup 等）；
- 忽略：``_TUNING_KWARGS`` 里的纯调参 kwarg。

需要断言调参值本身（如 settle_time=0 的瞬态赛跑契约）时，直接读
``call.kwargs[...]``，不走本模块。
"""

_TUNING_KWARGS = frozenset({
    "after_sleep",
    "time_out",
    "wait_confirm",
    "settle_time",
    "check_interval",
    "duration",
})


def _semantic_kwargs(kwargs):
    """剔除纯调参 kwarg，保留语义参数。"""
    return {key: value for key, value in kwargs.items() if key not in _TUNING_KWARGS}


def _format(call_args_list):
    """把调用列表格式化成可读的多行文本，用于断言失败信息。"""
    return "\n".join(f"  {call}" for call in call_args_list) or "  <无调用>"


def _matches(call, args, kwargs):
    """判断单次调用的目标与语义参数是否匹配（忽略调参 kwarg）。"""
    expected = _semantic_kwargs(kwargs)
    return call.args == args and all(call.kwargs.get(key) == value for key, value in expected.items())


def matching_calls(mock, *args, **kwargs):
    """返回目标与语义参数均匹配的全部调用（忽略调参 kwarg）。"""
    return [call for call in mock.call_args_list if _matches(call, args, kwargs)]


def assert_called_once_semantic(mock, *args, **kwargs):
    """断言 mock 恰好被调用一次，且该调用目标与语义参数匹配（忽略调参 kwarg）。"""
    calls = mock.call_args_list
    if len(calls) != 1:  # 调用次数不符，直接报出实际调用。
        raise AssertionError(f"期望恰好 1 次调用，实际 {len(calls)} 次：\n{_format(calls)}")
    if not _matches(calls[0], args, kwargs):  # 唯一一次调用的目标或语义参数不符。
        raise AssertionError(f"调用不匹配：目标 args={args}，语义 kwargs={_semantic_kwargs(kwargs)}"
                             f"\n实际调用：\n{_format(calls)}")


def assert_last_call_semantic(mock, *args, **kwargs):
    """断言 mock 最后一次调用的目标与语义参数匹配（忽略调参 kwarg）。"""
    calls = mock.call_args_list
    if not calls:  # 尚无调用。
        raise AssertionError("尚无调用，无法断言最后一次调用")
    if not _matches(calls[-1], args, kwargs):  # 末次调用的目标或语义参数不符。
        raise AssertionError(f"末次调用不匹配：目标 args={args}，语义 kwargs={_semantic_kwargs(kwargs)}"
                             f"\n实际调用：\n{_format(calls)}")


def assert_any_call_semantic(mock, *args, **kwargs):
    """断言 mock 至少存在一次目标与语义参数匹配的调用（忽略调参 kwarg）。"""
    if not matching_calls(mock, *args, **kwargs):  # 没有任何匹配调用。
        raise AssertionError(f"未找到匹配调用：目标 args={args}，语义 kwargs={_semantic_kwargs(kwargs)}"
                             f"\n实际调用：\n{_format(mock.call_args_list)}")
