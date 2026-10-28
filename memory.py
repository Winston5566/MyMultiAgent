
import json
from pathlib import Path


class SharedMemory:

    def __init__(self):
        self.data = {
            "task": "",
            "plan": [],
            "results": {},
            "step_status": {},
            "status": "pending"
        }

    def set_task(self, task):
        self.data["task"] = task

    def set_plan(self, plan):
        self.data["plan"] = plan

    def save_result(self, agent_name, result):
        self.data["results"][agent_name] = result

    def get_result(self, agent_name):
        return self.data["results"].get(agent_name)

    def get_all(self):
        return self.data

    def save_to_file(self, filename="memory.json"):
        path = Path(__file__).resolve().parent / filename

        with path.open("w", encoding="utf-8") as f:
            json.dump(
                self.data,
                f,
                ensure_ascii=False,
                indent=4
            )

    def set_status(self, status):
        allowed = {
            "pending",
            "running",
            "completed",
            "failed"
        }

        if status not in allowed:
            raise ValueError("无效的任务状态")

        self.data["status"] = status

    def set_step_status(self, agent_name, status):
        allowed = {
            "pending",
            "running",
            "completed",
            "failed"
        }

        if status not in allowed:
            raise ValueError("无效的步骤状态")

        self.data["step_status"][agent_name] = status
