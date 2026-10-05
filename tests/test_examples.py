"""The example CLI can explain its inputs before loading inference dependencies."""

from pathlib import Path
import importlib
import runpy
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
ENTRIES = (
    "vimoo_1_0_t2v.py",
    "vimoo_1_0_i2v.py",
    "vimoo_1_0_lite_ti2v.py",
)


def mock_runtime_imports(monkeypatch):
    """Keep CLI control-flow tests runnable with the declared minimal CI dependencies."""
    torch = ModuleType("torch")
    torch.bfloat16, torch.float16, torch.float32 = "bf16", "fp16", "fp32"
    torch.device = lambda device: device
    torch.Generator = lambda device: SimpleNamespace(manual_seed=lambda seed: None)
    torch.backends = SimpleNamespace(
        cuda=SimpleNamespace(matmul=SimpleNamespace(allow_tf32=True)),
        cudnn=SimpleNamespace(allow_tf32=False),
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    for name in ("numpy", "imageio", "imageio.v2", "accelerate", "accelerate.hooks"):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    sys.modules["imageio"].v2 = sys.modules["imageio.v2"]
    sys.modules["accelerate.hooks"].remove_hook_from_module = (
        lambda *args, **kwargs: None
    )


@pytest.mark.parametrize("entry", ENTRIES)
def test_help_without_inference_dependencies(entry):
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(EXAMPLES / entry), "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--model" in result.stdout
    assert "--prompt" in result.stdout
    assert "--output" in result.stdout
    assert "--attention-backend {sdpa,fa2,fa3,fa4,sage}" in result.stdout
    assert "default: PyTorch SDPA" in result.stdout


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("kind", ["directory", "parent_file"])
def test_output_path_rejected_without_inference_dependencies(entry, kind, tmp_path):
    if kind == "directory":
        output = tmp_path / "result.mp4"
        output.mkdir()
        expected = "--output points to a directory"
    else:
        parent = tmp_path / "regular-file"
        parent.write_text("not a directory")
        output = parent / "result.mp4"
        expected = "--output parent is not a directory"
    arguments = ["--output", str(output)]
    if entry == "vimoo_1_0_i2v.py":
        arguments += ["--image", "unused-reference.png"]
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(EXAMPLES / entry), *arguments],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert expected in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("entry", ["vimoo_1_0_i2v.py"])
def test_i2v_requires_a_reference_image(entry):
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(EXAMPLES / entry)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "--image" in result.stderr


@pytest.mark.parametrize("entry", ["vimoo_1_0_i2v.py", "vimoo_1_0_lite_ti2v.py"])
@pytest.mark.parametrize("corrupt", [False, True])
def test_invalid_image_fails_before_loading_models(
    entry, corrupt, monkeypatch, tmp_path, capsys
):
    mock_runtime_imports(monkeypatch)
    monkeypatch.syspath_prepend(str(EXAMPLES))
    image = tmp_path / "reference.png"
    if corrupt:
        image.write_bytes(b"not an image")

    def unexpected_model_load(*args, **kwargs):
        pytest.fail("Model loading must wait until the reference image is valid")

    def load_image(path):
        # Actual missing/corrupt-file decoding is covered by CLI integration probes.
        if corrupt:
            raise OSError("cannot identify image file")
        raise ValueError("not a valid image path")

    fake_diffusers = ModuleType("diffusers")
    fake_diffusers.ComponentsManager = unexpected_model_load
    fake_diffusers.ModularPipeline = SimpleNamespace(from_pretrained=unexpected_model_load)
    fake_diffusers.ClassifierFreeGuidance = SimpleNamespace()
    fake_diffusers.VimooI2VFlowMatchEulerDiscreteScheduler = SimpleNamespace()
    fake_utils = ModuleType("diffusers.utils")
    fake_utils.load_image = load_image
    fake_utils.export_to_video = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "diffusers", fake_diffusers)
    monkeypatch.setitem(sys.modules, "diffusers.utils", fake_utils)
    main = runpy.run_path(str(EXAMPLES / entry))["main"]

    with pytest.raises(SystemExit) as error:
        main(["--image", str(image), "--model", "must-not-load"])
    assert error.value.code == 2
    assert "Could not load --image" in capsys.readouterr().err


class AttentionSelected(Exception):
    pass


class InferenceRequested(Exception):
    pass


