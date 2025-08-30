import importlib
import inspect

import pathlib
from typing import Type

from tasks.utils import BaseTask

tasks = None


def get_task_class_by_task_name(task_name: str) -> tuple[Type[BaseTask], str]:
    tasks_dict = get_tasks_dict()
    if task_name in tasks_dict:
        return tasks_dict[task_name]
    raise Exception(f"No task class found for task name: {task_name}")


def get_tasks_dict() -> dict[str, tuple[Type[BaseTask], str]]:
    global tasks
    if tasks is None:
        tasks = {}
        current_dir = pathlib.Path(__file__).parent
        all_module_names = [
            f.stem
            for f in current_dir.glob("*.py")
            if f.name != "__init__.py" and f.name != "utils.py"
        ]
        for mod_name in all_module_names:
            mod = importlib.import_module(f".{mod_name}", package=__name__)
            apk_name: str = mod.__apk__
            new_tasks = {
                name: (c, apk_name)
                for name, c in inspect.getmembers(mod, inspect.isclass)
                if c.__module__ == mod.__name__ and name.endswith("Task")
            }
            tasks.update(new_tasks)
    return tasks
