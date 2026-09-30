from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.formatting.rule import FormulaRule
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo


DETAIL_HEADERS = [
    "模型厂商",
    "高管/来源",
    "职位",
    "日期",
    "来源类型",
    "原文标题",
    "高管发言/博客链接",
    "核心观点",
    "技术标签",
    "AI未来模型动向分析",
    "证据等级",
    "置信度",
    "时间窗口",
    "来源等级",
    "是否官方",
    "归因状态",
    "证据落地校验",
    "分析方法/模型",
    "抓取时间",
]


def _join_points(values: list[Any]) -> str:
    return "\n".join(f"{index}. {value}" for index, value in enumerate(values, 1))


def _signal_tags(values: list[dict[str, Any]]) -> str:
    tags = [str(item.get("tag", "")).strip() for item in values if str(item.get("tag", "")).strip()]
    return ", ".join(dict.fromkeys(tags))


def _detail_row(item: dict[str, Any]) -> list[Any]:
    people = item.get("people_json") or []
    statements = item.get("attributed_statements_json") or []
    speaker_names = list(dict.fromkeys(str(statement.get("speaker", "")).strip() for statement in statements if str(statement.get("speaker", "")).strip()))
    role_by_name = {str(person.get("name", "")): str(person.get("role", "")) for person in people}
    default_source = item.get("source_name", "")
    if item.get("official") and item.get("source_type") == "search_discovery":
        default_source = f"{item.get('company_name', '')} 官方来源"
    people_name = "、".join(speaker_names) or default_source
    people_role = "、".join(role_by_name.get(name, "待核验") for name in speaker_names)
    published = item.get("published_at")
    try:
        published_value: date | str | None = date.fromisoformat(published) if published else None
    except ValueError:
        published_value = published
    confidence = item.get("confidence")
    confidence_value = float(confidence) if confidence is not None else None
    model = " / ".join(value for value in [item.get("analysis_method"), item.get("model")] if value)
    return [
        item.get("company_name", ""),
        people_name,
        people_role,
        published_value,
        item.get("source_type", ""),
        item.get("title", ""),
        item.get("url", ""),
        _join_points(item.get("core_points_json") or []),
        _signal_tags(item.get("technical_signals_json") or []),
        item.get("trend_summary") or "待分析",
        item.get("evidence_level") or "待分析",
        confidence_value,
        item.get("time_window") or "",
        item.get("tier", ""),
        "是" if item.get("official") else "否",
        item.get("attribution_status", ""),
        "通过" if item.get("grounding_passed") else ("未通过" if item.get("analyzed_at") else "待分析"),
        model or "待分析",
        item.get("fetched_at", ""),
    ]


def export_reports(rows: list[dict[str, Any]], output_dir: Path, prefix: str = "ai_executive_intelligence") -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = output_dir / f"{prefix}_{stamp}"
    detail_rows = [_detail_row(item) for item in rows]
    xlsx_path = base.with_suffix(".xlsx")
    csv_path = base.with_suffix(".csv")
    md_path = base.with_suffix(".md")
    _write_xlsx(xlsx_path, rows, detail_rows)
    _write_csv(csv_path, detail_rows)
    _write_markdown(md_path, detail_rows)
    return {"xlsx": xlsx_path, "csv": csv_path, "markdown": md_path}


def _write_xlsx(path: Path, source_rows: list[dict[str, Any]], detail_rows: list[list[Any]]) -> None:
    workbook = Workbook()
    detail = workbook.active
    detail.title = "情报明细"
    summary = workbook.create_sheet("厂商趋势")
    notes = workbook.create_sheet("说明与口径")

    detail.append(DETAIL_HEADERS)
    for row in detail_rows:
        detail.append(row)
    _style_detail_sheet(detail)

    summary_headers = ["模型厂商", "来源数", "已分析数", "最新日期", "主要技术标签", "最新趋势判断", "平均置信度"]
    summary.append(summary_headers)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in source_rows:
        grouped[str(item.get("company_name", ""))].append(item)
    for company in sorted(grouped):
        items = grouped[company]
        analyzed = [item for item in items if item.get("analyzed_at")]
        dates = [str(item.get("published_at")) for item in items if item.get("published_at")]
        summary_tags = _normalized_summary_tags(analyzed)
        latest_analyzed = _representative_model_signal(analyzed)
        confidences = [float(item["confidence"]) for item in analyzed if item.get("confidence") is not None]
        summary.append(
            [
                company,
                len(items),
                len(analyzed),
                max(dates) if dates else "",
                ", ".join(summary_tags),
                latest_analyzed.get("trend_summary", "待分析"),
                sum(confidences) / len(confidences) if confidences else None,
            ]
        )
    _style_summary_sheet(summary)

    notes_rows = [
        ["字段", "说明"],
        ["范围", "国内外关键模型厂商的第一方博客、研究页面、官方活动、正式演讲及可核验采访。"],
        ["Explicit", "原文明确给出未来计划、承诺或下一步方向。"],
        ["Strong inference", "多个一致信号共同指向某一方向，但原文未直接承诺。"],
        ["Speculative", "仅有单一或模糊信号，必须按低置信度理解。"],
        ["官方团队内容", "官方页面没有明确出现已登记高管姓名，不能视为个人发言。"],
        ["证据落地校验", "分析所引用证据短句能否在抓取原文中找到。失败项应人工复核。"],
        ["限制", "AI未来模型动向为基于公开信号的推断，不是厂商已确认事实；网页抓取也可能受动态渲染、登录或反爬限制。"],
    ]
    for row in notes_rows:
        notes.append(row)
    _style_notes_sheet(notes)

    workbook.save(path)


