
import copy
import json
import os
import time
from monitor import AgentMonitor
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed
)

from checkpoint import (
    save_checkpoint,
    load_checkpoint
)

from dynamic_planner import DynamicPlanner
from scheduler import TaskScheduler
from memory import SharedMemory
from multi_agent import (
    finance_agent,
    risk_agent,
    writer_agent
)

default_task = (
    "采购20只800G光模块，单价2800元，"
    "供应商提供九折优惠。"
    "请计算采购金额、分析风险并生成报告。"
)

user_task = os.getenv(
    "MULTIAGENT_TASK",
    default_task
)

agents = {
    "finance": finance_agent,
    "risk": risk_agent,
    "writer": writer_agent
}

required_agents = set()

MAX_RETRIES = 2
MAX_WORKERS = 2


# 保存各Agent的初始对话历史
initial_messages = {
    name: copy.deepcopy(agent.messages)
    for name, agent in agents.items()
}



def execute_with_retry(agent_name, task_text):

    agent = agents[agent_name]

    for attempt in range(1, MAX_RETRIES + 1):

        print(f"[{agent_name}] 第 {attempt} 次执行")

        def run_once():

            # 恢复初始对话状态
            agent.messages = copy.deepcopy(
                initial_messages[agent_name]
            )

            # 模拟故障，用于测试
            if (
                os.getenv("SIMULATE_RISK_FAILURE") == "1"
                and agent_name == "risk"
            ):
                raise RuntimeError("模拟Risk执行失败")

            result = agent.run(task_text)

            if not isinstance(result, str) or not result.strip():
                raise ValueError("Agent返回了空结果")

            return result

        try:

            result = monitor.timed_call(
                agent_name=agent_name,
                attempt=attempt,
                func=run_once
            )

            print(f"[{agent_name}] 执行成功")

            return result

        except Exception as e:

            print(
                f"[{agent_name}] 执行失败："
                f"{type(e).__name__}: {e}"
            )

            if attempt == MAX_RETRIES:
                raise

            monitor.record(
                agent_name,
                "retry_scheduled",
                next_attempt=attempt + 1
            )

            time.sleep(2 ** (attempt - 1))

planner = DynamicPlanner()
memory = SharedMemory()

saved_state = load_checkpoint()
if saved_state is not None and saved_state.get("run_id"):
    monitor = AgentMonitor(
        run_id=saved_state["run_id"]
    )
else:
    monitor = AgentMonitor()

if saved_state is None:

    print("\n没有发现Checkpoint，创建新任务")

    tasks = planner.create_plan(
        user_task,
        max_attempts=3,
        required_agents=required_agents
    )

    memory.set_task(user_task)
    memory.set_plan(tasks)
    memory.set_status("running")

    for name in tasks:
        memory.set_step_status(name, "pending")

    memory.data["errors"] = {}
    memory.data["run_id"] = monitor.run_id

    save_checkpoint(memory.data)

else:

    print("\n发现Checkpoint，准备恢复任务")

    memory.data = saved_state

    if memory.data["task"] != user_task:
        raise ValueError(
            "Checkpoint属于其他任务，请勿直接复用"
        )

    tasks = memory.data["plan"]

    # 再次验证磁盘中的任务计划
    planner.validate_plan(
        json.dumps({"tasks": tasks}, ensure_ascii=False),
        required_agents=required_agents
    )

    # 校验完成状态与结果是否一致
    for name in tasks:
        status = memory.data["step_status"][name]

        if (
            status == "completed"
            and name not in memory.data["results"]
        ):
            raise ValueError(
                f"{name}标记完成，但缺少执行结果"
            )

    # 上次中断或失败的任务允许重新执行
    for name in tasks:

        status = memory.data["step_status"][name]

        if status in {"running", "failed"}:
            memory.set_step_status(name, "pending")

    memory.set_status("running")
    save_checkpoint(memory.data)

    print("已经恢复的任务状态：")
    print(memory.data["step_status"])

