#!/usr/bin/env python3
"""Generate video from an image with Vimoo-1.0 and native Diffusers APIs."""

import argparse
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=str(Path(__file__).resolve().parents[1] / "models" / "Vimoo-1.0"),
    )
    parser.add_argument("--image", required=True, help="reference image path or URL")
    parser.add_argument(
        "--prompt", default="The subject moves gently as the camera slowly pushes in."
    )
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

    import torch
    from diffusers import (
        ClassifierFreeGuidance,
        ComponentsManager,
        ModularPipeline,
        VimooI2VFlowMatchEulerDiscreteScheduler,
    )
    from diffusers.utils import export_to_video, load_image

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
            args.model, workflow="i2v", components_manager=manager
        )
    except OSError as error:
        parser.error(f"Could not load --model {args.model!r}: {error}")
    pipe.load_components(
        dtype={
            "transformer": torch.bfloat16,
            "text_encoder": torch.float32,
            "vision_encoder": torch.bfloat16,
            "default": torch.float32,
        }
    )
    pipe.text_encoder.to(dtype=torch.float16)
    pipe.vision_encoder.to(dtype=torch.float16)
    pipe.update_components(
        scheduler=VimooI2VFlowMatchEulerDiscreteScheduler(
            num_train_timesteps=1000, shift=6.0
        ),
        guider=ClassifierFreeGuidance.from_config(
            pipe.guider.config,
            guidance_scale=3.0,
            guidance_rescale=0.5,
        ),
    )
    pipe.transformer.set_attention_backend(attention_backend)
    pipe.text_encoder.config.use_cache = False
    # Optional: pipe.transformer.compile_math_helpers() before installing offload hooks.
    manager.enable_auto_cpu_offload(
        device=torch.device("cuda"),
        offload_strategy=lambda hooks, **kwargs: hooks,
    )

    videos = pipe(
        prompt=args.prompt,
        reference_image=reference_image,
        negative_prompt=None,
        add_fps=True,
        i2v_first_frame_replace=True,
        height=720,
        width=1280,
        num_frames=121,
        fps=24,
        num_inference_steps=50,
        flow_shift=6.0,
        generator=torch.Generator("cpu").manual_seed(1234),
        vae_tiling=False,
        output_type="np",
        output="videos",
    )
    export_to_video(
        videos[0], str(output_path), fps=24, quality=None
    )
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()
