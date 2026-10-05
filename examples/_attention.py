"""Resolve the example CLIs' attention choices to installed Diffusers backends."""

from importlib import import_module


ATTENTION_BACKENDS = {
    "sdpa": "native",
    "fa2": "_vimoo_flash_2",
    "fa3": "_flash_varlen_3",
    "fa4": "_vimoo_flash_4",
    "sage": "sage",
}

_OPTIONAL_KERNELS = {
    "fa2": ("flash_attn", "flash_attn_varlen_func", "flash-attn>=2.6.3"),
    "fa3": (
        "flash_attn_interface",
        "flash_attn_varlen_func",
        "FlashAttention 3 beta built from the flash-attention repository's hopper directory",
    ),
    "fa4": ("flash_attn.cute.interface", "flash_attn_varlen_func", "flash-attn-4"),
    "sage": ("sageattention", "sageattn", "SageAttention 2.2.0"),
}


def resolve_attention_backend(name):
    """Fail before model loading if an explicitly selected kernel is unavailable."""
    if name not in ATTENTION_BACKENDS:
        raise ValueError(f"Unknown attention backend: {name}")
    if name in _OPTIONAL_KERNELS:
        module_name, function_name, requirement = _OPTIONAL_KERNELS[name]
        try:
            module = import_module(module_name)
            if not callable(getattr(module, function_name, None)):
                raise ImportError(f"{module_name}.{function_name} is unavailable")
        except (ImportError, OSError) as error:
            raise RuntimeError(
                f"--attention-backend {name} requires a working {requirement} installation."
            ) from error
    return ATTENTION_BACKENDS[name]
