from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from src.chatbot_service.chatbot_helpers.setup_llm import gpt_4o_llm

smalltalk_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You talk like in a professional manner who handle vague intents.   
            Please respond in a friendly and kind manner.  
         Another llm model is set to classify intents, and you are responsible for handling the situation when the intent is not extracted from texts.\
         Answer all questions to the best of your ability.\
         Usually, ask user to provide more details about their questions in a nice manner.\
         
         Remember that director cannot upload cards. Please explain to director if they intents to upload cards.
         
         Kindly guide the user to register as a new worker, then, they are able to use the system. 

         Remember to reply in *Cantonese* no matter which language the user is using.
         Thanks!""",
        ),
        ("human", "{messages}"),
    ]
)

smalltalk_chain = smalltalk_template | gpt_4o_llm | StrOutputParser()


def falldown_smalltalk_response(body):
    try:
        response_message = smalltalk_chain.invoke({"messages": body})

        if isinstance(response_message, BaseMessage):
            response_message_content = str(
                response_message.content
            )  # Get the response message content
            response_message_content = f"{response_message_content}"

        else:
            response_message_content = "Error: Response format is not valid."

        return response_message_content

    except Exception as e:
        response_message_content = f"Error: {str(e)}"
        return response_message_content