def replan_remaining(failed_agents):

    completed = {
        name
        for name, status
        in memory.data["step_status"].items()
        if status == "completed"
    }

    old_tasks = memory.data["plan"]

    replan_request = (
        f"原始用户任务：{user_task}\n\n"
        "当前完整任务计划：\n"
        f"{json.dumps(old_tasks, ensure_ascii=False)}\n\n"
        f"已经完成的Agent：{sorted(completed)}\n"
        f"执行失败的Agent：{failed_agents}\n\n"
        "请重新规划未完成任务的依赖和描述。"
        "必须保留原有全部Agent名称。"
        "已完成Agent的description和depends_on必须原样保留。"
        "不能删除已完成任务，也不能要求重新执行它们。"
        "请返回包含所有Agent的完整JSON计划。"
    )

    new_tasks = planner.create_plan(
        replan_request,
        max_attempts=2,
        required_agents=set(old_tasks)
    )

    # 不允许添加或删除Agent
    if set(new_tasks) != set(old_tasks):
        raise ValueError(
            "重新规划不能增删已有Agent"
        )

    # 已完成任务的配置不能改变
    for name in completed:

        if new_tasks[name] != old_tasks[name]:
            raise ValueError(
                f"不能修改已完成任务：{name}"
            )

    # 重新验证依赖图
    TaskScheduler(new_tasks).build_schedule()

    memory.set_plan(new_tasks)

    save_checkpoint(memory.data)

    print("\n剩余任务重新规划完成")
    print(
        json.dumps(
            new_tasks,
            ensure_ascii=False,
            indent=2
        )
    )

workflow_start = time.perf_counter()

while True:

    tasks = memory.data["plan"]

    completed = {
        name
        for name, status
        in memory.data["step_status"].items()
        if status == "completed"
    }

    # 所有任务完成，结束循环
    if len(completed) == len(tasks):
        break

    # 找出当前可以执行的任务
    ready = []

    for name, info in tasks.items():

        if name in completed:
            continue

        dependencies = info["depends_on"]

        if all(dep in completed for dep in dependencies):
            ready.append(name)

    if not ready:
        raise RuntimeError(
            "没有可执行任务，请检查任务依赖"
        )

    print("\n本轮可执行任务：", ready)

    # 固定本轮的前序结果
    context = json.dumps(
        memory.data["results"],
        ensure_ascii=False
    )

    for name in ready:
        memory.set_step_status(name, "running")

    save_checkpoint(memory.data)

    futures = {}

    with ThreadPoolExecutor(
        max_workers=min(MAX_WORKERS, len(ready))
    ) as executor:

        for name in ready:

            description = tasks[name]["description"]

            agent_task = (
                f"原始任务：{user_task}\n\n"
                f"当前职责：{description}\n\n"
                f"已经完成的结果：{context}\n\n"
                "请完成当前职责。"
            )

            future = executor.submit(
                execute_with_retry,
                name,
                agent_task
            )

            futures[future] = name

        failures = []

        for future in as_completed(futures):

            name = futures[future]

            try:

                result = future.result()

                memory.save_result(name, result)

                memory.set_step_status(
                    name, "completed"
                )

                memory.data["errors"].pop(name, None)

            except Exception as e:

                memory.set_step_status(
                    name, "failed"
                )

                memory.data["errors"][name] = (
                    f"{type(e).__name__}: {e}"
                )

                failures.append((name, e))

            # 每个Agent结束后立即保存进度
            save_checkpoint(memory.data)

    if failures:

        memory.set_status("failed")
        save_checkpoint(memory.data)

        failed_names = [
            name for name, error in failures
        ]

        print("\n执行失败的任务：", failed_names)
        print("正在尝试重新规划剩余任务...")

        try:
            replan_remaining(failed_names)

        except Exception as e:
            print(
                "重新规划未成功，保留原计划：",
                type(e).__name__,
                str(e)
            )

        print(
            "\n已保存Checkpoint。"
            "请解决故障后重新运行程序。"
        )

        raise RuntimeError(
            "工作流未完成，等待断点恢复"
        ) from failures[0][1]

memory.set_status("completed")
save_checkpoint(memory.data)

# 第28课：工作流完成后自动评分和有限次修订
from report_repair import finalize_report_with_quality
finalize_report_with_quality(
    memory.data,
    save_checkpoint=save_checkpoint,
    job_id=os.getenv("MULTIAGENT_JOB_ID") or memory.data.get("run_id"),
    threshold=90,
    max_attempts=2,
)


elapsed = time.perf_counter() - workflow_start

print("\n========== 工作流执行完成 ==========")

if "writer" in memory.data["results"]:
    print(memory.get_result("writer"))
else:
    print(memory.data["results"])

print(f"\n本次运行耗时：{elapsed:.2f} 秒")
