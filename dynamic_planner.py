
import json

from my_agent import Agent
from scheduler import TaskScheduler


class DynamicPlanner:

    def __init__(self):

        self.agent = Agent(
            name="动态任务规划经理",
            instructions=(
                "你是多智能体任务规划经理。"
                "可用Agent只有finance、risk、writer。"
                "finance负责财务计算。"
                "risk负责采购风险分析。"
                "writer负责汇总报告。"
                "你只负责规划，不负责执行。"
                "description只能描述任务，不能提前给出结果。"
                "必须根据用户需求选择Agent。"
                "如果需要writer，它必须依赖所有选中的前序Agent。"
                "不能出现未知Agent或循环依赖。"
                "只输出合法JSON对象，不要Markdown代码块。"
                '格式：{"tasks":{"agent_name":'
                '{"description":"任务说明",'
                '"depends_on":[]}}}'
            )
        )

    def validate_plan(self, response, required_agents=None):

        # 第1层：验证JSON格式
        plan = json.loads(response)

        if not isinstance(plan, dict):
            raise ValueError("计划必须是JSON对象")

        tasks = plan.get("tasks")

        if not isinstance(tasks, dict) or not tasks:
            raise ValueError("计划缺少有效的tasks")

        # 第2层：验证Agent名称
        allowed_agents = {"finance", "risk", "writer"}

        if not set(tasks).issubset(allowed_agents):
            raise ValueError("计划包含未知Agent")

        # 验证用户明确要求的Agent是否齐全
        required_agents = set(required_agents or [])

        if not required_agents.issubset(allowed_agents):
            raise ValueError("required_agents包含未知Agent")

        missing = required_agents - set(tasks)

        if missing:
            raise ValueError(
                f"计划缺少必要Agent：{sorted(missing)}"
            )

        # 第3层：验证任务结构
        for name, info in tasks.items():

            if not isinstance(info, dict):
                raise ValueError(f"{name}的配置格式错误")

            description = info.get("description")
            dependencies = info.get("depends_on")

            if (
                not isinstance(description, str)
                or not description.strip()
            ):
                raise ValueError(f"{name}缺少任务描述")

            if not isinstance(dependencies, list):
                raise ValueError(f"{name}的依赖必须是列表")

            if any(
                not isinstance(dep, str)
                for dep in dependencies
            ):
                raise ValueError(f"{name}的依赖名称必须是字符串")

            if len(dependencies) != len(set(dependencies)):
                raise ValueError(f"{name}存在重复依赖")

            if name in dependencies:
                raise ValueError(f"{name}不能依赖自己")

            if name == "writer":

                expected = set(tasks) - {"writer"}

                if set(dependencies) != expected:
                    raise ValueError(
                        "writer必须依赖所有选中的前序Agent"
                    )

        # 第4层：验证依赖图
        scheduler = TaskScheduler(tasks)

        scheduler.build_schedule()

        return tasks

    def create_plan(
        self,
        user_task,
        max_attempts=3,
        required_agents=None
    ):

        if max_attempts < 1:
            raise ValueError("max_attempts必须大于0")

        feedback = ""
        last_error = None

        for attempt in range(1, max_attempts + 1):

            print(
                f"\n===== Manager第{attempt}次规划 ====="
            )

            prompt = (
                f"用户任务：{user_task}\n"
                "请生成符合要求的JSON任务计划。"
            )

            if required_agents:
                prompt += (
                    "\n必须包含这些Agent："
                    + ", ".join(sorted(required_agents))
                )

            # 如果之前失败，把错误反馈给Manager
            if feedback:
                prompt += (
                    "\n上一次计划验证失败。"
                    "\n请根据以下错误重新规划：\n"
                    + feedback
                )

            # 调用大模型
            response = self.agent.run(prompt)

            try:

                tasks = self.validate_plan(
                    response,
                    required_agents=required_agents
                )

                print("任务计划验证成功！")

                return tasks

            except (ValueError, TypeError) as e:

                last_error = e

                print(f"计划验证失败：{e}")

                feedback = (
                    f"错误原因：{e}\n"
                    f"上次输出：{response[:2000]}\n"
                    "请重新生成完整、合法的JSON计划。"
                    "不要添加解释或Markdown代码块。"
                )

        raise RuntimeError(
            f"Manager连续{max_attempts}次规划失败"
        ) from last_error
