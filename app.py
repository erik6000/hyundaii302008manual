from __future__ import annotations

import io
import re
from pathlib import Path

import fitz
import streamlit as st
from PIL import Image
from pypdf import PdfReader


PDF_PATH = Path(__file__).with_name("Hyundai-i30-FD-2007-2012-factory-service-manual.pdf")
PDF_WEB_URL = "https://github.com/erik6000/hyundaii302008manual/blob/main/Hyundai-i30-FD-2007-2012-factory-service-manual.pdf"

KNOWN_SUFFIX_FIXES = {
    "Components and": "Components and Components Location",
    "Components": "Components and Components Location",
    "Repair": "Repair procedures",
    "Description": "Description and Operation",
    "Com": "Components and Components Location",
}


def normalize_line(text: str) -> str:
    return " ".join(text.replace("\x00", " ").split())


def should_append_continuation(current: str, next_line: str) -> bool:
    if not next_line or next_line.startswith("Page ") or "http://" in next_line.lower():
        return False
    if current.endswith((" and", " >", " Com", " Components", " Repair", " Description", "/")):
        return True
    if next_line in {
        "Components Location",
        "and Components Location",
        "Description and Operation",
        "Repair procedures",
        "ponent Location",
    }:
        return True
    return False


def finalize_heading(heading: str) -> str:
    heading = normalize_line(heading)
    for suffix, replacement in KNOWN_SUFFIX_FIXES.items():
        if heading.endswith(suffix):
            heading = heading[: -len(suffix)] + replacement
            break
    heading = re.sub(r"\s+>", " >", heading)
    heading = heading.replace("> >", ">")
    return heading.strip()


@st.cache_data(show_spinner=False)
def extract_sections(pdf_path: str, section_prefixes: tuple[str, ...]) -> list[dict[str, object]]:
    reader = PdfReader(pdf_path)
    results: list[dict[str, object]] = []
    seen: set[tuple[str, int]] = set()

    for page_number, page in enumerate(reader.pages, start=1):
        lines = [normalize_line(line) for line in (page.extract_text() or "").splitlines()]
        index = 0
        while index < len(lines):
            line = lines[index]
            if not any(line.startswith(f"{prefix} > ") for prefix in section_prefixes):
                index += 1
                continue

            heading = line
            lookahead = index + 1
            while lookahead < len(lines) and should_append_continuation(heading, lines[lookahead]):
                heading += " " + lines[lookahead]
                lookahead += 1

            heading = finalize_heading(heading)
            parts = [part.strip() for part in heading.split(">") if part.strip()]
            if len(parts) >= 2:
                key = (heading, page_number)
                if key not in seen:
                    seen.add(key)
                    results.append({"heading": heading, "parts": parts, "page": page_number})

            index = lookahead

    results.sort(key=lambda item: (int(item["page"]), str(item["heading"])))
    return results


