"""Check locally prepared text components before downloading inference components."""

from pathlib import Path


def require_byt5_components(model):
    root = Path(model).expanduser()
    if not (root / "modular_model_index.json").is_file():
        return  # The pipeline reports an invalid model path.
    required = ("text_encoder_2/model.safetensors", "tokenizer_2/tokenizer_config.json")
    if any(not (root / name).is_file() for name in required):
        raise ValueError(
            "Download and convert the ByT5 encoder before loading this model. "
            "See README Download weights and run convert_byt5.py with --format diffusers."
        )
