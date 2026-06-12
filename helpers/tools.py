import base64
import inspect
import io
import re
import typing

import numpy as np
from PIL import Image

import helpers.model as helpers_model


# ------------------------------------------------------------------ schema building

def _python_type_to_json(hint: typing.Any) -> str:
    """Map a Python type annotation to a JSON-schema type string."""
    origin = getattr(hint, "__origin__", None)
    args = getattr(hint, "__args__", ())

    # Unwrap Optional[X] → X
    if origin is typing.Union and len(args) == 2 and type(None) in args:
        inner = next(a for a in args if a is not type(None))
        return _python_type_to_json(inner)

    if hint is int or hint is bool:
        return "boolean" if hint is bool else "integer"
    if hint is float:
        return "number"
    if hint is bool:
        return "boolean"
    if origin in (list, typing.List) or hint is list:
        return "array"
    if origin in (dict, typing.Dict) or hint is dict:
        return "object"

    # Fallback for bare names
    name = getattr(hint, "__name__", str(hint))
    if name == "int":
        return "integer"
    if name == "float":
        return "number"
    if name == "bool":
        return "boolean"
    if name in ("list", "List"):
        return "array"
    if name in ("dict", "Dict"):
        return "object"

    return "string"


def _parse_signature(
    func: typing.Callable,
) -> typing.Tuple[str, typing.Dict[str, typing.Any], typing.List[str]]:
    """Parse a function into (description, properties, required) for tool-use schemas.

    Uses the docstring for description and parameter descriptions, type hints for
    JSON types, and the real signature for required/optional determination.
    """
    docstring = inspect.getdoc(func) or ""

    desc_match = re.match(
        r"\s*(.*?)(?:\n\n|\n\s*Args:|\n\s*Parameters:|\Z)", docstring, re.DOTALL
    )
    description = desc_match.group(1).strip() if desc_match else ""

    params_match = re.search(
        r"(?:Args|Parameters):(.*?)(?:\n\s*Returns:|\n\s*Raises:|\Z)",
        docstring,
        re.DOTALL,
    )
    params_text = params_match.group(1).strip() if params_match else ""

    type_hints: typing.Dict[str, typing.Any] = {}
    try:
        type_hints = typing.get_type_hints(func)
    except Exception:
        pass

    sig = inspect.signature(func)
    properties: typing.Dict[str, typing.Any] = {}
    required: typing.List[str] = []

    param_pattern = re.compile(
        r"\s*(\w+)(?:\s*\(\w+\))?\s*:\s*(.*?)(?=\n\s*\w+\s*:|$)", re.DOTALL
    )
    for match in param_pattern.finditer(params_text):
        param_name = match.group(1).strip()
        param_desc = match.group(2).strip()

        if param_name not in sig.parameters:
            continue

        hint = type_hints.get(param_name)
        json_type = _python_type_to_json(hint) if hint is not None else "string"

        entry: typing.Dict[str, typing.Any] = {
            "type": json_type,
            "description": param_desc,
        }
        if json_type == "array":
            entry["items"] = {"type": "string"}

        properties[param_name] = entry

        param = sig.parameters[param_name]
        is_optional = param.default is not inspect.Parameter.empty
        if not is_optional and param_name not in ("kwargs",) and not param_name.startswith("*"):
            required.append(param_name)
        elif not is_optional and "(required)" in param_desc.lower():
            if param_name not in required:
                required.append(param_name)

    # Catch params present in signature but absent from docstring
    for param_name, param in sig.parameters.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            continue
        if param_name in properties:
            continue
        hint = type_hints.get(param_name)
        json_type = _python_type_to_json(hint) if hint is not None else "string"
        properties[param_name] = {
            "type": json_type,
            "description": "No description available",
        }
        if (
            param.default is inspect.Parameter.empty
            and param.kind != inspect.Parameter.VAR_POSITIONAL
        ):
            required.append(param_name)

    return description, properties, required


