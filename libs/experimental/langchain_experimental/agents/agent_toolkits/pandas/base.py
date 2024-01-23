"""Agent for working with pandas objects."""
from typing import Any, Dict, List, Optional, Sequence, Tuple, Literal, Union

from langchain.agents import create_openai_tools_agent, create_react_agent
from langchain.agents.agent import AgentExecutor, BaseSingleActionAgent
from langchain.agents.mrkl.base import ZeroShotAgent
from langchain.agents.openai_functions_agent.base import OpenAIFunctionsAgent, \
    create_openai_functions_agent
from langchain.agents.types import AgentType
from langchain.callbacks.base import BaseCallbackManager
from langchain.chains.llm import LLMChain
from langchain.schema import BasePromptTemplate
from langchain.tools import BaseTool
from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import SystemMessage
from langchain_core.runnables import Runnable

from langchain_experimental.agents.agent_toolkits.pandas.prompt import (
    FUNCTIONS_WITH_DF,
    FUNCTIONS_WITH_MULTI_DF,
    MULTI_DF_PREFIX,
    MULTI_DF_PREFIX_FUNCTIONS,
    PREFIX,
    PREFIX_FUNCTIONS,
    SUFFIX_NO_DF,
    SUFFIX_WITH_DF,
    SUFFIX_WITH_MULTI_DF,
)
from langchain_experimental.tools.python.tool import PythonAstREPLTool


def _get_multi_prompt(
    dfs: List[Any],
    prefix: Optional[str] = None,
    suffix: Optional[str] = None,
    input_variables: Optional[List[str]] = None,
    include_df_in_prompt: Optional[bool] = True,
    number_of_head_rows: int = 5,
    extra_tools: Sequence[BaseTool] = (),
) -> Tuple[BasePromptTemplate, List[BaseTool]]:
    num_dfs = len(dfs)
    if suffix is not None:
        suffix_to_use = suffix
        include_dfs_head = True
    elif include_df_in_prompt:
        suffix_to_use = SUFFIX_WITH_MULTI_DF
        include_dfs_head = True
    else:
        suffix_to_use = SUFFIX_NO_DF
        include_dfs_head = False
    if input_variables is None:
        input_variables = ["input", "agent_scratchpad", "num_dfs"]
        if include_dfs_head:
            input_variables += ["dfs_head"]

    if prefix is None:
        prefix = MULTI_DF_PREFIX

    df_locals = {}
    for i, dataframe in enumerate(dfs):
        df_locals[f"df{i + 1}"] = dataframe
    tools = [PythonAstREPLTool(locals=df_locals)] + list(extra_tools)
    prompt = ZeroShotAgent.create_prompt(
        tools,
        prefix=prefix,
        suffix=suffix_to_use,
        input_variables=input_variables,
    )
    partial_prompt = prompt.partial()
    if "dfs_head" in input_variables:
        dfs_head = "\n\n".join([d.head(number_of_head_rows).to_markdown() for d in dfs])
        partial_prompt = partial_prompt.partial(num_dfs=str(num_dfs), dfs_head=dfs_head)
    if "num_dfs" in input_variables:
        partial_prompt = partial_prompt.partial(num_dfs=str(num_dfs))
    return partial_prompt, tools


def _get_single_prompt(
    df: Any,
    prefix: Optional[str] = None,
    suffix: Optional[str] = None,
    input_variables: Optional[List[str]] = None,
    include_df_in_prompt: Optional[bool] = True,
    number_of_head_rows: int = 5,
    extra_tools: Sequence[BaseTool] = (),
) -> Tuple[BasePromptTemplate, List[BaseTool]]:
    if suffix is not None:
        suffix_to_use = suffix
        include_df_head = True
    elif include_df_in_prompt:
        suffix_to_use = SUFFIX_WITH_DF
        include_df_head = True
    else:
        suffix_to_use = SUFFIX_NO_DF
        include_df_head = False

    if input_variables is None:
        input_variables = ["input", "agent_scratchpad"]
        if include_df_head:
            input_variables += ["df_head"]

    if prefix is None:
        prefix = PREFIX

    tools = [PythonAstREPLTool(locals={"df": df})] + list(extra_tools)

    prompt = ZeroShotAgent.create_prompt(
        tools,
        prefix=prefix,
        suffix=suffix_to_use,
        input_variables=input_variables,
    )

    partial_prompt = prompt.partial()
    if "df_head" in input_variables:
        partial_prompt = partial_prompt.partial(
            df_head=str(df.head(number_of_head_rows).to_markdown())
        )
    return partial_prompt, tools


