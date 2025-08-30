import time
from loguru import logger


class Limiter:
    start_time: float
    max_minutes: int
    transitions_count: int
    max_transitions: int

    @staticmethod
    def format_duration(seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @classmethod
    def init(cls, max_minutes: int, max_transitions: int):
        cls.start_time = time.time()
        cls.max_minutes = max_minutes
        cls.transitions_count = 0
        cls.max_transitions = max_transitions

    @classmethod
    def check_max_transitions(cls):
        if cls.transitions_count >= cls.max_transitions:
            logger.error("[Limiter] Max transitions reached: {}", cls.max_transitions)
            return True
        else:
            logger.info("[Limiter] Transitions: {}/{}", cls.transitions_count, cls.max_transitions)
            return False

    @classmethod
    def check_max_time(cls):
        duration = time.time() - cls.start_time
        if duration > cls.max_minutes * 60:
            logger.error("[Limiter] Max explore time reached: {}", cls.format_duration(duration))
            return True
        else:
            logger.info("[Limiter] Explore time: {}", cls.format_duration(duration))
            return False

    @classmethod
    def time_consumption(cls):
        return cls.format_duration(time.time() - cls.start_time)
