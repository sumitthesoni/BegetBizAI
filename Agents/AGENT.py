import os
import logging
from dotenv import load_dotenv
from config import SYSTEM_PROMPT_PATH
import warnings

# Ignore all warnings
warnings.filterwarnings("ignore")

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph import StateGraph, END, START, MessagesState
from langgraph.prebuilt import ToolNode
from langchain_openai import ChatOpenAI

from utils.google_image_fetching_tool import fetch_google_images
from utils.lead_sender_tool import send_lead
from Memory.sqldatabase import load_memory, save_memory
from debugging.logger import logging

# Load environment variables
load_dotenv()
os.getenv("OPENAI_API_KEY")

# Core LLM Setup
core_llm = ChatOpenAI(model="gpt-4o-mini")
llm_with_tools = core_llm.bind_tools([fetch_google_images,send_lead])

# Load system prompt
with open(SYSTEM_PROMPT_PATH,encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

# ––– AGENT WORKFLOW ––– #
def AGENT() -> StateGraph:
    # The "model" node
    def call_model(state: MessagesState, config: RunnableConfig) -> MessagesState:
        logging.info("Executing 'call_model' node")
        thread_id = config['metadata']['thread_id']

        # ① Load memory for this thread
        memory = load_memory(thread_id)
        history = memory.chat_memory.messages
        summary_of_history = memory.moving_summary_buffer

        # ② Build message list
        user_msg = state["messages"][0]

        # ③ Build full prompt
        prompt = [SystemMessage(content=SYSTEM_PROMPT.format(history=summary_of_history))] + history + [user_msg] + state["messages"][1:]

        response: AIMessage = llm_with_tools.invoke(prompt)

        return {"messages": [response]}

    # Router node: decide whether to use tool or finish
    def router(state: MessagesState, config: RunnableConfig) -> str:
        logging.info("Executing 'router' node")
        if state["messages"][-1].tool_calls:
            logging.info("Tool is called")
            return "use_tools"
        else:
            thread_id = config['metadata']['thread_id']
            memory = load_memory(thread_id=thread_id)
            logging.info(f"Saving memory for thread {thread_id}")

            # Save all message types to memory
            for msg in state['messages']:
                if isinstance(msg, HumanMessage):
                    memory.chat_memory.add_user_message(msg.content)
                elif isinstance(msg, AIMessage) and not msg.tool_calls:
                    memory.chat_memory.add_ai_message(msg.content)
                elif isinstance(msg, AIMessage) and msg.tool_calls:
                    memory.chat_memory.add_ai_message(msg)
                elif isinstance(msg, ToolMessage):
                    memory.chat_memory.add_message(msg)

            memory.save_context(inputs={"input": ''}, outputs={"output": ''})
            save_memory(thread_id=thread_id, memory=memory)
            logging.info("Memory saved, routing to 'finish'")
            return "finish"

    # Build the graph
    wf = StateGraph(state_schema=MessagesState)
    wf.add_node("model", call_model)
    wf.add_node("use_tools", ToolNode([fetch_google_images,send_lead]))
    wf.add_edge(START, "model")
    wf.add_conditional_edges(
        "model",
        router,
        {"use_tools": "use_tools", "finish": END}
    )
    wf.add_edge("use_tools", "model")

    return wf.compile()