def build_tree(sections: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    root: dict[str, dict[str, object]] = {}
    for section in sections:
        node = root
        for depth, part in enumerate(section["parts"]):
            if part not in node:
                node[part] = {"children": {}, "heading": None}
            if depth == len(section["parts"]) - 1:
                node[part]["heading"] = section["heading"]
            node = node[part]["children"]
    return root


def section_ranges(sections: list[dict[str, object]], total_pages: int) -> list[dict[str, object]]:
    ranged: list[dict[str, object]] = []
    for index, section in enumerate(sections):
        start_page = int(section["page"])
        if index + 1 < len(sections):
            end_page = int(sections[index + 1]["page"]) - 1
        else:
            end_page = total_pages
        ranged.append(
            {
                "heading": section["heading"],
                "parts": section["parts"],
                "start_page": start_page,
                "end_page": max(start_page, end_page),
            }
        )
    return ranged


@st.cache_data(show_spinner=False)
def get_total_pages(pdf_path: str) -> int:
    return len(PdfReader(pdf_path).pages)


@st.cache_data(show_spinner=False)
def render_section_pages(pdf_path: str, start_page: int, end_page: int, zoom: float = 1.6) -> list[tuple[int, bytes]]:
    doc = fitz.open(pdf_path)
    pages: list[tuple[int, bytes]] = []
    for page_number in range(start_page, end_page + 1):
        page = doc.load_page(page_number - 1)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        image = Image.open(io.BytesIO(pix.tobytes("png")))
        output = io.BytesIO()
        image.save(output, format="PNG")
        pages.append((page_number, output.getvalue()))
    return pages


def render_tree(node: dict[str, dict[str, object]], path: list[str] | None = None) -> None:
    path = path or []
    for label, child in node.items():
        current_path = path + [label]
        if child["children"]:
            with st.expander(label, expanded=len(current_path) <= 2):
                if child["heading"]:
                    if st.button(
                        "Open section",
                        key=f"branch-{'-'.join(current_path)}",
                        width="stretch",
                    ):
                        st.session_state.selected_heading = child["heading"]
                render_tree(child["children"], current_path)
        else:
            is_selected = st.session_state.get("selected_heading") == child["heading"]
            label_text = f"{'• ' if is_selected else ''}{label}"
            if st.button(label_text, key=f"leaf-{'-'.join(current_path)}", width="stretch"):
                st.session_state.selected_heading = child["heading"]


st.set_page_config(page_title="Hyundai i30 Service Manual Navigator", layout="wide")

st.title("Hyundai i30 service manual navigator")
st.caption("Träd till vänster. Hela vald sektion till höger i ett scrollbart läsfönster.")

if not PDF_PATH.exists():
    st.error(f"PDF saknas: {PDF_PATH}")
    st.stop()

supported_sections = ("Brake System", "Body Electrical System")
all_sections = extract_sections(str(PDF_PATH), supported_sections)
sections_by_main = {
    section_name: [section for section in all_sections if section["parts"][0] == section_name]
    for section_name in supported_sections
}

if not any(sections_by_main.values()):
    st.error("Inga Brake System- eller Body Electrical System-sektioner hittades i PDF:en.")
    st.stop()

available_main_sections = [name for name, items in sections_by_main.items() if items]
selected_main = st.selectbox("Huvudsektion", options=available_main_sections, index=0)
main_sections = sections_by_main[selected_main]

page_ranges = section_ranges(main_sections, get_total_pages(str(PDF_PATH)))
tree = build_tree(page_ranges)

if "selected_heading" not in st.session_state:
    st.session_state.selected_heading = str(page_ranges[0]["heading"])

search = st.text_input("Filter", placeholder="Till exempel Parking Brake, Audio eller Rear Wiper")
if search:
    visible_ranges = [
        item for item in page_ranges if search.lower() in str(item["heading"]).lower()
    ]
else:
    visible_ranges = page_ranges

if not visible_ranges:
    st.warning("Inga sektioner matchar filtret.")
    st.stop()

visible_tree = build_tree(visible_ranges)
selected = next(
    (item for item in page_ranges if item["heading"] == st.session_state.selected_heading),
    visible_ranges[0],
)
st.session_state.selected_heading = str(selected["heading"])

left_col, right_col = st.columns([1, 3])

with left_col:
    st.markdown("**Navigation**")
    quick_jump_options = [str(item["heading"]) for item in visible_ranges]
    current_index = (
        quick_jump_options.index(str(selected["heading"]))
        if str(selected["heading"]) in quick_jump_options
        else 0
    )
    quick_jump_value = st.selectbox(
        "Quick jump",
        options=quick_jump_options,
        index=current_index,
        key="quick_jump_heading",
    )
    st.session_state.selected_heading = quick_jump_value
    st.divider()
    render_tree(visible_tree)

with right_col:
    st.subheader(str(selected["parts"][-1]))
    st.write(" > ".join(selected["parts"]))
    meta1, meta2, meta3 = st.columns([1, 1, 1])
    with meta1:
        st.metric("Start page", int(selected["start_page"]))
    with meta2:
        st.metric("End page", int(selected["end_page"]))
    with meta3:
        st.metric("Pages", int(selected["end_page"]) - int(selected["start_page"]) + 1)

    st.link_button("Open full PDF in browser", PDF_WEB_URL, use_container_width=True)

    section_images = render_section_pages(
        str(PDF_PATH),
        int(selected["start_page"]),
        int(selected["end_page"]),
    )

    with st.container(height=950):
        for page_number, image_bytes in section_images:
            st.markdown(f"**Page {page_number}**")
            st.image(image_bytes, width="stretch")
