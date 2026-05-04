import os

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


def register_fonts():

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    noto_font_dir = os.path.join(base_dir, "fonts", "notosans_hk")
    songti_tc_font_dir = os.path.join(base_dir, "fonts", "songti_tc")
    songti_sc_font_dir = os.path.join(base_dir, "fonts", "songti_sc")
    aptos_font_dir = os.path.join(base_dir, "fonts", "aptos")

    # NOTOSANS-HK Register regular font
    noto_regular_font_path = os.path.join(noto_font_dir, "notosans-hk-regular.ttf")
    pdfmetrics.registerFont(TTFont("notosans-hk-regular", noto_regular_font_path))

    # NOTOSANS-HK Register bold font
    noto_bold_font_path = os.path.join(noto_font_dir, "notosans-hk-bold.ttf")
    pdfmetrics.registerFont(TTFont("notosans-hk-bold", noto_bold_font_path))

    # SONGTI-SC Register regular font
    songti_regular_font_path = os.path.join(songti_sc_font_dir, "songti-sc-regular.ttf")
    pdfmetrics.registerFont(TTFont("songti-sc-regular", songti_regular_font_path))

    # SONGTI-SC Register bold font
    songti_bold_font_path = os.path.join(songti_sc_font_dir, "songti-sc-bold.ttf")
    pdfmetrics.registerFont(TTFont("songti-sc-bold", songti_bold_font_path))

    # SONGTI-SC Register light font
    songti_light_font_path = os.path.join(songti_sc_font_dir, "songti-sc-light.ttf")
    pdfmetrics.registerFont(TTFont("songti-sc-light", songti_light_font_path))

    # SONGTI-TC Register regular font
    songti_regular_font_path = os.path.join(songti_tc_font_dir, "songti-tc-regular.ttf")
    pdfmetrics.registerFont(TTFont("songti-tc-regular", songti_regular_font_path))

    # SONGTI-TC Register bold font
    songti_bold_font_path = os.path.join(songti_tc_font_dir, "songti-tc-bold.ttf")
    pdfmetrics.registerFont(TTFont("songti-tc-bold", songti_bold_font_path))

    # SONGTI-TC Register light font
    songti_light_font_path = os.path.join(songti_tc_font_dir, "songti-tc-light.ttf")
    pdfmetrics.registerFont(TTFont("songti-tc-light", songti_light_font_path))

    # APTOS Register font
    aptos_font_path = os.path.join(aptos_font_dir, "Aptos.ttf")
    pdfmetrics.registerFont(TTFont("aptos", aptos_font_path))

    # APTOS Bold font
    aptos_bold_font_path = os.path.join(aptos_font_dir, "Aptos-Bold.ttf")
    pdfmetrics.registerFont(TTFont("aptos-bold", aptos_bold_font_path))

    # APTOS Light font
    aptos_light_font_path = os.path.join(aptos_font_dir, "Aptos-Light.ttf")
    pdfmetrics.registerFont(TTFont("aptos-light", aptos_light_font_path))
