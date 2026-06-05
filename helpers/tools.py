import base64
import inspect
import io
import re
import typing

import numpy as np
from PIL import Image

import helpers.model as helpers_model


def _desc_marks_required(desc: str) -> bool:
    return "(required)" in desc.lower()


def function_to_schema(func: typing.Callable) -> typing.Dict[str, typing.Any]:
    """
    Converts a function's docstring into a structured JSON schema object.

    Args:
        func: The function to parse

    Returns:
        A dictionary representing the function in the requested schema format
    """

    model = helpers_model.get_model()

    if model is None:
        raise Exception("Model is not initialized.")

    if model[0] == "ollama":
        return function_to_schema_ollama(func)

    elif model[0] == "gemini":
        return function_to_schema_gemini(func)

    elif model[0] == "sonnet":
        return function_to_schema_anthropic(func)

    raise Exception("Unsupported model type.")


def function_to_schema_ollama(func: typing.Callable) -> typing.Dict[str, typing.Any]:
    # Get function name
    name = func.__name__

    # Get docstring and clean it up
    docstring = inspect.getdoc(func) or ""

    # Extract description (first paragraph of docstring)
    description_match = re.match(
        r"\s*(.*?)(?:\n\n|\n\s*Args:|\n\s*Parameters:|\Z)", docstring, re.DOTALL
    )
    description = description_match.group(1).strip() if description_match else ""

    # Extract parameters section
    params_match = re.search(
        r"(?:Args|Parameters):(.*?)(?:\n\s*Returns:|\n\s*Raises:|\Z)",
        docstring,
        re.DOTALL,
    )
    params_text = params_match.group(1).strip() if params_match else ""

    # Parse parameters
    properties = {}
    required = []

    # Get type hints from function signature
    type_hints = typing.get_type_hints(func)

    # Parse parameter definitions
    param_pattern = re.compile(
        r"\s*(\w+)(?:\s*\(\w+\))?\s*:\s*(.*?)(?=\n\s*\w+\s*:|$)", re.DOTALL
    )
    for match in param_pattern.finditer(params_text):
        param_name = match.group(1).strip()
        param_desc = match.group(2).strip()

        # Check if parameter is in kwargs (optional) or args (required)
        sig = inspect.signature(func)
        is_kwarg = False

        for param in sig.parameters.values():
            if param.name == param_name:
                if param.default != inspect.Parameter.empty:
                    is_kwarg = True
                break

        # Determine parameter type
        param_type = "string"  # Default type
        if param_name in type_hints:
            hint = type_hints[param_name]
            hint_str = str(hint)
            if "int" in hint_str:
                param_type = "integer"
            elif "float" in hint_str:
                param_type = "number"
            elif "bool" in hint_str:
                param_type = "boolean"
            elif "list" in hint_str or "List" in hint_str:
                param_type = "array"
                properties[param_name] = {
                    "type": param_type,
                    "items": {"type": "string"},
                    "description": param_desc,
                }
                continue
            elif "dict" in hint_str or "Dict" in hint_str:
                param_type = "object"

        properties[param_name] = {"type": param_type, "description": param_desc}

        # If not a kwarg and not "kwargs" itself, mark as required
        if not is_kwarg and param_name != "kwargs" and not param_name.startswith("*"):
            required.append(param_name)
        elif param_name not in required and _desc_marks_required(param_desc):
            required.append(param_name)

    # Handle  case separately by checking the function signature
    sig = inspect.signature(func)
    for param_name, param in sig.parameters.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:  # This is
            # Don't add kwargs to the properties or required list
            pass
        elif param_name not in properties:
            # Handle parameters that weren't documented in the docstring
            properties[param_name] = {
                "type": "string",
                "description": "No description available",
            }
            if (
                param.default == inspect.Parameter.empty
                and param.kind != inspect.Parameter.VAR_POSITIONAL
            ):
                required.append(param_name)

    # Build the schema in the format required for Ollama
    schema = {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }

    return schema


def function_to_schema_gemini(func: typing.Callable) -> typing.Dict[str, typing.Any]:
    # Get function name
    name = func.__name__

    # Get docstring and clean it up
    docstring = inspect.getdoc(func) or ""

    # Extract description (first paragraph of docstring)
    description_match = re.match(
        r"\s*(.*?)(?:\n\n|\n\s*Args:|\n\s*Parameters:|\Z)", docstring, re.DOTALL
    )
    description = description_match.group(1).strip() if description_match else ""

    # Extract parameters section
    params_match = re.search(
        r"(?:Args|Parameters):(.*?)(?:\n\s*Returns:|\n\s*Raises:|\Z)",
        docstring,
        re.DOTALL,
    )
    params_text = params_match.group(1).strip() if params_match else ""

    # Parse parameters
    properties = {}
    required = []

    # Get type hints from function signature
    type_hints = typing.get_type_hints(func)

    # Parse parameter definitions
    param_pattern = re.compile(
        r"\s*(\w+)(?:\s*\(\w+\))?\s*:\s*(.*?)(?=\n\s*\w+\s*:|$)", re.DOTALL
    )
    for match in param_pattern.finditer(params_text):
        param_name = match.group(1).strip()
        param_desc = match.group(2).strip()

        # Check if parameter is in kwargs (optional) or args (required)
        sig = inspect.signature(func)
        is_kwarg = False

        for param in sig.parameters.values():
            if param.name == param_name:
                if param.default != inspect.Parameter.empty:
                    is_kwarg = True
                break

        # Determine parameter type
        param_type = "string"  # Default type
        if param_name in type_hints:
            hint = type_hints[param_name]
            hint_str = str(hint)
            if "int" in hint_str:
                param_type = "integer"
            elif "float" in hint_str:
                param_type = "number"
            elif "bool" in hint_str:
                param_type = "boolean"
            elif "list" in hint_str or "List" in hint_str:
                param_type = "array"
                properties[param_name] = {
                    "type": param_type,
                    "items": {"type": "string"},
                    "description": param_desc,
                }
                continue
            elif "dict" in hint_str or "Dict" in hint_str:
                param_type = "object"

        properties[param_name] = {"type": param_type, "description": param_desc}

        # If not a kwarg and not "kwargs" itself, mark as required
        if not is_kwarg and param_name != "kwargs" and not param_name.startswith("*"):
            required.append(param_name)
        elif param_name not in required and _desc_marks_required(param_desc):
            required.append(param_name)

    # Handle  case separately by checking the function signature
    sig = inspect.signature(func)
    for param_name, param in sig.parameters.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:  # This is
            # Don't add kwargs to the properties or required list
            pass
        elif param_name not in properties:
            # Handle parameters that weren't documented in the docstring
            properties[param_name] = {
                "type": "string",
                "description": "No description available",
            }
            if (
                param.default == inspect.Parameter.empty
                and param.kind != inspect.Parameter.VAR_POSITIONAL
            ):
                required.append(param_name)

    # Build the schema
    schema = {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }

    return schema


