import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()
os.environ["KMP_DUPLICATE_LIB_OK"] = "True"

openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
openrouter_base_url = "https://openrouter.ai/api/v1"


deepseek_model = "deepseek/deepseek-r1:free"
gpt_mini_model = "openai/gpt-4o-mini"
gpt_4o_model = "openai/chatgpt-4o-latest"
anthropic_claude_3_7_sonnet_model = "anthropic/claude-3.7-sonnet"

gpt_mini_llm = ChatOpenAI(
    model=gpt_mini_model, base_url=openrouter_base_url, api_key=openrouter_api_key
)

gpt_4o_llm = ChatOpenAI(
    model=gpt_4o_model, base_url=openrouter_base_url, api_key=openrouter_api_key
)

anthropic_claude_3_7_sonnet_llm = ChatOpenAI(
    model=anthropic_claude_3_7_sonnet_model,
    base_url=openrouter_base_url,
    api_key=openrouter_api_key,
)


gpt_4_1_model = "openai/gpt-4.1"
gpt_4_1_llm = ChatOpenAI(
    model=gpt_4_1_model, base_url=openrouter_base_url, api_key=openrouter_api_key
)


mistral_large_model = "mistralai/mistral-large-2411"
mistral_large_llm = ChatOpenAI(
    model=mistral_large_model, base_url=openrouter_base_url, api_key=openrouter_api_key
)