@pytest.mark.parametrize("entry", ENTRIES)
def test_model_load_error_explains_the_selected_path(entry, monkeypatch, capsys):
    mock_runtime_imports(monkeypatch)
    monkeypatch.syspath_prepend(str(EXAMPLES))

    def unavailable(*args, **kwargs):
        raise OSError("Could not find or load modular_model_index.json")

    fake_diffusers = ModuleType("diffusers")
    fake_diffusers.ComponentsManager = lambda: None
    fake_diffusers.ModularPipeline = SimpleNamespace(from_pretrained=unavailable)
    fake_diffusers.ClassifierFreeGuidance = SimpleNamespace()
    fake_diffusers.VimooI2VFlowMatchEulerDiscreteScheduler = SimpleNamespace()
    fake_utils = ModuleType("diffusers.utils")
    fake_utils.load_image = lambda path: path
    fake_utils.export_to_video = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "diffusers", fake_diffusers)
    monkeypatch.setitem(sys.modules, "diffusers.utils", fake_utils)
    main = runpy.run_path(str(EXAMPLES / entry))["main"]
    arguments = ["--model", "wrong-model-directory"]
    if entry == "vimoo_1_0_i2v.py":
        arguments += ["--image", "valid-reference.png"]
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2
    message = capsys.readouterr().err
    assert "Could not load --model 'wrong-model-directory'" in message
    assert "modular_model_index.json" in message