def _style_header(sheet: Any, width: int) -> None:
    fill = PatternFill("solid", fgColor="1F4E78")
    font = Font(name="Arial", color="FFFFFF", bold=True, size=10)
    for cell in sheet[1][:width]:
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.row_dimensions[1].height = 32
    sheet.sheet_view.showGridLines = False


def _style_detail_sheet(sheet: Any) -> None:
    _style_header(sheet, len(DETAIL_HEADERS))
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    widths = [16, 22, 26, 12, 18, 42, 48, 50, 26, 60, 18, 12, 18, 12, 12, 22, 16, 24, 24]
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(name="Arial", size=10, color="1F2937")
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        row[3].number_format = "yyyy-mm-dd"
        row[11].number_format = "0.0%"
        if row[6].value:
            row[6].hyperlink = str(row[6].value)
            row[6].style = "Hyperlink"
        sheet.row_dimensions[row[0].row].height = 96
    if sheet.max_row >= 2:
        sheet.conditional_formatting.add(
            f"Q2:Q{sheet.max_row}",
            FormulaRule(formula=['$Q2="未通过"'], fill=PatternFill("solid", fgColor="FCE8E6")),
        )
        sheet.conditional_formatting.add(
            f"Q2:Q{sheet.max_row}",
            FormulaRule(formula=['$Q2="通过"'], fill=PatternFill("solid", fgColor="E6F4EA")),
        )
    if sheet.max_row >= 2:
        table = Table(displayName="IntelDetailTable", ref=f"A1:S{sheet.max_row}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showFirstColumn=False, showLastColumn=False, showRowStripes=True, showColumnStripes=False)
        sheet.add_table(table)


def _style_summary_sheet(sheet: Any) -> None:
    _style_header(sheet, 7)
    sheet.freeze_panes = "A2"
    widths = [18, 12, 12, 14, 38, 72, 14]
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(name="Arial", size=10, color="1F2937")
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        row[6].number_format = "0.0%"
        sheet.row_dimensions[row[0].row].height = 60
    if sheet.max_row >= 2:
        table = Table(displayName="CompanyTrendTable", ref=f"A1:G{sheet.max_row}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        sheet.add_table(table)


def _style_notes_sheet(sheet: Any) -> None:
    _style_header(sheet, 2)
    sheet.column_dimensions["A"].width = 24
    sheet.column_dimensions["B"].width = 100
    light_border = Border(bottom=Side(style="thin", color="D9E2F3"))
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(name="Arial", size=10, color="1F2937")
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = light_border
        sheet.row_dimensions[row[0].row].height = 36


def _write_csv(path: Path, rows: list[list[Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(DETAIL_HEADERS)
        for row in rows:
            writer.writerow([value.isoformat() if isinstance(value, date) else value for value in row])


def _write_markdown(path: Path, rows: list[list[Any]]) -> None:
    selected = [0, 1, 3, 6, 7, 9, 10, 11]
    headers = [DETAIL_HEADERS[index] for index in selected]
    lines = ["# AI 模型厂商高管技术情报", "", "| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        values = []
        for index in selected:
            value = row[index]
            if isinstance(value, date):
                value = value.isoformat()
            if isinstance(value, float):
                value = f"{value:.0%}"
            value = str(value or "").replace("\n", "<br>").replace("|", "\\|")
            values.append(value)
        lines.append("| " + " | ".join(values) + " |")
    lines.extend(["", "> AI 未来模型动向是基于公开信号的推断，不是厂商已确认事实。"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


SUMMARY_TAG_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Agent", ("agent", "智能体", "tool use", "工具调用", "computer use")),
    ("Coding", ("coding", "code", "编程", "代码", "软件工程")),
    ("Reasoning", ("reasoning", "推理", "强化学习", "reinforcement")),
    ("Multimodal", ("multimodal", "多模态", "视觉", "vision", "audio", "video")),
    ("Long Context", ("context", "上下文", "长文本")),
    ("Efficiency / Infra", ("efficiency", "inference", "training", "moe", "sparse", "效率", "推理", "训练", "芯片", "服务器", "基础设施")),
    ("Open Source", ("open source", "open-source", "开源", "权重")),
    ("AI for Science", ("science", "scientific", "科学")),
    ("Safety", ("safety", "安全", "governance", "治理")),
    ("World / Embodied", ("world model", "世界模型", "robot", "机器人", "具身")),
]


def _normalized_summary_tags(items: list[dict[str, Any]]) -> list[str]:
    counts: Counter[str] = Counter()
    raw_tags: Counter[str] = Counter()
    for item in items:
        for signal in item.get("technical_signals_json") or []:
            raw = " ".join(str(signal.get(key, "")) for key in ("tag", "description")).casefold()
            tag = str(signal.get("tag", "")).strip()
            if tag:
                raw_tags[tag] += 1
            for label, keywords in SUMMARY_TAG_RULES:
                if any(keyword.casefold() in raw for keyword in keywords):
                    counts[label] += 1
    if counts:
        return [label for label, _ in counts.most_common(6)]
    return [label for label, _ in raw_tags.most_common(6)]


def _representative_model_signal(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {}
    title_keywords = (
        "model", "gpt", "gemini", "qwen", "deepseek", "glm", "seed", "kimi", "minimax",
        "hunyuan", "mimo", "ernie", "agent", "coding", "模型", "智能体", "推理", "多模态",
    )

    def score(item: dict[str, Any]) -> tuple[int, float, str]:
        title = str(item.get("title", "")).casefold()
        technical = sum(1 for keyword in title_keywords if keyword in title)
        return technical, float(item.get("confidence") or 0.0), str(item.get("published_at") or "")

    return max(items, key=score)
