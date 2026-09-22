"""Composition helpers for configured Chat providers."""

import logging
from dataclasses import dataclass

from chat_buddy.chat.domain import (
    GenerationConfiguration,
    GenerationParameter,
    MemoryCandidateExtractor,
    ModelDescriptor,
    ModelId,
    ProviderDescriptor,
    ProviderId,
    ProviderRegistry,
    ResponseGatewayResolver,
    ResponseGenerator,
    SummaryGenerator,
    TitleGenerator,
)
from chat_buddy.chat.infrastructure.config import settings
from chat_buddy.chat.infrastructure.llm.ollama_gateway import OllamaGateway
from chat_buddy.chat.infrastructure.llm.openai_gateway import OpenAIResponseGateway
from chat_buddy.chat.infrastructure.llm.provider_registry import (
    StaticProviderRegistry,
    StaticResponseGatewayResolver,
)
from chat_buddy.chat.infrastructure.tokenization import (
    MistralTokenCounter,
    OpenAIResponsesTokenCounter,
)

logger = logging.getLogger(__name__)

_OPENAI_MODEL_SPECS = (
    ("gpt-5.6-terra", "GPT-5.6 Terra", 1_050_000, 922_000, 128_000, 8_192),
    ("gpt-5.6-luna", "GPT-5.6 Luna", 1_050_000, 922_000, 128_000, 8_192),
    ("gpt-5.6-sol", "GPT-5.6 Sol", 1_050_000, 922_000, 128_000, 8_192),
    (
        "gpt-4.1-2025-04-14",
        "GPT-4.1 (2025-04-14)",
        1_047_576,
        None,
        32_768,
        4_096,
    ),
)


@dataclass(slots=True, frozen=True)
class ProviderRuntime:
    """Provider-neutral services constructed from infrastructure settings."""

    registry: ProviderRegistry
    response_gateway_resolver: ResponseGatewayResolver
    title_generator: TitleGenerator
    summary_generator: SummaryGenerator
    memory_candidate_extractor: MemoryCandidateExtractor


def build_provider_runtime() -> ProviderRuntime:
    """Build configured local and explicitly enabled cloud providers.

    Returns:
        Provider-neutral runtime services for application composition.
    """

    provider_id = ProviderId(settings.OLLAMA_PROVIDER_ID)
    gateway = OllamaGateway()
    providers = [
        ProviderDescriptor(
            id=provider_id,
            display_name=settings.OLLAMA_PROVIDER_NAME,
        )
    ]
    models = [
        ModelDescriptor(
            provider_id=provider_id,
            id=ModelId(model_name),
            display_name=model_name,
            context_window_tokens=settings.MODEL_CONTEXT_WINDOW,
            supports_streaming=True,
            supported_generation_parameters=frozenset(GenerationParameter),
            default_generation_configuration=GenerationConfiguration(),
            token_counter=MistralTokenCounter(),
            default_output_token_reserve=(settings.MODEL_DEFAULT_OUTPUT_TOKEN_RESERVE),
        )
        for model_name in settings.CHAT_MODELS
    ]
    gateways: dict[ProviderId, ResponseGenerator] = {provider_id: gateway}

    if settings.is_openai_enabled():
        api_key = settings.get_openai_api_key()
        if api_key is None:
            logger.warning(
                "OpenAI is enabled but CHAT_OPENAI_API_KEY is missing or blank; "
                "the provider will not be registered."
            )
        else:
            openai_id = ProviderId(settings.OPENAI_PROVIDER_ID)
            providers.append(
                ProviderDescriptor(
                    id=openai_id,
                    display_name=settings.OPENAI_PROVIDER_NAME,
                    usage_notice=(
                        "OpenAI responses are billable, send eligible Chat "
                        "context to the cloud, and run with reasoning features "
                        "disabled."
                    ),
                )
            )
            for (
                model_name,
                display_name,
                context_window,
                maximum_input,
                maximum_output,
                output_reserve,
            ) in _OPENAI_MODEL_SPECS:
                supported = {GenerationParameter.MAX_OUTPUT_TOKENS}
                if model_name.startswith("gpt-4.1-"):
                    supported.update(
                        {
                            GenerationParameter.TEMPERATURE,
                            GenerationParameter.TOP_P,
                        }
                    )
                models.append(
                    ModelDescriptor(
                        provider_id=openai_id,
                        id=ModelId(model_name),
                        display_name=display_name,
                        context_window_tokens=context_window,
                        supports_streaming=True,
                        supported_generation_parameters=frozenset(supported),
                        default_generation_configuration=GenerationConfiguration(),
                        token_counter=OpenAIResponsesTokenCounter(),
                        default_output_token_reserve=output_reserve,
                        maximum_input_tokens=maximum_input,
                        maximum_output_tokens=maximum_output,
                        application_prompt_limit=(
                            settings.OPENAI_APPLICATION_PROMPT_LIMIT
                        ),
                    )
                )
            gateways[openai_id] = OpenAIResponseGateway(api_key=api_key)

    registry = StaticProviderRegistry(
        providers=providers,
        models=models,
        default_provider_id=provider_id,
        default_model_id=ModelId(settings.CHAT_MODEL),
    )
    resolver = StaticResponseGatewayResolver(gateways)
    return ProviderRuntime(
        registry=registry,
        response_gateway_resolver=resolver,
        title_generator=gateway,
        summary_generator=gateway,
        memory_candidate_extractor=gateway,
    )
