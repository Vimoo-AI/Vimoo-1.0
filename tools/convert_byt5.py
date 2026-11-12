#!/usr/bin/env python3
"""Convert a downloaded ByT5 encoder for Vimoo inference."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile


GLYPH_REPO = "nlpcvcode/Glyph-SDXL-v2"
GLYPH_REVISION = "a5aac7f492e85819208e7ed14aa4402d9c0b1b65"
BASE_REPO = "google/byt5-small"
BASE_REVISION = "68377bdc18a2ffec8a0533fef03b1c513a4dd49d"


def convert(source_dir, base_dir, output, output_format):
    import torch
    from safetensors.torch import save_file
    from transformers import ByT5Tokenizer, T5Config, T5EncoderModel

    source_dir, base_dir, output = Path(source_dir), Path(base_dir), Path(output)
    weight = (
        output / "text_encoders/vimoo_v1_glyph_byt5_fp32.safetensors"
        if output_format == "comfyui"
        else output / "text_encoder_2/model.safetensors"
    )
    if weight.exists() or weight.is_symlink():
        raise FileExistsError(f"Glyph weights already exist: {weight}")
    colors = json.loads((source_dir / "assets/color_idx.json").read_text())
    fonts = json.loads((source_dir / "assets/multilingual_10-lang_idx.json").read_text())
    tokenizer = ByT5Tokenizer.from_pretrained(base_dir, local_files_only=True)
    tokens = [f"<color-{i}>" for i in range(len(colors))]
    tokens += [f"<{code[:2]}-font-{index}>" for code, index in fonts.items()]
    tokenizer.add_tokens(tokens, special_tokens=True)
    config = T5Config.from_pretrained(base_dir, local_files_only=True)
    config.vocab_size = len(tokenizer)
    config.is_encoder_decoder = False
    config.use_cache = False
    state = torch.load(source_dir / "checkpoints/byt5_model.pt", map_location="cpu", weights_only=True)
    if len(tokenizer) != 1510 or state["embed_tokens.weight"].shape != (1510, 1472):
        raise ValueError("Expected the Glyph-SDXL-v2 encoder and its 1510-token vocabulary")
    if any(not isinstance(value, torch.Tensor) or value.dtype != torch.float32 for value in state.values()):
        raise ValueError("Glyph weights must contain FP32 tensors")
    converted = {f"encoder.{key}": value for key, value in state.items()}
    converted["shared.weight"] = state["embed_tokens.weight"]
    with torch.device("meta"):
        encoder = T5EncoderModel(config)
    encoder.load_state_dict(converted, strict=True, assign=True)

    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".byt5-", dir=output) as temporary:
        stage = Path(temporary)
        if output_format == "comfyui":
            target = stage / "text_encoders" / weight.name
            target.parent.mkdir()
            save_file(
                {key: value.contiguous().clone() for key, value in converted.items()},
                target,
                metadata={"format": "pt"},
            )
        else:
            encoder.save_pretrained(stage / "text_encoder_2", safe_serialization=True)
            tokenizer.save_pretrained(stage / "tokenizer_2")
        for path in stage.rglob("*"):
            if path.is_file():
                target = output / path.relative_to(stage)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), target)
    return weight


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        required=True,
        type=Path,
        help="downloaded Glyph-SDXL-v2 directory",
    )
    parser.add_argument(
        "--base-dir",
        required=True,
        type=Path,
        help="downloaded google/byt5-small config and tokenizer",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Vimoo model directory, or ComfyUI models directory",
    )
    parser.add_argument(
        "--format",
        required=True,
        choices=("diffusers", "comfyui"),
        help="MLX uses diffusers format",
    )
    args = parser.parse_args(argv)
    try:
        weight = convert(args.source_dir, args.base_dir, args.output, args.format)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        parser.exit(1, f"Could not convert ByT5 encoder: {error}\n")
    print(f"Converted ByT5 encoder: {weight}")


if __name__ == "__main__":
    main()
