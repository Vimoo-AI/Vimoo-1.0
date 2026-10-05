#!/usr/bin/env python3
"""Generate video with Vimoo-1.0 using native Diffusers APIs."""

import argparse
from pathlib import Path


def save_video(frames, output, *, fps):
    """Export truncating RGB values to MP4, preferring FFmpeg."""
    import shutil
    import subprocess

    import imageio.v2 as imageio
    import numpy as np

    pixels = (np.clip(frames, 0, 1) * 255).astype(np.uint8)
    ffmpeg = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
    if Path(ffmpeg).is_file():
        _, height, width, _ = pixels.shape
        command = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{width}x{height}",
            "-r",
            str(int(fps)),
            "-i",
            "-",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            "-movflags",
            "+faststart",
            str(output),
        ]
        try:
            result = subprocess.run(
                command, input=pixels.tobytes(), stderr=subprocess.PIPE
            )
        except OSError:
            result = None
        if result is not None:
            if result.returncode == 0:
                return
            print(
                "system ffmpeg encode failed, falling back to imageio: "
                + result.stderr.decode(errors="ignore")[-300:]
            )
    imageio.mimwrite(str(output), pixels, fps=fps)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=str(Path(__file__).resolve().parents[1] / "models" / "Vimoo-1.0"),
    )
    parser.add_argument(
        "--prompt", default='A cat holds a sign that says "Vimoo" on a sunny rooftop.'
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
    from diffusers import ClassifierFreeGuidance, ComponentsManager, ModularPipeline

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        parser.error(f"Could not create --output parent directory: {error}")
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = True
    manager = ComponentsManager()
    try:
        pipe = ModularPipeline.from_pretrained(
            args.model, workflow="t2v", components_manager=manager
        )
    except OSError as error:
        parser.error(f"Could not load --model {args.model!r}: {error}")
    pipe.load_components(
        dtype={
            "transformer": torch.bfloat16,
            "text_encoder": torch.bfloat16,
            "default": torch.float32,
        }
    )
    pipe.update_components(
        guider=ClassifierFreeGuidance.from_config(
            pipe.guider.config,
            guidance_scale=4.5,
            guidance_rescale=1.2,
        )
    )
    pipe.transformer.set_attention_backend(attention_backend)
    pipe.text_encoder.config.use_cache = False
    # Optional: pipe.transformer.compile_repeated_blocks() before installing offload hooks.
    manager.enable_auto_cpu_offload(
        device=torch.device("cuda"),
        offload_strategy=lambda hooks, **kwargs: hooks,
    )

    videos = pipe(
        prompt=args.prompt,
        negative_prompt=None,
        height=720,
        width=1280,
        num_frames=121,
        fps=24,
        num_inference_steps=50,
        flow_shift=12.0,
        generator=torch.Generator("cpu").manual_seed(1234),
        vae_tiling=False,
        output_type="np",
        output="videos",
    )
    save_video(videos[0], str(output_path), fps=24)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()