def function_to_schema_anthropic(func: typing.Callable) -> typing.Dict[str, typing.Any]:
    # Get function name
    name = func.__name__

    # Get docstring and clean it up
    docstring = inspect.getdoc(func) or ""

    # Extract description (first paragraph of docstring)
    description_match = re.match(
        r"\s*(.*?)(?:\n\n|\n\s*Args:|\n\s*Parameters:|\Z)", docstring, re.DOTALL
    )
    description = description_match.group(1).strip() if description_match else ""

    # Extract parameters section
    params_match = re.search(
        r"(?:Args|Parameters):(.*?)(?:\n\s*Returns:|\n\s*Raises:|\Z)",
        docstring,
        re.DOTALL,
    )
    params_text = params_match.group(1).strip() if params_match else ""

    # Parse parameters
    properties = {}
    required = []

    # Get type hints from function signature
    type_hints = typing.get_type_hints(func)

    # Parse parameter definitions
    param_pattern = re.compile(
        r"\s*(\w+)(?:\s*\(\w+\))?\s*:\s*(.*?)(?=\n\s*\w+\s*:|$)", re.DOTALL
    )
    for match in param_pattern.finditer(params_text):
        param_name = match.group(1).strip()
        param_desc = match.group(2).strip()

        # Check if parameter is in kwargs (optional) or args (required)
        sig = inspect.signature(func)
        is_kwarg = False

        for param in sig.parameters.values():
            if param.name == param_name:
                if param.default != inspect.Parameter.empty:
                    is_kwarg = True
                break

        # Determine parameter type
        param_type = "string"  # Default type
        if param_name in type_hints:
            hint = type_hints[param_name]
            hint_str = str(hint)
            if "int" in hint_str:
                param_type = "integer"
            elif "float" in hint_str:
                param_type = "number"
            elif "bool" in hint_str:
                param_type = "boolean"
            elif "list" in hint_str or "List" in hint_str:
                param_type = "array"
            elif "dict" in hint_str or "Dict" in hint_str:
                param_type = "object"

        properties[param_name] = {"type": param_type, "description": param_desc}

        # If not a kwarg and not "kwargs" itself, mark as required
        if not is_kwarg and param_name != "kwargs" and not param_name.startswith("*"):
            required.append(param_name)
        elif param_name not in required and _desc_marks_required(param_desc):
            required.append(param_name)

    # Handle  case separately by checking the function signature
    sig = inspect.signature(func)
    for param_name, param in sig.parameters.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:  # This is
            # Don't add kwargs to the properties or required list
            pass
        elif param_name not in properties:
            # Handle parameters that weren't documented in the docstring
            properties[param_name] = {
                "type": "string",
                "description": "No description available",
            }
            if (
                param.default == inspect.Parameter.empty
                and param.kind != inspect.Parameter.VAR_POSITIONAL
            ):
                required.append(param_name)

    # Build the schema
    schema = {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }

    return schema


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
    # Ensure the array is in a format Pillow can handle (e.g., uint8)
    if image_array.dtype != np.uint8:
        print(f"Warning: Converting image data from {image_array.dtype} to uint8.")
        image_array = image_array.astype(np.uint8)

    # Convert the NumPy array to a Pillow Image object
    try:
        # Handle different array shapes (grayscale, RGB)
        if image_array.ndim == 2:
            pil_image = Image.fromarray(image_array, "L")  # 'L' for grayscale
        elif image_array.ndim == 3 and image_array.shape[2] == 3:
            pil_image = Image.fromarray(image_array, "RGB")  # 'RGB' for color
        elif image_array.ndim == 3 and image_array.shape[2] == 4:
            pil_image = Image.fromarray(
                image_array, "RGBA"
            )  # 'RGBA' for color with alpha
        else:
            print(f"Error: Unsupported image array shape: {image_array.shape}")
            return None

    except Exception as e:
        print(f"Error converting numpy array to Pillow image: {e}")
        return None

    # Save the image to a bytes buffer in the specified format
    buffer = io.BytesIO()
    try:
        pil_image.save(buffer, format=image_format)
    except KeyError:
        print(f"Error: Unsupported image format: {image_format}")
        return None
    except Exception as e:
        print(f"Error saving Pillow image to buffer: {e}")
        return None

    # Get the binary data from the buffer
    image_bytes = buffer.getvalue()

    # Encode the binary data to base64 bytes
    base64_bytes = base64.b64encode(image_bytes)

    return base64_bytes