@pytest.mark.parametrize(
    ("entry", "image", "workflow", "shift"),
    [
        ("vimoo_1_0_t2v.py", False, "t2v", 12.0),
        ("vimoo_1_0_i2v.py", True, "i2v", 6.0),
        ("vimoo_1_0_lite_ti2v.py", False, "t2v", 8.0),
        ("vimoo_1_0_lite_ti2v.py", True, "i2v", 8.0),
    ],
)
@pytest.mark.parametrize("model_arg", [None, "local-model"])
def test_default_generation_recipe(
    entry, image, workflow, shift, model_arg, monkeypatch, tmp_path
):
    """Run each CLI to its inference call and inspect the actual default request."""
    mock_runtime_imports(monkeypatch)
    monkeypatch.syspath_prepend(str(EXAMPLES))
    loaded = []
    requests = []
    encoder = SimpleNamespace(config=SimpleNamespace(), to=lambda **kwargs: None)

    class Pipeline:
        guider = SimpleNamespace(config={})
        text_encoder = vision_encoder = text_encoder_2 = encoder
        transformer = SimpleNamespace(set_attention_backend=lambda backend: None)

        def load_components(self, **kwargs):
            pass

        def update_components(self, **kwargs):
            pass

        def __call__(self, **kwargs):
            requests.append(kwargs)
            raise InferenceRequested

    def load(model, **kwargs):
        loaded.append((model, kwargs))
        return Pipeline()

    fake_diffusers = ModuleType("diffusers")
    fake_diffusers.ComponentsManager = lambda: SimpleNamespace(
        enable_auto_cpu_offload=lambda **kwargs: None
    )
    fake_diffusers.ModularPipeline = SimpleNamespace(from_pretrained=load)
    fake_diffusers.ClassifierFreeGuidance = SimpleNamespace(
        from_config=lambda *args, **kwargs: None
    )
    fake_diffusers.VimooI2VFlowMatchEulerDiscreteScheduler = lambda **kwargs: None
    monkeypatch.setitem(sys.modules, "diffusers", fake_diffusers)
    fake_utils = ModuleType("diffusers.utils")
    fake_utils.load_image = lambda image: image
    fake_utils.export_to_video = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "diffusers.utils", fake_utils)
    hooks = importlib.import_module("accelerate.hooks")
    monkeypatch.setattr(hooks, "remove_hook_from_module", lambda *args, **kwargs: None)
    main = runpy.run_path(str(EXAMPLES / entry))["main"]
    monkeypatch.chdir(tmp_path)
    args = ["--output", str(tmp_path / "video.mp4")]
    if model_arg is not None:
        args += ["--model", model_arg]
    if image:
        args += ["--image", "reference.png"]
    with pytest.raises(InferenceRequested):
        main(args)
    assert loaded[0][1]["workflow"] == workflow
    package = "Vimoo-1.0-Lite" if entry == "vimoo_1_0_lite_ti2v.py" else "Vimoo-1.0"
    assert loaded[0][0] == (model_arg or str(EXAMPLES.parent / "models" / package))
    assert requests[0]["num_inference_steps"] == 50
    assert requests[0]["flow_shift"] == shift
    assert ("reference_image" in requests[0]) == image


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        (None, "native"),
        ("sdpa", "native"),
        ("fa2", "_vimoo_flash_2"),
        ("fa3", "_flash_varlen_3"),
        ("fa4", "_vimoo_flash_4"),
        ("sage", "sage"),
    ],
)
def test_cli_selects_the_requested_attention(
    entry, choice, expected, monkeypatch, tmp_path
):
    """Exercise each CLI up to the model setter without weights or GPU allocation."""
    monkeypatch.syspath_prepend(str(EXAMPLES))
    attention = importlib.import_module("_attention")
    installed = SimpleNamespace(
        flash_attn_varlen_func=lambda: None,
        flash_attn_func=lambda: None,
        sageattn=lambda: None,
    )
    monkeypatch.setattr(attention, "import_module", lambda name: installed)
    selected = []

    def select(backend):
        selected.append(backend)
        raise AttentionSelected

    encoder = SimpleNamespace(to=lambda **kwargs: None)
    pipe = SimpleNamespace(
        load_components=lambda **kwargs: None,
        update_components=lambda **kwargs: None,
        load_lora_weights=lambda *args, **kwargs: None,
        guider=SimpleNamespace(config={}),
        text_encoder=encoder,
        vision_encoder=encoder,
        transformer=SimpleNamespace(set_attention_backend=select),
    )
    fake_diffusers = ModuleType("diffusers")
    fake_diffusers.ComponentsManager = lambda: None
    fake_diffusers.ModularPipeline = SimpleNamespace(
        from_pretrained=lambda *args, **kwargs: pipe
    )
    fake_diffusers.ClassifierFreeGuidance = SimpleNamespace(
        from_config=lambda *args, **kwargs: None
    )
    fake_diffusers.VimooI2VFlowMatchEulerDiscreteScheduler = lambda **kwargs: None
    monkeypatch.setitem(sys.modules, "diffusers", fake_diffusers)
    fake_utils = ModuleType("diffusers.utils")
    fake_utils.export_to_video = lambda *args, **kwargs: None
    fake_utils.load_image = lambda image: image
    monkeypatch.setitem(sys.modules, "diffusers.utils", fake_utils)
    fake_torch = ModuleType("torch")
    fake_torch.bfloat16, fake_torch.float16, fake_torch.float32 = "bf16", "fp16", "fp32"
    fake_torch.backends = SimpleNamespace(
        cuda=SimpleNamespace(matmul=SimpleNamespace(allow_tf32=True)),
        cudnn=SimpleNamespace(allow_tf32=False),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    for name in (
        "numpy",
        "imageio",
        "imageio.v2",
        "accelerate",
        "accelerate.hooks",
        "PIL",
    ):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    sys.modules["accelerate.hooks"].remove_hook_from_module = (
        lambda *args, **kwargs: None
    )
    sys.modules["PIL"].Image = SimpleNamespace()
    main = runpy.run_path(str(EXAMPLES / entry))["main"]
    args = ["--output", str(tmp_path / "unused.mp4")]
    if entry == "vimoo_1_0_i2v.py":
        args += ["--image", "unused.png"]
    if choice is not None:
        args += ["--attention-backend", choice]
    with pytest.raises(AttentionSelected):
        main(args)
    assert selected == [expected]


@pytest.mark.parametrize("entry", ENTRIES)
def test_missing_optional_attention_fails_before_loading_models(entry, monkeypatch):
    monkeypatch.syspath_prepend(str(EXAMPLES))
    attention = importlib.import_module("_attention")

    def unavailable(name):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(attention, "import_module", unavailable)
    main = runpy.run_path(str(EXAMPLES / entry))["main"]
    args = ["--attention-backend", "fa4"]
    if entry == "vimoo_1_0_i2v.py":
        args += ["--image", "unused.png"]
    with pytest.raises(
        RuntimeError, match="--attention-backend fa4 requires a working flash-attn-4"
    ):
        main(args)


@pytest.mark.parametrize("choice", ["fa2", "fa3", "fa4", "sage"])
def test_each_optional_kernel_reports_an_unusable_install(choice, monkeypatch):
    monkeypatch.syspath_prepend(str(EXAMPLES))
    attention = importlib.import_module("_attention")
    monkeypatch.setattr(attention, "import_module", lambda name: ModuleType(name))
    with pytest.raises(
        RuntimeError, match=f"--attention-backend {choice} requires a working"
    ):
        attention.resolve_attention_backend(choice)


@pytest.mark.parametrize("entry", ENTRIES)
def test_unknown_attention_is_rejected_without_inference_dependencies(entry):
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(EXAMPLES / entry),
            "--attention-backend",
            "unknown",
            "--image",
            "unused.png",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "invalid choice: 'unknown'" in result.stderr
