def error_handler_node(state):
    error_msg = f"⚠️ 發生錯誤: {state.get('action_result', '未知錯誤')}"
    state["action_result"] = error_msg  # 👈 Set pending_message
    return state


def fallback_node(state):
    fallback_msg = "請稍後再試，或輸入 'restart' 重新開始流程。"
    state["action_result"] = fallback_msg  # 👈 Set pending_message
    return state