def _mcp_schema(func: typing.Callable) -> typing.Optional[typing.Dict]:
    """Return the raw MCP inputSchema if this callable is an MCP tool wrapper, else None."""
    raw = getattr(func, "_tool_schema", None)
    if raw is None:
        return None
    if hasattr(raw, "model_dump"):
        return raw.model_dump()
    return dict(raw)


# Schemas are derived from static docstrings/signatures — cache them so the
# agent loop doesn't re-parse every job's docstring on every model call.
_schema_cache: typing.Dict[typing.Tuple[str, typing.Callable], typing.Dict[str, typing.Any]] = {}


def function_to_schema(func: typing.Callable) -> typing.Dict[str, typing.Any]:
    model = helpers_model.get_model()
    if model is None:
        raise Exception("Model is not initialized.")

    provider = model[0]
    key = (provider, func)
    if key in _schema_cache:
        return _schema_cache[key]

    if provider == "ollama":
        schema = function_to_schema_ollama(func)
    elif provider == "gemini":
        schema = function_to_schema_gemini(func)
    elif provider == "anthropic":
        schema = function_to_schema_anthropic(func)
    else:
        raise Exception(f"Unsupported model type: {provider}")

    _schema_cache[key] = schema
    return schema


def function_to_schema_ollama(func: typing.Callable) -> typing.Dict[str, typing.Any]:
    schema = _mcp_schema(func)
    if schema is not None:
        return {
            "type": "function",
            "function": {
                "name": func.__name__,
                "description": func.__doc__ or func.__name__,
                "parameters": schema,
            },
        }
    description, properties, required = _parse_signature(func)
    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def function_to_schema_gemini(func: typing.Callable) -> typing.Dict[str, typing.Any]:
    schema = _mcp_schema(func)
    if schema is not None:
        return {
            "name": func.__name__,
            "description": func.__doc__ or func.__name__,
            "parameters": schema,
        }
    description, properties, required = _parse_signature(func)
    return {
        "name": func.__name__,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


def function_to_schema_anthropic(func: typing.Callable) -> typing.Dict[str, typing.Any]:
    schema = _mcp_schema(func)
    if schema is not None:
        return {
            "name": func.__name__,
            "description": func.__doc__ or func.__name__,
            "input_schema": schema,
        }
    description, properties, required = _parse_signature(func)
    return {
        "name": func.__name__,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


# ------------------------------------------------------------------ image helpers

def numpy_image_to_base64_bytes(
    image_array: np.ndarray, image_format: str = "PNG"
) -> typing.Optional[bytes]:
    """
    Encodes a NumPy array image into a base64 byte string.

    Args:
        image_array: A NumPy array representing the image (e.g., shape HxW or HxWx3, dtype=uint8).
        image_format: The format to save the image in ('PNG', 'JPEG', etc.). Defaults to 'PNG'.

    Returns:
        A bytes object containing the base64 encoded image data.
        Returns None if the conversion fails.
    """
    if image_array.dtype != np.uint8:
        print(f"Warning: Converting image data from {image_array.dtype} to uint8.")
        image_array = image_array.astype(np.uint8)

    try:
        if image_array.ndim == 2:
            pil_image = Image.fromarray(image_array, "L")
        elif image_array.ndim == 3 and image_array.shape[2] == 3:
            pil_image = Image.fromarray(image_array, "RGB")
        elif image_array.ndim == 3 and image_array.shape[2] == 4:
            pil_image = Image.fromarray(image_array, "RGBA")
        else:
            print(f"Error: Unsupported image array shape: {image_array.shape}")
            return None
    except Exception as e:
        print(f"Error converting numpy array to Pillow image: {e}")
        return None

    buffer = io.BytesIO()
    try:
        pil_image.save(buffer, format=image_format)
    except KeyError:
        print(f"Error: Unsupported image format: {image_format}")
        return None
    except Exception as e:
        print(f"Error saving Pillow image to buffer: {e}")
        return None

    return base64.b64encode(buffer.getvalue())
