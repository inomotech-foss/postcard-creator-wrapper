import importlib.resources
import io
import logging
import os
import textwrap
from collections.abc import Sequence
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
            cover = resizeimage.resize_cover(
                image,
                [width, height],
                validate=fallback_color_fill,
            )
        except Exception as e:
            _LOGGER.warning(e)
            _LOGGER.warning(
                f"resizing image from {image.width}x{image.height} to {width}x{height} failed."
                f" using resize_contain mode as a fallback. Expect boundaries around img"
            )

            color_thief = ColorThief(file)
            (r, g, b) = color_thief.get_color(quality=1)
            color = (r, g, b, 0)
            cover = resizeimage.resize_contain(image, [width, height], bg_color=color)
            image_export = True
            _LOGGER.warning(
                f"using image boundary color {color}, exporting image for visual inspection."
            )

        _LOGGER.debug("resizing done")

        cover = cover.convert("RGB")
        with io.BytesIO() as f:
            cover.save(f, img_format)
            scaled = f.getvalue()

        if image_export:
            name = strftime(
                "postcard_creator_export_%Y-%m-%d_%H-%M-%S_cover.jpg", gmtime()
            )
            path = os.path.join(_get_trace_postcard_sent_dir(), name)
            _LOGGER.info("exporting image to {} (image_export=True)".format(path))
            cover.save(path)

    return scaled


def create_text_image(text: str, image_export: bool = False, **kwargs: Any) -> bytes:
    """
    Create a jpg with given text and return in bytes format
    """
    text_canvas_w = 720
    text_canvas_h = 744
    text_canvas_bg = "white"
    text_canvas_fg = "black"
    text_canvas_font_name = "open_sans_emoji.ttf"

    def load_font(size: int):
        with importlib.resources.as_file(
            importlib.resources.files("postcard_creator").joinpath(
                text_canvas_font_name
            )
        ) as font_path:
            return ImageFont.truetype(str(font_path), size)

    def find_optimal_size(
        msg: str,
        min_size: int = 20,
        max_size: int = 400,
        min_line_w: int = 1,
        max_line_w: int = 80,
        padding: int = 0,
    ):
        """
        Find optimal font size and line width for a given text
        """

        if min_line_w >= max_line_w:
            raise Exception("illegal arguments, min_line_w < max_line_w needed")

        def line_width(font_size: int, line_padding: int = 70) -> int:
            left = min_line_w
            right = max_line_w
            font = load_font(font_size)
            while left < right:
                n = floor((left + right) / 2)
                t = "".join([char * n for char in "1"])
                font_w, _font_h = _get_font_bbox_dim(font, t)
                font_w = font_w + (2 * line_padding)
                if font_w >= text_canvas_w:
                    right = n - 1
                    pass
                else:
                    left = n + 1
                    pass
            return n

        size_l = min_size
        size_r = max_size
        last_line_w = 0
        last_size = 0

        while size_l < size_r:
            size = floor((size_l + size_r) / 2.0)
            last_size = size

            line_w = line_width(size)
            last_line_w = line_w

            lines = []
            for line in msg.splitlines():
                cur_lines = textwrap.wrap(line, width=line_w)
                for cur_line in cur_lines:
                    lines.append(cur_line)

            font = load_font(size)
            total_w, line_h = _get_font_bbox_dim(font, msg)
            tot_height = len(lines) * line_h

            if tot_height + (2 * padding) < text_canvas_h:
                start_y = (text_canvas_h - tot_height) / 2
            else:
                start_y = 0

            if start_y == 0:
                size_r = size - 1
            else:
                # does fit
                size_l = size + 1

        return last_size, last_line_w

    def center_y(lines: Sequence[Any], font_h: int) -> int:
        tot_height = len(lines) * font_h
        if tot_height < text_canvas_h:
            return (text_canvas_h - tot_height) // 2
        else:
            return 0

    size, line_w = find_optimal_size(text, padding=50)
    _LOGGER.debug(f"using font with size: {size}, width: {line_w}")

    font = load_font(size)
    font_w, font_h = _get_font_bbox_dim(font, text)

    lines = []
    for line in text.splitlines():
        cur_lines = textwrap.wrap(line, width=line_w)
        for cur_line in cur_lines:
            lines.append(cur_line)
    text_y_start = center_y(lines, font_h)

    canvas = Image.new("RGB", (text_canvas_w, text_canvas_h), text_canvas_bg)
    draw = ImageDraw.Draw(canvas)
    for line in lines:
        width, height = _get_font_bbox_dim(font, line)
        draw.text(
            ((text_canvas_w - width) // 2, text_y_start),
            line,
            font=font,
            fill=text_canvas_fg,
            embedded_color=True,
        )
        text_y_start += height

    if image_export:
        name = strftime("postcard_creator_export_%Y-%m-%d_%H-%M-%S_text.jpg", gmtime())
        path = os.path.join(_get_trace_postcard_sent_dir(), name)
        _LOGGER.info("exporting image to {} (image_export=True)".format(path))
        canvas.save(path)

    img_byte_arr = io.BytesIO()
    canvas.save(img_byte_arr, format="jpeg")
    return img_byte_arr.getvalue()


def _get_font_bbox_dim(font: ImageFont.FreeTypeFont, text: str) -> tuple[float, float]:
    left, top, right, bottom = font.getbbox(text)
    return (right - left, bottom - top)
