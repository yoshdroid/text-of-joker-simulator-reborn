from __future__ import annotations

import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .schema import ExcelAbility, ExcelCard, ExcelJoker


SPREADSHEET_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
WORKBOOK_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def load_cardpool_from_xlsx(path: str | Path) -> list[ExcelCard]:
    workbook_path = Path(path)
    with zipfile.ZipFile(workbook_path) as archive:
        shared_strings = _load_shared_strings(archive)
        rows = _load_cardpool_rows(archive, shared_strings)

    if not rows:
        return []

    header = rows[0]
    return [
        _build_card(header, row)
        for row in rows[1:]
        if any(cell != "" for cell in row) and row[: len(header)] != header
    ]


def load_jokers_from_xlsx(path: str | Path) -> list[ExcelJoker]:
    workbook_path = Path(path)
    with zipfile.ZipFile(workbook_path) as archive:
        shared_strings = _load_shared_strings(archive)
        rows = _load_joker_rows(archive, shared_strings)
    if not rows:
        return []
    header = rows[0]
    return [
        _build_joker(header, row)
        for row in rows[1:]
        if any(cell != "" for cell in row) and row[: len(header)] != header
    ]


def _load_cardpool_rows(archive: zipfile.ZipFile, shared_strings: list[str]) -> list[list[str]]:
    required_headers = {"no", "category", "rarity", "color", "name", "cp", "bp", "abilities"}
    for worksheet in _load_worksheets(archive):
        rows = _read_rows(worksheet, shared_strings)
        if rows and required_headers.issubset(set(rows[0])):
            return rows
    return []


def _load_joker_rows(archive: zipfile.ZipFile, shared_strings: list[str]) -> list[list[str]]:
    required_headers = {"no", "JOKER", "name", "cp", "speed", "ability"}
    for worksheet in _load_worksheets(archive):
        rows = _read_rows(worksheet, shared_strings)
        if rows and required_headers.issubset(set(rows[0])):
            return rows
    return []


def _load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(text.text or "" for text in item.iterfind(".//a:t", SPREADSHEET_NS))
        for item in root.findall("a:si", SPREADSHEET_NS)
    ]


def _load_worksheets(archive: zipfile.ZipFile) -> list[ET.Element]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relation_map = {node.attrib["Id"]: node.attrib["Target"] for node in relationships}
    worksheets = []
    for sheet in workbook.find("a:sheets", SPREADSHEET_NS):
        relationship_id = sheet.attrib[f"{{{WORKBOOK_REL_NS}}}id"]
        target = relation_map[relationship_id]
        if not target.startswith("xl/"):
            target = f"xl/{target}"
        worksheets.append(ET.fromstring(archive.read(target)))
    return worksheets


def _read_rows(worksheet: ET.Element, shared_strings: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in worksheet.findall(".//a:sheetData/a:row", SPREADSHEET_NS):
        parsed_cells: dict[int, str] = {}
        for cell in row.findall("a:c", SPREADSHEET_NS):
            cell_ref = cell.attrib.get("r", "")
            column_index = _column_letters_to_index("".join(ch for ch in cell_ref if ch.isalpha()))
            value_node = cell.find("a:v", SPREADSHEET_NS)
            value = "" if value_node is None else value_node.text or ""
            if cell.attrib.get("t") == "s" and value:
                value = shared_strings[int(value)]
            parsed_cells[column_index] = value
        if parsed_cells:
            rows.append([parsed_cells.get(index, "") for index in range(max(parsed_cells) + 1)])
    return rows


def _build_card(header: list[str], row: list[str]) -> ExcelCard:
    data = {key: row[index] if index < len(row) else "" for index, key in enumerate(header)}
    abilities_raw = json.loads(data["abilities"]) if data.get("abilities") else []
    abilities = tuple(
        ExcelAbility(
            name=str(item.get("name", "")),
            text=str(item.get("text", "")),
            raw=item,
        )
        for item in abilities_raw
        if isinstance(item, dict)
    )
    return ExcelCard(
        card_no=data["no"],
        category=data["category"],
        rarity=data["rarity"],
        color=data["color"],
        name=data["name"],
        race="" if data.get("race", "") == "-" else data.get("race", ""),
        cp=_parse_optional_int(data.get("cp", "")),
        bp_by_level=_parse_bp_levels(data.get("bp", "")),
        abilities=abilities,
    )


def _build_joker(header: list[str], row: list[str]) -> ExcelJoker:
    data = {key: row[index] if index < len(row) else "" for index, key in enumerate(header)}
    return ExcelJoker(
        joker_no=data["no"],
        name=data["name"],
        cp=int(data["cp"]),
        speed=int(data["speed"]),
        ability_text=data.get("ability", ""),
    )


def _parse_bp_levels(bp_text: str) -> tuple[int, ...]:
    if not bp_text or bp_text == "-":
        return ()
    return tuple(int(part) for part in bp_text.split("/"))


def _parse_optional_int(value: str) -> int | None:
    if not value or value == "-":
        return None
    return int(value)


def _column_letters_to_index(column_letters: str) -> int:
    index = 0
    for letter in column_letters:
        index = index * 26 + (ord(letter.upper()) - ord("A") + 1)
    return index - 1
