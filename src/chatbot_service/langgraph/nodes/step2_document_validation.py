import logging

from src.utils.standardization_helpers import validate_mobile_from_whatsapp


def respond(state, message, error=True):
    """Helper to update the state with a response message."""
    state["action_result"] = message
    state["status"] = "responder"
    state["error"] = error
    return state


async def document_validation_node(state):
    logging.info(f"Step 2: Validating fields: {state}")

    sender = state["messages"][-1]["content"]["From"]
    intent = state.get("current_intent", "")
    media_urls = state.get("media_urls", [])
    user_message = state["messages"][-1]["content"].get("Body", "")

    sender_info = await validate_mobile_from_whatsapp(sender)

    if intent is None or intent == "":
        state["error"] = True
        return respond(
            state,
            "AI而家仲學緊嘢，所以未必識晒你講嘅嘢 😅 暫時淨係識「登記」同「打卡」咋～ 我哋會快啲搞掂，希望唔會搞到你唔方便～真係唔該晒你體諒呀 🙏",
        )

    # Case 1: Already registered
    if intent == "registration" and sender_info is not None:
        return respond(state, "你已經登記過喇，唔使再登記多次啦。")

    # Case 2: Registration intent, but no media
    if intent == "registration" and media_urls == []:
        return respond(
            state, "可唔可以回覆我「登記」同埋你張身份證呀？🙏 真係多謝你配合呀！🙌"
        )

    # ✅ Case 3: Registration intent, media present, sender not yet registered → Proceed
    if intent == "registration" and media_urls and sender_info is None:
        state["status"] = "await_field"
        state["error"] = False
        return state

    # Case 4: Unknown intent with no media
    if intent == "" and media_urls == []:
        return respond(
            state,
            "AI而家仲喺開發緊，所以未必識晒你講嘅嘢，暫時淨係做到登記同打卡啫。如果你係想登記，不如一齊send埋「登記」兩個字同你嘅身份證相過嚟啦～唔該晒你呀！🙏",
        )

    # Case 5: Unknown intent with media
    if user_message == "" or user_message == " ":
        return respond(
            state,
            "AI而家仲學緊嘢，所以未必識晒你講嘅嘢 😅 暫時淨係識「登記」同「打卡」咋～ 我哋會快啲搞掂，希望唔會搞到你唔方便～真係唔該晒你體諒呀 🙏",
        )

    # Default: Assume we're waiting for next info
    state["status"] = "await_field"
    state["error"] = False
    return state
