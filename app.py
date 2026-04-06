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
def extract_sections(pdf_path: str, prefix: str) -> list[dict[str, object]]:
    reader = PdfReader(pdf_path)
    results: list[dict[str, object]] = []
    seen: set[tuple[str, int]] = set()
    match_prefix = prefix + " > "

    for page_number, page in enumerate(reader.pages, start=1):
        lines = [normalize_line(line) for line in (page.extract_text() or "").splitlines()]
        index = 0
        while index < len(lines):
            line = lines[index]
            if not line.startswith(match_prefix):
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


def render_tree(
    node: dict[str, dict[str, object]],
    selected_key: str,
    path: list[str] | None = None,
) -> None:
    path = path or []
    for label, child in node.items():
        current_path = path + [label]
        if child["children"]:
            with st.expander(label, expanded=len(current_path) <= 2):
                if child["heading"]:
                    if st.button(
                        "Open section",
                        key=f"branch-{selected_key}-{'-'.join(current_path)}",
                        width="stretch",
                    ):
                        st.session_state[selected_key] = child["heading"]
                render_tree(child["children"], selected_key, current_path)
        else:
            is_selected = st.session_state.get(selected_key) == child["heading"]
            label_text = f"{'• ' if is_selected else ''}{label}"
            if st.button(label_text, key=f"leaf-{selected_key}-{'-'.join(current_path)}", width="stretch"):
                st.session_state[selected_key] = child["heading"]


def render_section_tab(
    prefix: str,
    tab_key: str,
    search_placeholder: str,
    no_sections_msg: str,
) -> None:
    all_sections = extract_sections(str(PDF_PATH), prefix)
    filtered = [s for s in all_sections if s["parts"][0] == prefix]

    if not filtered:
        st.error(no_sections_msg)
        return

    total = get_total_pages(str(PDF_PATH))
    page_ranges = section_ranges(filtered, total)

    selected_key = f"selected_heading_{tab_key}"
    if selected_key not in st.session_state:
        st.session_state[selected_key] = str(page_ranges[0]["heading"])

    search = st.text_input("Filter", placeholder=search_placeholder, key=f"search_{tab_key}")
    if search:
        visible_ranges = [
            item for item in page_ranges if search.lower() in str(item["heading"]).lower()
        ]
    else:
        visible_ranges = page_ranges

    if not visible_ranges:
        st.warning("Inga sektioner matchar filtret.")
        return

    visible_tree = build_tree(visible_ranges)
    selected = next(
        (item for item in page_ranges if item["heading"] == st.session_state[selected_key]),
        visible_ranges[0],
    )
    st.session_state[selected_key] = str(selected["heading"])

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
            key=f"quick_jump_{tab_key}",
        )
        st.session_state[selected_key] = quick_jump_value
        selected = next(
            (item for item in page_ranges if item["heading"] == st.session_state[selected_key]),
            visible_ranges[0],
        )
        st.divider()
        render_tree(visible_tree, selected_key)

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


st.set_page_config(page_title="Hyundai i30 Manual Navigator", layout="wide")

st.title("Hyundai i30 manual navigator")
st.caption("Träd till vänster. Hela vald sektion till höger i ett scrollbart läsfönster.")

if not PDF_PATH.exists():
    st.error(f"PDF saknas: {PDF_PATH}")
    st.stop()

tab_brake, tab_body = st.tabs(["🔧 Brake System", "🚗 Body"])

with tab_brake:
    render_section_tab(
        prefix="Brake System",
        tab_key="brake",
        search_placeholder="Till exempel Parking Brake, ABS eller Rear Disc",
        no_sections_msg="Inga Brake System-sektioner hittades i PDF:en.",
    )

with tab_body:
    render_section_tab(
        prefix="Body",
        tab_key="body",
        search_placeholder="Till exempel Hood, Door, Bumper eller Seat",
        no_sections_msg="Inga Body-sektioner hittades i PDF:en.",
    )
