#!/usr/bin/env python3
"""Generate text- or image-conditioned video with the ordinary Vimoo-1.0-Lite base."""

import argparse
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=str(Path(__file__).resolve().parents[1] / "models" / "Vimoo-1.0-Lite"),
    )
    parser.add_argument("--image", help="optional reference image path or URL")
    parser.add_argument("--prompt", default="A pig is reading a book")
    parser.add_argument("--output", default="vimoo.mp4")
    parser.add_argument(
        "--attention-backend",
        choices=("sdpa", "fa2", "fa3", "fa4", "sage"),
        default="sdpa",
        help="attention implementation (default: PyTorch SDPA); other choices require their optional kernel",
    )
    args = parser.parse_args(argv)
    output_path = Path(args.output).expanduser()
    if output_path.is_dir():
        parser.error(f"--output points to a directory: {output_path}")
    if output_path.parent.is_file():
        parser.error(f"--output parent is not a directory: {output_path.parent}")

    if __package__:
        from ._attention import resolve_attention_backend
    else:
        from _attention import resolve_attention_backend

    attention_backend = resolve_attention_backend(args.attention_backend)

    import imageio.v2 as imageio
    import numpy as np
    import torch
    from accelerate.hooks import remove_hook_from_module
    from diffusers import ClassifierFreeGuidance, ComponentsManager, ModularPipeline
    from diffusers.utils import load_image

    reference_image = None
    if args.image:
        try:
            reference_image = load_image(args.image)
        except (OSError, ValueError) as error:
            parser.error(f"Could not load --image {args.image!r}: {error}")

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        parser.error(f"Could not create --output parent directory: {error}")
    manager = ComponentsManager()
    try:
        pipe = ModularPipeline.from_pretrained(
            args.model,
            workflow="i2v" if args.image else "t2v",
            components_manager=manager,
        )
    except OSError as error:
        parser.error(f"Could not load --model {args.model!r}: {error}")
    # Load Qwen in FP32 before the model profile converts it to FP16.
    pipe.load_components(
        dtype={
            "transformer": torch.bfloat16,
            "text_encoder": torch.float32,
            "vision_encoder": torch.bfloat16,
            "default": torch.float32,
        }
    )
    if args.image:
        pipe.vision_encoder.to(dtype=torch.float16)
    pipe.update_components(
        guider=ClassifierFreeGuidance.from_config(
            pipe.guider.config,
            guidance_scale=5.0 if args.image else 4.0,
            guidance_rescale=0.85,
        )
    )
    pipe.transformer.set_attention_backend(attention_backend)
    pipe.text_encoder.config.use_cache = False
    # Optional: pipe.transformer.compile_repeated_blocks() before installing offload hooks.
    manager.enable_auto_cpu_offload(
        device=torch.device("cuda"),
        offload_strategy=lambda hooks, **kwargs: hooks,
    )
    # Glyph conditioning uses CPU FP32, including prompts with quoted text.
    remove_hook_from_module(pipe.text_encoder_2, recurse=True)
    pipe.text_encoder_2.to(device="cpu", dtype=torch.float32)

    image_inputs = {}
    if args.image:
        image_inputs = {
            "reference_image": reference_image,
            "reference_guidance_scale": 3.0,
            "i2v_anchor_tau": 0.001,
        }
    videos = pipe(
        **image_inputs,
        prompt=args.prompt,
        negative_prompt=(
            "oversaturated colors, overexposed, static, blurry details, subtitles, "
            "style, artwork, painting, still image, grayish overall tone, worst quality, "
            "low quality, JPEG artifacts, ugly, mutilated, extra fingers, poorly drawn "
            "hands, poorly drawn face, deformed, disfigured, malformed limbs, fused "
            "fingers, motionless scene, cluttered background, three legs, many people "
            "in the background, walking backwards"
        ),
        height=720,
        width=1280,
        num_frames=121,
        fps=24,
        num_inference_steps=50,
        flow_shift=8.0,
        max_sequence_length=1400,
        generator=torch.Generator("cpu").manual_seed(1234),
        vae_tiling=False,
        output_type="pil",
        output="videos",
    )
    imageio.mimwrite(
        str(output_path),
        np.stack([np.asarray(frame) for frame in videos[0]]),
        fps=24,
    )
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()
