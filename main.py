import asyncio
import operator
from typing import Optional

import dotenv

# --- FastAPI 引入 ---
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn

# ---langgraph相关---
from langchain_openai import ChatOpenAI
from langchain.messages import (
    SystemMessage,
    HumanMessage,
    AnyMessage
)
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END

# ---pipecat相关---
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    InterruptionFrame,
    LLMTextFrame,
    LLMFullResponseStartFrame,
    LLMFullResponseEndFrame,
    LLMContextFrame
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.frames.frames import InputAudioRawFrame, OutputAudioRawFrame, Frame
from pipecat.serializers.base_serializer import FrameSerializer

# ---TTS-----
from FastSentenceAggregator import FastSentenceAggregator

from pydantic import BaseModel, Field
from typing_extensions import TypedDict, Annotated

from config_manager import ConfigManager

# ---RAG相关-----

USER_MEMORIES_DIR = "./user_memories"
KNOWLEDGE_FILE = "./knowledge.txt"
VECTOR_DB_DIR = "./vector_db"

dotenv.load_dotenv()
config_manager = ConfigManager()
app = FastAPI()


# 定义状态
class MessageState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    llm_calls: int


class RawPCMSerializer(FrameSerializer):
    async def serialize(self, frame: Frame) -> bytes | str | None:
        # 当后端 TTS 生成音频准备发给前端时：剥离信封，只发纯字节
        if isinstance(frame, OutputAudioRawFrame):
            return frame.audio
        return None

    async def deserialize(self, data: bytes | str) -> Frame | None:
        # 当收到前端发来的 ws.send 纯字节时：封装成 Pipecat 能懂的音频帧
        if isinstance(data, bytes):
            return InputAudioRawFrame(
                audio = data,
                sample_rate = 16000,  # 匹配前端麦克风采集的 16000Hz
                num_channels = 1
            )
        return None


class UserInfo(BaseModel):
    name: Optional[str] = Field(default = None)
    hobbies: Optional[list[str]] = Field(default = None)
    english_level: Optional[str] = Field(default = None)
    current_goal: Optional[str] = Field(default = None)
    special_notes: Optional[str] = Field(default = None)


# # 工具定义
# @tool
# def add(a: int, b: int) -> int:
#     """Adds `a` and `b`.
#
#     Args:
#         a: First int
#         b: Second int
#     """
#     return a + b

def load_user_info(config: RunnableConfig) -> dict:
    # user_namespace = ("user",)
    user_id = config["configurable"].get("user_id")
    user_info = config_manager.get_user_memory(user_id)

    if user_info:
        return user_info
    else:
        return "没找到该用户"


# # 初始化RAG知识库
# def init_rag():
#     # 切分文档
#     print(f"开始初始化RAG")
#     loader = TextLoader(KNOWLEDGE_FILE, encoding = "utf-8")
#     docs = loader.load()
#     text_splitter = RecursiveCharacterTextSplitter(chunk_size = 100, chunk_overlap = 20)
#     splits = text_splitter.split_documents(docs)
#
#     # 向量化，建立Chroma矢量数据库
#     embeddings = OllamaEmbeddings(model = "nomic-embed-text")
#     vector = Chroma.from_documents(
#         documents = splits,
#         embedding = embeddings,
#         persist_directory = VECTOR_DB_DIR
#     )
#
#     retriever = vector.as_retriever(search_kwargs = {"k": 2})
#     print(f"初始化RAG完成")
#     return retriever


# # 参数问题（是否压平）
# @tool
# def save_user_info(
#         # user_info: UserInfo,
#         config: RunnableConfig,
#         name: Optional[str] = None,
#         hobbies: Optional[list] = None
# ) -> str:
#     """当用户在对话中提到或修改了他们的名字、爱好、兴趣等个人信息时，你必须立即使用此工具保存。"""
#     user_info = {
#         "name": name,
#         "hobbies": hobbies
#     }
#
#     # user_namespace = ("user",)
#     user_id = config["configurable"].get("user_id")
#     config_manager.update_user_memory(user_id, user_info)
#     # store.put(user_namespace, user_id, user_info)
#     return "保存用户信息成功"


