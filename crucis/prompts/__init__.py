"""Jinja2 template engine for Crucis LLM prompts."""

from jinja2 import Environment, PackageLoader

from crucis.prompts._filters import bool_label, path_to_module, readable_name

NONE_PLACEHOLDER = "  (none)"
NOT_SPECIFIED = "not specified"


def _create_environment() -> Environment:
    """Create and configure the Jinja2 template environment.

    Returns:
        Configured Jinja2 Environment.
    """
    env = Environment(
        loader=PackageLoader("crucis.prompts", "templates"),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
        autoescape=False,
    )
    env.filters["path_to_module"] = path_to_module
    env.filters["bool_label"] = bool_label
    env.filters["readable_name"] = readable_name
    env.globals["NONE_PLACEHOLDER"] = NONE_PLACEHOLDER
    env.globals["NOT_SPECIFIED"] = NOT_SPECIFIED
    return env


_env = _create_environment()


def render(template_name: str, **kwargs) -> str:
    """Render a named prompt template with the given context.

    Args:
        template_name: Template filename (e.g. ``generation.jinja2``).
        **kwargs: Context variables passed to the template.

    Returns:
        Rendered prompt text.
    """
    template = _env.get_template(template_name)
    return template.render(**kwargs)
