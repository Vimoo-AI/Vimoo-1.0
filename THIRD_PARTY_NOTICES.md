# Third-party components

Vimoo uses the following upstream software and model components. Their
copyright notices and license terms continue to apply.

1. Diffusers runtime
   Source: https://github.com/huggingface/diffusers
   License: Apache-2.0
   https://github.com/huggingface/diffusers/blob/main/LICENSE

2. Qwen2.5-VL text tower and tokenizer
   Source: https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct
   Components: text tower and tokenizer

3. Glyph-ByT5 and tokenizer
   Source: https://huggingface.co/nlpcvcode/Glyph-SDXL-v2
   Components: encoder weights and font/color vocabulary, downloaded separately and prepared locally
   Base config and tokenizer: https://huggingface.co/google/byt5-small

4. VAE
   Source: https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B-Diffusers
   Component: vae subfolder

5. SigLIP vision encoder
   Source: https://huggingface.co/google/siglip-so400m-patch14-384
   Components: vision tower and image processor

Refer to the upstream repositories, model cards, and license files for the
terms governing each component. The Vimoo license (LICENSE) does not replace
those terms.
