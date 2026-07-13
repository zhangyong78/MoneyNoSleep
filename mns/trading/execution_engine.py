class ExecutionEngine:
    def submit(self, *args, **kwargs):
        raise RuntimeError("Live execution is disabled in phase 1.")
