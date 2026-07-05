"""Java executor stub â€” TODO: implement."""

from thinkdome.executors.base import BaseExecutor, ExecRequest, ExecResult


class JavaExecutor(BaseExecutor):
    async def initialize(self) -> None:
        pass

    async def execute(self, request: ExecRequest) -> ExecResult:
        return ExecResult(stdout="", stderr="Java execution is not yet implemented", exit_code=1)

    async def shutdown(self) -> None:
        pass

    async def health_check(self) -> bool:
        return False
