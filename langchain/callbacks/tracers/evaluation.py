"""A tracer that runs evaluators over completed runs."""
import logging
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import Any, Optional, Sequence, Set, Union
from uuid import UUID

# from langchainplus_sdk import LangChainPlusClient, RunEvaluator

from langchain.callbacks.manager import tracing_v2_enabled
from langchain.callbacks.tracers.base import BaseTracer
from langchain.callbacks.tracers.schemas import Run

logger = logging.getLogger(__name__)


class LangChainPlusClient:
    pass


class RunEvaluator:
    pass


class EvaluatorCallbackHandler(BaseTracer):
    """A tracer that runs a run evaluator whenever a run is persisted.

    Parameters
    ----------
    evaluators : Sequence[RunEvaluator]
        The run evaluators to apply to all top level runs.
    max_workers : int, optional
        The maximum number of worker threads to use for running the evaluators.
        If not specified, it will default to the number of evaluators.
    client : LangChainPlusClient, optional
        The LangChainPlusClient instance to use for evaluating the runs.
        If not specified, a new instance will be created.
    example_id : Union[UUID, str], optional
        The example ID to be associated with the runs.
    project_name : str, optional
        The LangSmith project name to be organize eval chain runs under.

    Attributes
    ----------
    example_id : Union[UUID, None]
        The example ID associated with the runs.
    client : LangChainPlusClient
        The LangChainPlusClient instance used for evaluating the runs.
    evaluators : Sequence[RunEvaluator]
        The sequence of run evaluators to be executed.
    executor : ThreadPoolExecutor
        The thread pool executor used for running the evaluators.
    futures : Set[Future]
        The set of futures representing the running evaluators.
    skip_unfinished : bool
        Whether to skip runs that are not finished or raised
        an error.
    project_name : Optional[str]
        The LangSmith project name to be organize eval chain runs under.
    """

    name = "evaluator_callback_handler"

    def __init__(
        self,
        evaluators: Sequence[RunEvaluator],
        max_workers: Optional[int] = None,
        client: Optional[LangChainPlusClient] = None,
        example_id: Optional[Union[UUID, str]] = None,
        skip_unfinished: bool = True,
        project_name: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.example_id = (
            UUID(example_id) if isinstance(example_id, str) else example_id
        )
        self.client = client or LangChainPlusClient()
        self.evaluators = evaluators
        self.executor = ThreadPoolExecutor(
            max_workers=max(max_workers or len(evaluators), 1)
        )
        self.futures: Set[Future] = set()
        self.skip_unfinished = skip_unfinished
        self.project_name = project_name

    def _evaluate_in_project(self, run: Run, evaluator: RunEvaluator) -> None:
        """Evaluate the run in the project.

        Parameters
        ----------
        run : Run
            The run to be evaluated.
        evaluator : RunEvaluator
            The evaluator to use for evaluating the run.

        """
        try:
            if self.project_name is None:
                self.client.evaluate_run(run, evaluator)
            with tracing_v2_enabled(project_name=self.project_name, tags=["eval"]):
                self.client.evaluate_run(run, evaluator)
        except Exception as e:
            logger.error(
                f"Error evaluating run {run.id} with "
                f"{evaluator.__class__.__name__}: {e}",
                exc_info=True,
            )
            raise e

    def _persist_run(self, run: Run) -> None:
        """Run the evaluator on the run.

        Parameters
        ----------
        run : Run
            The run to be evaluated.

        """
        if self.skip_unfinished and not run.outputs:
            logger.debug(f"Skipping unfinished run {run.id}")
            return
        run_ = run.copy()
        run_.reference_example_id = self.example_id
        for evaluator in self.evaluators:
            self.futures.add(
                self.executor.submit(self._evaluate_in_project, run_, evaluator)
            )

    def wait_for_futures(self) -> None:
        """Wait for all futures to complete."""
        futures = list(self.futures)
        wait(futures)
        for future in futures:
            self.futures.remove(future)
