"""The VLM eval suite — image perception tasks for the harness.

These tasks seed a generated image (via the Task.setup hook, since Task.files is
text-only) and grade the agent's spoken answer with answer_contains. They exercise
the read_file image path end-to-end: a vision MODEL sees the lifted image, or a
configured AGENT_VLM_MODEL captions it.

The harness integration is tested with a faked runner (no model, no API cost); the
real vision check happens when the suite is run against a live VLM.
"""

import pytest
from PIL import Image

import evals.harness as harness
from evals.suites.vlm import VLM_SUITE, make_solid, make_split, make_text


def test_make_solid_produces_a_png_of_that_colour(tmp_path):
    p = tmp_path / "s.png"
    make_solid(p, (220, 20, 30))
    img = Image.open(p).convert("RGB")
    assert img.size[0] > 0
    # Centre pixel is the requested colour.
    assert img.getpixel((img.size[0] // 2, img.size[1] // 2)) == (220, 20, 30)


def test_make_split_has_two_halves(tmp_path):
    p = tmp_path / "split.png"
    make_split(p, (220, 20, 30), (20, 40, 210))
    img = Image.open(p).convert("RGB")
    w, h = img.size
    assert img.getpixel((w // 4, h // 2)) == (220, 20, 30)  # left
    assert img.getpixel((3 * w // 4, h // 2)) == (20, 40, 210)  # right


def test_make_text_renders_non_blank(tmp_path):
    p = tmp_path / "t.png"
    make_text(p, "DEPLOY FAILED")
    img = Image.open(p).convert("RGB")
    # Some pixels are non-white (text was drawn).
    assert any(
        img.getpixel((x, y)) != (255, 255, 255)
        for x in range(0, img.size[0], 5)
        for y in range(0, img.size[1], 5)
    )


def test_suite_tasks_are_well_formed():
    assert len(VLM_SUITE) >= 3
    ids = [t.id for t in VLM_SUITE]
    assert len(ids) == len(set(ids))  # unique ids
    for t in VLM_SUITE:
        assert t.prompt and callable(t.grader)
        assert t.setup is not None  # images are seeded via the setup hook
        # VLM tasks are graded on the spoken answer.
        assert getattr(t.grader, "wants_answer", False) is True


def test_setup_writes_a_readable_image(tmp_path):
    for t in VLM_SUITE:
        assert t.setup is not None
        t.setup(tmp_path)
        img_path = tmp_path / "image.png"
        assert img_path.exists()
        Image.open(img_path).verify()  # raises if not a valid image


def test_suite_is_registered_in_the_runner():
    from evals.run import SUITES, get_suite

    assert "vlm" in SUITES
    assert get_suite("vlm") is VLM_SUITE or get_suite("vlm") == VLM_SUITE


@pytest.mark.asyncio
async def test_vlm_task_passes_with_a_correct_canned_answer(monkeypatch, tmp_path):
    """Plug a vlm task into run_task with a faked runner that 'sees' red — the
    answer-grader should pass. Proves the suite integrates with the harness."""
    color_task = next(t for t in VLM_SUITE if "color" in t.id)

    async def fake_runner(prompt, **kwargs):
        return [{"type": "turn_end"}], [
            {"role": "assistant", "content": "The dominant colour in the image is red."}
        ]

    monkeypatch.setattr(harness, "run_agent_collecting", fake_runner)

    result = await harness.run_task(color_task)
    assert result.passed, result.detail
