
import os
import json
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from token_usage import tracked_create

# 读取 API 配置
load_dotenv(Path(__file__).resolve().parent / ".env")


class Agent:

    def __init__(
        self,
        name,
        instructions,
        tools=None,
        functions=None
    ):
        # Agent 的名字
        self.name = name

        # Agent 的系统指令
        self.instructions = instructions

        # 模型可以看到的工具说明
        self.tools = tools or []

        # Python 实际执行的函数
        self.functions = functions or {}

        # 每个 Agent 拥有独立的对话历史
        self.messages = [
            {
                "role": "system",
                "content": instructions
            }
        ]

        # 连接第三方 API
        self.client = OpenAI(
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("BASE_URL"),
            timeout=60.0,
            max_retries=1
        )

        self.model = os.getenv("MODEL_NAME")

    def run(self, task, max_steps=10, job_id=None):
        # 优先使用显式传入的 job_id
        # 如果没有，就从网页任务环境变量读取

        effective_job_id = job_id or os.getenv("MULTIAGENT_JOB_ID")
        print(f"\n[{self.name}] 收到任务：{task}")

        # 保存用户任务
        self.messages.append({
            "role": "user",
            "content": task
        })

        # Agent Loop
        for step in range(max_steps):

            print(f"[{self.name}] 第 {step + 1} 轮")

            request = {
                "model": self.model,
                "messages": self.messages
            }

            # 只有存在工具时才传 tools
            if self.tools:
                request["tools"] = self.tools
                request["tool_choice"] = "auto"
            if effective_job_id:

                response = tracked_create(
                    self.client,
                    job_id=str(effective_job_id),
                    agent_name=self.name,
                    **request
                )

            # 兼容旧代码和独立测试
            else:

               response = self.client.chat.completions.create(
                     **request
               )

            message = response.choices[0].message

            # 模型没有调用工具
            if not message.tool_calls:

                answer = message.content or ""

                self.messages.append({
                    "role": "assistant",
                    "content": answer
                })

                print(f"[{self.name}] 完成任务")

                return answer

            # 保存工具调用请求
            self.messages.append(
                message.model_dump(exclude_none=True)
            )

            # 执行工具
            for tool_call in message.tool_calls:

                tool_name = tool_call.function.name

                print(f"[{self.name}] 调用工具：{tool_name}")

                if tool_name not in self.functions:
                    result = "错误：工具不存在"

                else:
                    try:
                        arguments = json.loads(
                            tool_call.function.arguments
                        )

                        if not isinstance(arguments, dict):
                            raise ValueError("参数必须是对象")

                        result = self.functions[tool_name](
                            **arguments
                        )

                    except (
                        ValueError,
                        KeyError,
                        TypeError
                    ) as e:
                        result = (
                            f"工具执行错误："
                            f"{type(e).__name__}"
                        )

                # 把结果交还模型
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(result)
                })

        raise RuntimeError(
            f"{self.name} 达到最大执行轮数，"
            "任务未完成"
        )