def _get_prompt_and_tools(
    df: Any,
    prefix: Optional[str] = None,
    suffix: Optional[str] = None,
    input_variables: Optional[List[str]] = None,
    include_df_in_prompt: Optional[bool] = True,
    number_of_head_rows: int = 5,
    extra_tools: Sequence[BaseTool] = (),
) -> Tuple[BasePromptTemplate, List[BaseTool]]:
    try:
        import pandas as pd

        pd.set_option("display.max_columns", None)
    except ImportError:
        raise ImportError(
            "pandas package not found, please install with `pip install pandas`"
        )

    if include_df_in_prompt is not None and suffix is not None:
        raise ValueError("If suffix is specified, include_df_in_prompt should not be.")

    if isinstance(df, list):
        for item in df:
            if not isinstance(item, pd.DataFrame):
                raise ValueError(f"Expected pandas object, got {type(df)}")
        return _get_multi_prompt(
            df,
            prefix=prefix,
            suffix=suffix,
            input_variables=input_variables,
            include_df_in_prompt=include_df_in_prompt,
            number_of_head_rows=number_of_head_rows,
            extra_tools=extra_tools,
        )
    else:
        if not isinstance(df, pd.DataFrame):
            raise ValueError(f"Expected pandas object, got {type(df)}")
        return _get_single_prompt(
            df,
            prefix=prefix,
            suffix=suffix,
            input_variables=input_variables,
            include_df_in_prompt=include_df_in_prompt,
            number_of_head_rows=number_of_head_rows,
            extra_tools=extra_tools,
        )


def _get_functions_single_prompt(
    df: Any,
    prefix: Optional[str] = None,
    suffix: Optional[str] = None,
    include_df_in_prompt: Optional[bool] = True,
    number_of_head_rows: int = 5,
) -> Tuple[BasePromptTemplate, List[PythonAstREPLTool]]:
    if suffix is not None:
        suffix_to_use = suffix
        if include_df_in_prompt:
            suffix_to_use = suffix_to_use.format(
                df_head=str(df.head(number_of_head_rows).to_markdown())
            )
    elif include_df_in_prompt:
        suffix_to_use = FUNCTIONS_WITH_DF.format(
            df_head=str(df.head(number_of_head_rows).to_markdown())
        )
    else:
        suffix_to_use = ""

    if prefix is None:
        prefix = PREFIX_FUNCTIONS

    tools = [PythonAstREPLTool(locals={"df": df})]
    system_message = SystemMessage(content=prefix + suffix_to_use)
    prompt = OpenAIFunctionsAgent.create_prompt(system_message=system_message)
    return prompt, tools


def _get_functions_multi_prompt(
    dfs: Any,
    prefix: Optional[str] = None,
    suffix: Optional[str] = None,
    include_df_in_prompt: Optional[bool] = True,
    number_of_head_rows: int = 5,
) -> Tuple[BasePromptTemplate, List[PythonAstREPLTool]]:
    if suffix is not None:
        suffix_to_use = suffix
        if include_df_in_prompt:
            dfs_head = "\n\n".join(
                [d.head(number_of_head_rows).to_markdown() for d in dfs]
            )
            suffix_to_use = suffix_to_use.format(
                dfs_head=dfs_head,
            )
    elif include_df_in_prompt:
        dfs_head = "\n\n".join([d.head(number_of_head_rows).to_markdown() for d in dfs])
        suffix_to_use = FUNCTIONS_WITH_MULTI_DF.format(
            dfs_head=dfs_head,
        )
    else:
        suffix_to_use = ""

    if prefix is None:
        prefix = MULTI_DF_PREFIX_FUNCTIONS
    prefix = prefix.format(num_dfs=str(len(dfs)))

    df_locals = {}
    for i, dataframe in enumerate(dfs):
        df_locals[f"df{i + 1}"] = dataframe
    tools = [PythonAstREPLTool(locals=df_locals)]
    system_message = SystemMessage(content=prefix + suffix_to_use)
    prompt = OpenAIFunctionsAgent.create_prompt(system_message=system_message)
    return prompt, tools


def _get_functions_prompt_and_tools(
    df: Any,
    prefix: Optional[str] = None,
    suffix: Optional[str] = None,
    input_variables: Optional[List[str]] = None,
    include_df_in_prompt: Optional[bool] = True,
    number_of_head_rows: int = 5,
) -> Tuple[BasePromptTemplate, List[PythonAstREPLTool]]:
    try:
        import pandas as pd

        pd.set_option("display.max_columns", None)
    except ImportError:
        raise ImportError(
            "pandas package not found, please install with `pip install pandas`"
        )
    if input_variables is not None:
        raise ValueError("`input_variables` is not supported at the moment.")

    if include_df_in_prompt is not None and suffix is not None:
        raise ValueError("If suffix is specified, include_df_in_prompt should not be.")

    if isinstance(df, list):
        for item in df:
            if not isinstance(item, pd.DataFrame):
                raise ValueError(f"Expected pandas object, got {type(df)}")
        return _get_functions_multi_prompt(
            df,
            prefix=prefix,
            suffix=suffix,
            include_df_in_prompt=include_df_in_prompt,
            number_of_head_rows=number_of_head_rows,
        )
    else:
        if not isinstance(df, pd.DataFrame):
            raise ValueError(f"Expected pandas object, got {type(df)}")
        return _get_functions_single_prompt(
            df,
            prefix=prefix,
            suffix=suffix,
            include_df_in_prompt=include_df_in_prompt,
            number_of_head_rows=number_of_head_rows,
        )