# 参数问题（是否压平）
async def save_user_info(model, config: RunnableConfig, memory: list) -> str:
    user_id = config["configurable"].get("user_id")
    user_old_info = load_user_info(config)

    update_prompt = f"这是用户的画像：{user_old_info}\n，这是用户本次对话历史{memory}。\n请根据以上对话历史更新用户画像，并只以JSON格式输出"

    try:
        structured_model = model.with_structured_output(UserInfo)
        user_new_info = await structured_model.ainvoke([HumanMessage(content = update_prompt)])  # 原生model

        user_new_info_dict = user_new_info.model_dump(exclude_none = True)  # 过滤空字段

        if user_new_info_dict:
            config_manager.update_user_memory(user_id, user_new_info_dict)
            return f"保存用户信息成功"

        else:
            return f"未提取到需要更新的信息"

    except Exception as e:
        return f"更新记忆时发生未知错误:{e}"


# @tool
# def search_knowledge(query: str) -> str:
#     """
#     当你需要回答用户公司的相关信息时，必须使用此工具进行检索。
#
#     Args:
#         query: 用户的查询关键字或问题。
#     """
#     retriever = init_rag()
#     print(f"正在检索数据库")
#     docs = retriever.invoke(query)
#
#     if not docs:
#         print(f"没有检索到数据")
#
#     context = "\n".join([doc.page_content for doc in docs])
#     return f"以下是从本地知识库检索到的参考信息，请务必基于这些信息回答用户，如果信息不相关请忽略{context}"


model = ChatOpenAI(
    model = "/mnt/data/LLM_MODELS/Qwen2.5-3B-Instruct",
    base_url = "http://localhost:8001/v1",
    api_key = "not-needed",
    temperature = 0.7,
)


# # 绑定工具
# tools = [save_user_info, search_knowledge]
# tools_by_name = {tool.name: tool for tool in tools}
# model_with_tools = model.bind_tools(tools)


# 定义llm节点
async def llm_call(state: dict, config: RunnableConfig):
    user_id = config["configurable"].get("user_id")
    print(user_id)
    user_memory = config_manager.get_user_memory(user_id)

    system_prompt = config_manager.build_system_prompt(user_memory)

    response = await model.ainvoke(
        [SystemMessage(content = system_prompt)] + state["messages"]
    )

    print(state["messages"])

    return {
        "messages": [response],
        "llm_calls": state.get('llm_calls', 0) + 1
    }


# # 定义工具节点
# async def tool_node(state: dict, config: RunnableConfig):
#     result = []
#     last_message = state["messages"][-1]
#
#     # context = state.get("context")
#
#     for tool_call in last_message.tool_calls:
#         tool = tools_by_name[tool_call["name"]]  # 找到工具
#         # runtime = ToolRuntime(context = context, store = None)
#
#         try:
#             # 尝试调用工具
#             observation = await tool.ainvoke(tool_call["args"], config = config)
#         except Exception as e:
#             observation = f"调用工具失败: {str(e)}。请检查参数是否正确。"
#
#         message = ToolMessage(
#             content = str(observation),
#             tool_call_id = tool_call["id"]
#         )
#
#         result.append(message)
#
#     return {
#         "messages": result
#     }


# # 定义动态路由控制流
# def should_continue(state: MessageState) -> Literal["tool_node", END]:
#     messages = state["messages"]
#     last_message = state["messages"][-1]
#
#     if last_message.tool_calls:
#         return "tool_node"
#
#     return END


