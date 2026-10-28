
class TaskScheduler:

    def __init__(self, tasks):
        self.tasks = tasks

    def get_ready_tasks(self, completed):
        ready = []

        for task_name, task_info in self.tasks.items():

            # 已完成的任务不再执行
            if task_name in completed:
                continue

            dependencies = task_info["depends_on"]

            # 所有依赖都完成，任务才可以执行
            if all(
                dep in completed
                for dep in dependencies
            ):
                ready.append(task_name)

        return ready

    def build_schedule(self):

        completed = set()
        schedule = []

        # 检查依赖是否合法
        for task_name, task_info in self.tasks.items():

            for dep in task_info["depends_on"]:

                if dep not in self.tasks:
                    raise ValueError(
                        f"{task_name} 依赖未知任务：{dep}"
                    )

        while len(completed) < len(self.tasks):

            ready = self.get_ready_tasks(completed)

            # 没有可执行任务，说明存在循环依赖
            if not ready:
                raise ValueError(
                    "无法继续调度，可能存在循环依赖"
                )

            schedule.append(ready)

            # 当前阶段全部完成后进入下一阶段
            completed.update(ready)

        return schedule