def create_pandas_dataframe_agent(
    llm: BaseLanguageModel,
    df: Any,
    agent_type: Union[AgentType, Literal["openai-tools"]] = AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    callback_manager: Optional[BaseCallbackManager] = None,
    prefix: Optional[str] = None,
    suffix: Optional[str] = None,
    input_variables: Optional[List[str]] = None,
    verbose: bool = False,
    return_intermediate_steps: bool = False,
    max_iterations: Optional[int] = 15,
    max_execution_time: Optional[float] = None,
    early_stopping_method: str = "force",
    agent_executor_kwargs: Optional[Dict[str, Any]] = None,
    include_df_in_prompt: Optional[bool] = True,
    number_of_head_rows: int = 5,
    extra_tools: Sequence[BaseTool] = (),
    **kwargs: Dict[str, Any],
) -> AgentExecutor:
    """Construct a pandas agent from an LLM and dataframe(s).
    
    Args:
        llm: Language model to use for the agent.
        df: Pandas dataframe or list of Pandas dataframes.
        agent_type: One of "openai-tools", "openai-functions", or
            "zero-shot-react-description". Defaults to "zero-shot-react-description".
            "openai-tools" is recommended over "openai-functions".
        callback_manager: DEPRECATED. Pass "callbacks" key into 'agent_executor_kwargs'
            instead to pass constructor callbacks to AgentExecutor.
        prefix: Prompt prefix string.
        suffix: Prompt suffix string.
        input_variables:
        verbose: AgentExecutor verbosity.
        return_intermediate_steps:
        max_iterations: Passed to AgentExecutor init.
        max_execution_time: Passed to AgentExecutor init.
        early_stopping_method: Passed to AgentExecutor init.
        agent_executor_kwargs: Arbitrary additional AgentExecutor args.
        include_df_in_prompt:
        number_of_head_rows:
        extra_tools: Additional tools to give to agent on top of the ones that come with
            SQLDatabaseToolkit.
        **kwargs: 

    Returns:
        An AgentExecutor with the specified agent_type agent.

    Example:

        .. code-block:: python

        from langchain_openai import ChatOpenAI
        from langchain_experimental.agents import create_pandas_dataframe_agent
        import pandas as pd

        df = pd.read_csv("titanic.csv")
        llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0)
        agent_executor = create_sql_agent(llm, db, agent_type="openai-tools", verbose=True)

    """  # noqa: E501
    if agent_type == AgentType.ZERO_SHOT_REACT_DESCRIPTION:
        prompt, tools = _get_prompt_and_tools(
            df,
            prefix=prefix,
            suffix=suffix,
            input_variables=input_variables,
            include_df_in_prompt=include_df_in_prompt,
            number_of_head_rows=number_of_head_rows,
            extra_tools=extra_tools,
        )
        agent: Union[BaseSingleActionAgent, Runnable] = create_react_agent(llm, tools, prompt)
    elif agent_type == AgentType.OPENAI_FUNCTIONS:
        prompt, base_tools = _get_functions_prompt_and_tools(
            df,
            prefix=prefix,
            suffix=suffix,
            input_variables=input_variables,
            include_df_in_prompt=include_df_in_prompt,
            number_of_head_rows=number_of_head_rows,
        )
        tools = list(base_tools) + list(extra_tools)
        agent = create_openai_functions_agent(llm, tools, prompt)
    elif agent_type == "openai-tools":
        prompt, base_tools = _get_functions_prompt_and_tools(
            df,
            prefix=prefix,
            suffix=suffix,
            input_variables=input_variables,
            include_df_in_prompt=include_df_in_prompt,
            number_of_head_rows=number_of_head_rows,
        )
        tools = list(base_tools) + list(extra_tools)
        agent = create_openai_tools_agent(llm, tools, prompt)
    else:
        raise ValueError(f"Agent type {agent_type} not supported at the moment.")
    return AgentExecutor.from_agent_and_tools(
        agent=agent,
        tools=tools,
        callback_manager=callback_manager,
        verbose=verbose,
        return_intermediate_steps=return_intermediate_steps,
        max_iterations=max_iterations,
        max_execution_time=max_execution_time,
        early_stopping_method=early_stopping_method,
        **(agent_executor_kwargs or {}),
    )