# 自定义llm处理器，继承自pipecat的FrameProcessor
class LangGraphProcessor(FrameProcessor):
    def __init__(self, agent, config: dict):
        super().__init__()
        self.agent = agent
        self.config = config
        self._current_task: asyncio.Task | None = None
        print(f"LangGraphService初始化成功")

    async def process_frame(self, frame, direction: FrameDirection):

        await super().process_frame(frame, direction)

        # 收到打断帧：取消正在跑的 LLM 协程
        if isinstance(frame, InterruptionFrame):
            if self._current_task and not self._current_task.done():
                self._current_task.cancel()
                print(f"LLM 被打断，取消生成")

        # 拦截处理LLMContextFrame帧
        if isinstance(frame, LLMContextFrame):
            message = frame.context.messages
            if message and message[-1]["role"] == "user":
                user_last_message = message[-1]["content"].strip()

                if user_last_message:
                    self._current_task = asyncio.create_task(
                        self._run_langgraph(user_last_message)
                    )

            return

        await super().push_frame(frame, direction)

    # 调用大模型
    async def _run_langgraph(self, user_context: str):
        complete_response = ""
        try:
            inputs = {"messages": [HumanMessage(content = user_context)]}
            print(f"LangGraph思考中")

            await self.push_frame(LLMFullResponseStartFrame())

            async for chunk, metadata in self.agent.astream(
                    inputs,
                    config = self.config,
                    stream_mode = "messages"
            ):
                if chunk.content and isinstance(chunk.content, str):
                    text_chunk = chunk.content
                    complete_response += text_chunk
                    await self.push_frame(LLMTextFrame(text_chunk))

            print(f"完整输出：{complete_response}")
            await self.push_frame(LLMFullResponseEndFrame())

        except asyncio.CancelledError:
            await self.push_frame(LLMFullResponseEndFrame())
            print(f"LLM 生成已取消")

        except Exception as e:
            await self.push_frame(LLMFullResponseEndFrame())
            print(e)


# 构建Graph
def create_agent():
    agent_builder = StateGraph(MessageState)

    agent_builder.add_node("llm_call", llm_call)

    agent_builder.add_edge(START, "llm_call")
    agent_builder.add_edge("llm_call", END)

    checkpoint = InMemorySaver()
    agent = agent_builder.compile(
        checkpoint,
    )

    return agent, checkpoint


async def run_bot(websocket: WebSocket, session_id: str, user_id: str = "user_1"):
    vad_analyzer = SileroVADAnalyzer(
        params = VADParams(
            stop_secs = 0.6,
            min_volume = 0.01,
            start_secs = 0.1
        ))

    # 替换为 WebSocket Transport
    # STT Whisper 默认需要 16000，你的 TTS 自定义输出是 24000
    transport = FastAPIWebsocketTransport(
        websocket = websocket,
        params = FastAPIWebsocketParams(
            audio_in_enabled = True,
            audio_out_enabled = True,
            add_wav_header = False,
            audio_in_sample_rate = 16000,
            audio_out_sample_rate = 24000,
            serializer = RawPCMSerializer()
        )
    )

    stt = WhisperSTTService(
        model = "/mnt/data/STT_MODLES/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120",
        device = "cuda",
        language = "zh"
    )
    tts = OpenAITTSService(
        api_key = "null",
        base_url = "http://localhost:8000/v1",  # 你的自定义 TTS 服务
        voice = "alloy",
        model = "tts-1",
    )

    agent, checkpoint = create_agent()
    # 每次连接生成独立的 thread_id
    config = {"configurable": {"thread_id": f"thread_{session_id}", "user_id": user_id}}
    langgraph_llm_service = LangGraphProcessor(agent, config)

    user_aggregator_params = LLMUserAggregatorParams(vad_analyzer = vad_analyzer)
    context = LLMContext([])
    context_aggregator = LLMContextAggregatorPair(context = context, user_params = user_aggregator_params)
    sentence_aggregator = FastSentenceAggregator()

    pipeline = Pipeline([
        transport.input(),
        stt,
        context_aggregator.user(),
        langgraph_llm_service,
        sentence_aggregator,
        tts,
        transport.output()
    ])

    task = PipelineTask(pipeline)
    runner = PipelineRunner()

    try:
        print(f"[{session_id}] 会话已建立，启动 Pipeline...")
        await runner.run(task)
    except WebSocketDisconnect:
        print(f"[{session_id}] 用户断开连接。")
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        await task.cancel()
        current_state = agent.get_state(config)
        memory_messages = current_state.values.get("messages", []) if current_state else []
        if memory_messages:
            result = await save_user_info(model, config, memory_messages)
            print(f"[{session_id}] 记忆更新结果: {result}")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    # 用客户端信息做一个简单的 Session ID
    session_id = f"{websocket.client.host}:{websocket.client.port}"
    await run_bot(websocket, session_id)


@app.api_route("/", methods=["GET", "POST", "HEAD"])
async def root():
    with open("index.html", "r", encoding = "utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content = html_content)


@app.api_route("/health", methods=["GET", "POST", "HEAD"])
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    print("启动 Web 语音服务...")
    uvicorn.run("main:app", host = "0.0.0.0", port = 8002, reload = False)
