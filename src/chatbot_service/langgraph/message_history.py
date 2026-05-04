from typing import List, Sequence

from langgraph.graph.message import AnyMessage


class LimitedHistory:
    def __init__(self, max_messages: int):
        self.max_messages = max_messages

    def __call__(
        self, messages: List[AnyMessage], new_messages: Sequence[AnyMessage]
    ) -> List[AnyMessage]:
        # Ensure new_messages is a list to avoid type errors
        if not isinstance(new_messages, list):
            new_messages = list(new_messages)

        # Combine existing messages with new messages
        all_messages = messages + new_messages

        # Limit the history to the last `max_messages`
        limited_history = all_messages[-self.max_messages :]

        return limited_history
