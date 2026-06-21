"""A small VLM suite — image perception, exercising the read_file image path.

Like ``smoke``, every task is self-contained (no external asset, no network): a
generated image is seeded into the workdir via the :class:`Task` ``setup`` hook
(``Task.files`` is text-only, so a binary PNG can't ride there), and the agent's
*spoken answer* is graded with :func:`answer_contains`. Three dimensions, mirroring
how a coding agent actually meets images:

* ``vlm-color``    — basic perception: name the dominant colour of a solid fill.
* ``vlm-ocr``      — text transcription: read the text rendered in the image (the
  screenshot / error-dialog case, the most practically useful).
* ``vlm-spatial``  — spatial grounding: name the colour on one side of a split image.

Running this suite needs a vision-capable ``AGENT_MODEL`` (so the lifted image is
seen) *or* a configured ``AGENT_VLM_MODEL`` (so read_file captions the image). With
neither, the model can't see the image and the tasks fail — by design.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from evals.graders import answer_contains
from evals.harness import Task

# Candidate fonts for legible OCR text; fall back to PIL's bitmap font.
_FONT_PATHS = (
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_solid(path: Path, rgb: tuple[int, int, int], size: tuple[int, int] = (200, 200)) -> None:
    """Write a solid-colour PNG."""
    Image.new("RGB", size, rgb).save(path)


def make_split(
    path: Path,
    left: tuple[int, int, int],
    right: tuple[int, int, int],
    size: tuple[int, int] = (240, 140),
) -> None:
    """Write a PNG that is ``left`` colour on the left half, ``right`` on the right."""
    img = Image.new("RGB", size, left)
    ImageDraw.Draw(img).rectangle([size[0] // 2, 0, size[0], size[1]], fill=right)
    img.save(path)


def make_text(path: Path, text: str, size: tuple[int, int] = (560, 140)) -> None:
    """Write a PNG of black ``text`` on white — large enough to be OCR-legible."""
    img = Image.new("RGB", size, (255, 255, 255))
    ImageDraw.Draw(img).text((20, 40), text, fill=(0, 0, 0), font=_font(56))
    img.save(path)


def _seed(draw: Callable[[Path], None]) -> Callable[[Path], None]:
    """Wrap an image-drawing function into a Task.setup that writes image.png."""

    def setup(workdir: Path) -> None:
        draw(workdir / "image.png")

    return setup


VLM_SUITE: list[Task] = [
    Task(
        id="vlm-color",
        prompt=(
            "Read the image file image.png. In one word, what is the single dominant "
            "colour of the image?"
        ),
        grader=answer_contains("red"),
        setup=_seed(lambda p: make_solid(p, (220, 20, 30))),
    ),
    Task(
        id="vlm-ocr",
        prompt=(
            "Read the image file image.png. It contains a short line of text. "
            "Transcribe the text you see exactly."
        ),
        grader=answer_contains("DEPLOY FAILED"),
        setup=_seed(lambda p: make_text(p, "DEPLOY FAILED")),
    ),
    Task(
        id="vlm-spatial",
        prompt=(
            "Read the image file image.png. The image is split into a left half and a "
            "right half of different colours. What colour is the RIGHT half? One word."
        ),
        grader=answer_contains("blue"),
        setup=_seed(lambda p: make_split(p, (220, 20, 30), (20, 40, 210))),
    ),
]
