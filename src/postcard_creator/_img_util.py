import importlib.resources
import io
import logging
import os
import textwrap
from math import floor
from pathlib import Path
from time import gmtime, strftime
from typing import IO, Any, Literal

from colorthief import ColorThief  # type: ignore
from PIL import Image, ImageDraw, ImageFont
from resizeimage import resizeimage  # type: ignore

_LOGGER = logging.getLogger(__package__)


def _get_trace_postcard_sent_dir():
    path = os.path.join(os.getcwd(), ".postcard_creator_wrapper_sent")
    Path(path).mkdir(parents=True, exist_ok=True)
    return path


def rotate_and_scale_image(
    file: IO[bytes],
    image_target_width: int = 154,
    image_target_height: int = 111,
    image_quality_factor: float = 20,
    image_rotate: bool = True,
    image_export: bool = False,
    # = True, will not make image smaller than given w/h, for high resolution submissions
    enforce_size: bool = False,
    # = False, will force resize cover even if image is too small.
    fallback_color_fill: bool = False,
    img_format: Literal["PNG", "jpeg"] = "PNG",
    **kwargs: Any,
):
    with Image.open(file) as image:
        if image_rotate and image.width < image.height:
            image = image.rotate(90, expand=True)
            _LOGGER.debug("rotating image by 90 degrees")

        if not enforce_size and (
            image.width < image_quality_factor * image_target_width
            or image.height < image_quality_factor * image_target_height
        ):
            factor_width = image.width / image_target_width
            factor_height = image.height / image_target_height
            factor = min([factor_height, factor_width])

            _LOGGER.debug(
                "image is smaller than default for resize/fill. "
                "using scale factor {} instead of {}".format(
                    factor, image_quality_factor
                )
            )
            image_quality_factor = factor

        width = image_target_width * image_quality_factor
        height = image_target_height * image_quality_factor
        _LOGGER.debug(
            "resizing image from {}x{} to {}x{}".format(
                image.width, image.height, width, height
            )
        )

        # XXX: swissid endpoint expect specific size for postcard
        # if we have an image which is too small, do not upsample but rather center image and fill
        # with boundary color which is most dominant color in image
        #
        # validate=True will throw exception if image is too small
        #
        try:
            cover = resizeimage.resize_cover(  # type: ignore
                image,
                [width, height],
                validate=fallback_color_fill,  # type: ignore
            )
        except Exception as e:
            _LOGGER.warning(e)
            _LOGGER.warning(
                f"resizing image from {image.width}x{image.height} to {width}x{height} failed."
                f" using resize_contain mode as a fallback. Expect boundaries around img"
            )

            color_thief = ColorThief(file)
            (r, g, b) = color_thief.get_color(quality=1)  # type: ignore
            color = (r, g, b, 0)  # type: ignore
            cover = resizeimage.resize_contain(image, [width, height], bg_color=color)  # type: ignore
            image_export = True
            _LOGGER.warning(
                f"using image boundary color {color}, exporting image for visual inspection."
            )

        _LOGGER.debug("resizing done")

        cover = cover.convert("RGB")  # type: ignore
        with io.BytesIO() as f:
            cover.save(f, img_format)  # type: ignore
            scaled = f.getvalue()

        if image_export:
            name = strftime(
                "postcard_creator_export_%Y-%m-%d_%H-%M-%S_cover.jpg", gmtime()
            )
            path = os.path.join(_get_trace_postcard_sent_dir(), name)
            _LOGGER.info("exporting image to {} (image_export=True)".format(path))
            cover.save(path)  # type: ignore

    return scaled


def create_text_image(
    text: str,
    image_export: bool = False,
    line_height_mul: float = 1.15,
) -> bytes:
    """
    Create a jpg with given text and return in bytes format
    """
    text_canvas_w = 720
    text_canvas_h = 744
    text_canvas_bg = "white"
    text_canvas_fg = "black"
    text_canvas_font_name = "open_sans_emoji.ttf"
    text_margin = 10

    def load_font(size: int):
        with importlib.resources.as_file(
            importlib.resources.files("postcard_creator").joinpath(
                text_canvas_font_name
            )
        ) as font_path:
            return ImageFont.truetype(str(font_path), size)

    size_l = 10
    size_r = 300
    size = chars_per_line = line_h = text_y_start = 0
    lines: list[str] = []
    font: ImageFont.FreeTypeFont | None = None
    while size_l < size_r:
        size = floor((size_l + size_r) / 2.0)

        font = load_font(size)
        bbox = font.getbbox("1")
        chars_per_line = int((text_canvas_w - 2 * text_margin) / (bbox[2] - bbox[0]))

        lines = []
        for line in text.splitlines():
            lines.extend(textwrap.wrap(line, width=chars_per_line))

        line_h = round(bbox[3] * line_height_mul)
        total_h_with_margin = len(lines) * line_h + (2 * text_margin)

        if total_h_with_margin < text_canvas_h:
            # does fit
            size_l = size + 1
            text_y_start = (text_canvas_h - total_h_with_margin) // 2
        else:
            # does not fit
            size_r = size - 1
            text_y_start = 0

    assert font is not None
    _LOGGER.debug(
        f"using font with size: {size}px, chars per line: {chars_per_line} line-height: {line_h}px"
    )

    canvas = Image.new("RGB", (text_canvas_w, text_canvas_h), text_canvas_bg)
    draw = ImageDraw.Draw(canvas)

    for line in lines:
        line_w, actual_line_h = _get_font_bbox_dim(font, line)
        if actual_line_h > line_h:
            _LOGGER.warning(
                "Line is higher than expected line height. %s > %s",
                actual_line_h,
                line_h,
            )

        draw.text(
            ((text_canvas_w - line_w) // 2, text_y_start),
            line,
            font=font,
            fill=text_canvas_fg,
            embedded_color=True,
        )
        text_y_start += line_h

    if image_export:
        name = strftime("postcard_creator_export_%Y-%m-%d_%H-%M-%S_text.jpg", gmtime())
        path = os.path.join(_get_trace_postcard_sent_dir(), name)
        _LOGGER.info("exporting image to {} (image_export=True)".format(path))
        canvas.save(path)

    img_byte_arr = io.BytesIO()
    canvas.save(img_byte_arr, format="jpeg")
    return img_byte_arr.getvalue()


def _get_font_bbox_dim(font: ImageFont.FreeTypeFont, text: str) -> tuple[int, int]:
    left, top, right, bottom = font.getbbox(text)
    return (int(right - left), int(bottom - top))
