from __future__ import annotations

import hashlib
import json
import re
import time
from collections import OrderedDict
from typing import Any, TypedDict

from astrbot import logger
from astrbot.core.message.components import (
    At,
    AtAll,
    File,
    Forward,
    Image,
    Node,
    Nodes,
    Plain,
    Reply,
    Video,
)
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.utils.string_utils import normalize_and_dedupe_strings

from .image_refs import looks_like_image_file_name
from .settings import SETTINGS, QuotedMessageParserSettings

_FORWARD_PLACEHOLDER_PATTERN = re.compile(
    r"^(?:[\(\[]?[^\]:\)]*[\)\]]?\s*:\s*)?\[(?:forward message|转发消息|合并转发)\]$",
    flags=re.IGNORECASE,
)


class ParsedOneBotPayload(TypedDict):
    text: str | None
    forward_ids: list[str]
    image_refs: list[str]


def _build_parsed_payload(
    text: str | None,
    forward_ids: list[str] | None = None,
    image_refs: list[str] | None = None,
) -> ParsedOneBotPayload:
    return {
        "text": text,
        "forward_ids": forward_ids or [],
        "image_refs": image_refs or [],
    }


def _join_text_parts(parts: list[str]) -> str | None:
    text = "".join(parts).strip()
    return text or None


def _find_first_reply_component(event: AstrMessageEvent) -> Reply | None:
    for comp in event.message_obj.message:
        if isinstance(comp, Reply):
            return comp
    return None


def _is_forward_placeholder_only_text(text: str | None) -> bool:
    if not isinstance(text, str):
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    return all(_FORWARD_PLACEHOLDER_PATTERN.match(line) for line in lines)


def _extract_image_refs_from_component_chain(
    chain: list[Any] | None,
    *,
    depth: int = 0,
    settings: QuotedMessageParserSettings = SETTINGS,
) -> list[str]:
    if not isinstance(chain, list) or depth > settings.max_component_chain_depth:
        return []

    image_refs: list[str] = []
    for seg in chain:
        if isinstance(seg, Image):
            for candidate in (seg.url, seg.file, seg.path):
                if isinstance(candidate, str) and candidate.strip():
                    image_refs.append(candidate.strip())
                    break
        elif isinstance(seg, Reply):
            image_refs.extend(
                _extract_image_refs_from_reply_component(
                    seg,
                    depth=depth + 1,
                    settings=settings,
                )
            )
        elif isinstance(seg, Node):
            image_refs.extend(
                _extract_image_refs_from_component_chain(
                    seg.content,
                    depth=depth + 1,
                    settings=settings,
                )
            )
        elif isinstance(seg, Nodes):
            for node in seg.nodes:
                image_refs.extend(
                    _extract_image_refs_from_component_chain(
                        node.content,
                        depth=depth + 1,
                        settings=settings,
                    )
                )

    return normalize_and_dedupe_strings(image_refs)


def _extract_text_from_component_chain(
    chain: list[Any] | None,
    *,
    depth: int = 0,
    settings: QuotedMessageParserSettings = SETTINGS,
) -> str | None:
    if not isinstance(chain, list) or depth > settings.max_component_chain_depth:
        return None

    parts: list[str] = []
    for seg in chain:
        if isinstance(seg, Plain):
            if seg.text:
                parts.append(seg.text)
        elif isinstance(seg, At):
            if seg.name:
                parts.append(f"@{seg.name}")
            elif seg.qq:
                parts.append(f"@{seg.qq}")
        elif isinstance(seg, AtAll):
            parts.append("@all")
        elif isinstance(seg, Image):
            parts.append("[Image]")
        elif isinstance(seg, Video):
            parts.append("[Video]")
        elif isinstance(seg, File):
            file_name = seg.name or "file"
            parts.append(f"[File:{file_name}]")
        elif isinstance(seg, Forward):
            parts.append("[Forward Message]")
        elif isinstance(seg, Reply):
            nested = _extract_text_from_reply_component(
                seg,
                depth=depth + 1,
                settings=settings,
            )
            if nested:
                parts.append(nested)
        elif isinstance(seg, Node):
            node_sender = seg.name or seg.uin or "Unknown User"
            node_text = _extract_text_from_component_chain(
                seg.content,
                depth=depth + 1,
                settings=settings,
            )
            if node_text:
                parts.append(f"{node_sender}: {node_text}")
        elif isinstance(seg, Nodes):
            for node in seg.nodes:
                node_sender = node.name or node.uin or "Unknown User"
                node_text = _extract_text_from_component_chain(
                    node.content,
                    depth=depth + 1,
                    settings=settings,
                )
                if node_text:
                    parts.append(f"{node_sender}: {node_text}")

    return _join_text_parts(parts)


def _extract_image_refs_from_reply_component(
    reply: Reply,
    *,
    depth: int = 0,
    settings: QuotedMessageParserSettings = SETTINGS,
) -> list[str]:
    for attr in ("chain", "message", "origin", "content"):
        payload = getattr(reply, attr, None)
        image_refs = _extract_image_refs_from_component_chain(
            payload,
            depth=depth,
            settings=settings,
        )
        if image_refs:
            return image_refs
    return []


def _extract_text_from_reply_component(
    reply: Reply,
    *,
    depth: int = 0,
    settings: QuotedMessageParserSettings = SETTINGS,
) -> str | None:
    for attr in ("chain", "message", "origin", "content"):
        payload = getattr(reply, attr, None)
        text = _extract_text_from_component_chain(
            payload,
            depth=depth,
            settings=settings,
        )
        if text:
            return text

    if reply.message_str and reply.message_str.strip():
        return reply.message_str.strip()
    return None


def _unwrap_onebot_data(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def _extract_text_from_multimsg_json(raw_json: str) -> str | None:
    try:
        parsed = json.loads(raw_json)
    except Exception:
        return None

    if not isinstance(parsed, dict):
        return None
    if parsed.get("app") != "com.tencent.multimsg":
        return None
    config = parsed.get("config")
    if not isinstance(config, dict):
        return None
    if config.get("forward") != 1:
        return None

    meta = parsed.get("meta")
    if not isinstance(meta, dict):
        return None
    detail = meta.get("detail")
    if not isinstance(detail, dict):
        return None
    news_items = detail.get("news")
    if not isinstance(news_items, list):
        return None

    texts: list[str] = []
    for item in news_items:
        if not isinstance(item, dict):
            continue
        text_content = item.get("text")
        if not isinstance(text_content, str):
            continue
        cleaned = text_content.strip().replace("[图片]", "").strip()
        if cleaned:
            texts.append(cleaned)

    return "\n".join(texts).strip() or None


# NapCat 展开转发节点时会写入固定的占位 uin，不能当真实 QQ 号展示
_PLACEHOLDER_SENDER_IDS = {"1094950020", "284840486", "0"}


def _node_sender_label(sender: Any, *, show_id: bool = True) -> str:
    if not isinstance(sender, dict):
        sender = {}
    name = (
        sender.get("nickname")
        or sender.get("card")
        or sender.get("user_id")
        or "Unknown User"
    )
    uid = sender.get("user_id")
    if (
        show_id
        and uid
        and str(uid) != str(name)
        and str(uid) not in _PLACEHOLDER_SENDER_IDS
    ):
        return f"{name}({uid})"
    return str(name)


def _escape_xml_attr(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _node_preview_text(raw_content: Any, limit: int = 80) -> str:
    chain = raw_content if isinstance(raw_content, list) else []
    parts: list[str] = []
    for seg in chain:
        if not isinstance(seg, dict):
            continue
        seg_type = seg.get("type")
        seg_data = seg.get("data") if isinstance(seg.get("data"), dict) else {}
        if seg_type in ("text", "plain"):
            value = seg_data.get("text")
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        elif seg_type == "image":
            parts.append("[Image]")
    preview = " ".join(parts).replace("\n", " ").strip()
    return preview[:limit]


def _parse_onebot_segments(
    segments: list[Any],
    *,
    depth: int = 0,
    quoted_map: dict[str, str] | None = None,
    settings: QuotedMessageParserSettings = SETTINGS,
    in_forward: bool = False,
) -> ParsedOneBotPayload:
    text_parts: list[str] = []
    forward_ids: list[str] = []
    image_refs: list[str] = []

    for seg in segments:
        if not isinstance(seg, dict):
            continue

        seg_type = seg.get("type")
        seg_data = seg.get("data", {}) if isinstance(seg.get("data"), dict) else {}

        if seg_type in ("text", "plain"):
            text = seg_data.get("text")
            if isinstance(text, str) and text:
                text_parts.append(text)
        elif seg_type == "reply":
            ref_id = str(seg_data.get("id") or "").strip()
            quoted_text = (quoted_map or {}).get(ref_id)
            if quoted_text:
                text_parts.append(f"[引用 {quoted_text}]")
            elif ref_id:
                text_parts.append("[引用消息]")
        elif seg_type == "at":
            at_name = seg_data.get("name")
            at_qq = str(seg_data.get("qq") or "").strip()
            if at_qq == "all":
                text_parts.append("@全体成员")
            elif at_name and at_qq:
                text_parts.append(f"@{at_name}({at_qq})")
            elif at_name or at_qq:
                text_parts.append(f"@{at_name or at_qq}")
        elif seg_type in ("record", "voice"):
            text_parts.append("[语音]")
        elif seg_type == "face":
            text_parts.append("[表情]")
        elif seg_type == "image":
            text_parts.append("[Image]")
            candidate = seg_data.get("url") or seg_data.get("file")
            if isinstance(candidate, str) and candidate.strip():
                image_refs.append(candidate.strip())
        elif seg_type == "video":
            text_parts.append("[Video]")
        elif seg_type == "file":
            file_name = (
                seg_data.get("name")
                or seg_data.get("file_name")
                or seg_data.get("file")
                or "file"
            )
            text_parts.append(f"[File:{file_name}]")
            candidate_url = seg_data.get("url", "")
            if (
                isinstance(candidate_url, str)
                and candidate_url.strip()
                and looks_like_image_file_name(candidate_url)
            ):
                image_refs.append(candidate_url.strip())
            candidate_file = seg_data.get("file")
            if (
                isinstance(candidate_file, str)
                and candidate_file.strip()
                and looks_like_image_file_name(
                    seg_data.get("name") or seg_data.get("file_name") or candidate_file
                )
            ):
                image_refs.append(candidate_file.strip())
        elif seg_type in ("forward", "forward_msg", "nodes"):
            # get_msg 返回的 forward 段通常已带 content（NapCat 的 GetMsg 解析
            # 恒展开合并转发）。此时若仍按 id 去调 get_forward_msg，反而会因
            # msgId 不在其 LRU 缓存内而失败，丢掉本已拿到的内容。
            nested_nodes = seg_data.get("content")
            if isinstance(nested_nodes, list) and nested_nodes:
                nested_text, nested_forward_ids, nested_images = (
                    _extract_text_forward_ids_and_images_from_forward_nodes(
                        nested_nodes,
                        depth=depth + 1,
                        settings=settings,
                    )
                )
                if nested_text:
                    if not in_forward:
                        # 前后补换行，避免和同一消息链里的文本段粘成一串
                        text_parts.append(f"\n{nested_text}\n")
                    else:
                        # 每层只加一级相对缩进；若按绝对 depth 加，父层会
                        # 在子层已有缩进上再次叠加，越深越歪。
                        prefix = "  "
                        body = "\n".join(
                            f"{prefix}{line}"
                            for line in nested_text.splitlines()
                            if line.strip()
                        )
                        # 用开闭标签而不是缩进表达边界：纯缩进会被模型当成
                        # 同一段对话继续读，分不清转发到哪条结束。
                        text_parts.append(f"<转发>\n{body}\n{prefix}</转发>")
                else:
                    text_parts.append('<转发 内容已省略="层级过深"/>')
                if nested_forward_ids:
                    forward_ids.extend(nested_forward_ids)
                if nested_images:
                    image_refs.extend(nested_images)
            else:
                fid = seg_data.get("id") or seg_data.get("message_id")
                if isinstance(fid, (str, int)) and str(fid):
                    forward_ids.append(str(fid))
        elif seg_type == "json":
            raw_json = seg_data.get("data")
            if isinstance(raw_json, str) and raw_json.strip():
                raw_json = raw_json.replace("&#44;", ",")
                multimsg_text = _extract_text_from_multimsg_json(raw_json)
                if multimsg_text:
                    text_parts.append(multimsg_text)

    return _build_parsed_payload(
        _join_text_parts(text_parts),
        forward_ids,
        normalize_and_dedupe_strings(image_refs),
    )


def _extract_text_forward_ids_and_images_from_forward_nodes(
    nodes: list[Any],
    *,
    depth: int = 0,
    settings: QuotedMessageParserSettings = SETTINGS,
) -> tuple[str | None, list[str], list[str]]:
    if not isinstance(nodes, list) or depth > settings.max_forward_node_depth:
        return None, [], []

    texts: list[str] = []
    forward_ids: list[str] = []
    image_refs: list[str] = []
    indent = ""

    # 同一层里多个发送者共用一个 user_id，说明 NapCat 给的是占位值，展示会误导模型
    sender_ids: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_sender = node.get("sender")
        if isinstance(node_sender, dict) and node_sender.get("user_id"):
            sender_ids.add(str(node_sender.get("user_id")))
    show_sender_id = len(sender_ids) > 1

    # 先建立本层「消息 id → 发送者 + 摘要」映射，引用段才能还原被引用的是哪条
    quoted_map: dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("message_id") or node.get("id")
        if node_id is None:
            continue
        preview = _node_preview_text(node.get("message") or node.get("content"))
        if preview:
            quoted_map[str(node_id)] = (
                f"{_node_sender_label(node.get('sender'), show_id=show_sender_id)}"
                f": {preview}"
            )

    for node in nodes:
        if not isinstance(node, dict):
            continue

        sender_label = _node_sender_label(node.get("sender"), show_id=show_sender_id)

        raw_content = node.get("message") or node.get("content") or []
        chain: list[Any] = []
        if isinstance(raw_content, list):
            chain = raw_content
        elif isinstance(raw_content, str):
            raw_content = raw_content.strip()
            if raw_content:
                try:
                    parsed = json.loads(raw_content)
                except Exception:
                    parsed = None
                if isinstance(parsed, list):
                    chain = parsed
                else:
                    chain = [{"type": "text", "data": {"text": raw_content}}]

        parsed_segments = _parse_onebot_segments(
            chain,
            depth=depth,
            settings=settings,
            quoted_map=quoted_map,
            in_forward=True,
        )
        node_text = parsed_segments["text"]
        node_forward_ids = parsed_segments["forward_ids"]
        node_images = parsed_segments["image_refs"]
        # 语音/表情/@ 等无文本消息若直接跳过，会让对话出现断层，
        # 所以保留发送者并给出占位
        texts.append(f"{indent}{sender_label}: {node_text or '[非文本消息]'}")
        if node_forward_ids:
            forward_ids.extend(node_forward_ids)
        if node_images:
            image_refs.extend(node_images)

    return (
        "\n".join(texts).strip() or None,
        normalize_and_dedupe_strings(forward_ids),
        normalize_and_dedupe_strings(image_refs),
    )


def _consume_forward_log_slot(text: str) -> bool:
    """Return True when the same expanded payload was not logged moments ago.

    AstrBot resolves quoted text and quoted images separately, so the same
    message reaches this parser twice; logging both copies is pure noise.
    """

    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    now = time.monotonic()
    last = _RECENT_FORWARD_LOGS.get(digest)
    _RECENT_FORWARD_LOGS[digest] = now
    _RECENT_FORWARD_LOGS.move_to_end(digest)
    while len(_RECENT_FORWARD_LOGS) > _FORWARD_LOG_LIMIT:
        _RECENT_FORWARD_LOGS.popitem(last=False)
    return last is None or now - last > _FORWARD_LOG_TTL


_RECENT_FORWARD_LOGS: OrderedDict[str, float] = OrderedDict()
_FORWARD_LOG_TTL = 5.0
_FORWARD_LOG_LIMIT = 8


def _parse_onebot_get_msg_payload(
    payload: dict[str, Any],
    *,
    settings: QuotedMessageParserSettings = SETTINGS,
) -> ParsedOneBotPayload:
    data = _unwrap_onebot_data(payload)
    segments = data.get("message") or data.get("messages")
    if isinstance(segments, list):
        parsed = _parse_onebot_segments(segments, settings=settings)
        text = parsed["text"]
        has_forward = any(
            isinstance(seg, dict)
            and seg.get("type") in ("forward", "forward_msg", "nodes")
            for seg in segments
        )
        if text and has_forward:
            origin = _node_sender_label(data.get("sender"))
            text = (
                f'<合并转发 发起者="{_escape_xml_attr(origin)}">\n'
                f"{text.strip()}\n"
                f"</合并转发>"
            )
            # 便于现场核对展开结果；只在引用到转发时触发，需将日志级别调到 DEBUG。
            # 文本与图片两次解析会命中同一内容，这里只记录真正注入给 agent 的那一份。
            if _consume_forward_log_slot(text):
                logger.debug("[转发展开] 字符数=%d\n%s", len(text), text)
        return _build_parsed_payload(text, parsed["forward_ids"], parsed["image_refs"])

    text: str | None = None
    if isinstance(segments, str) and segments.strip():
        text = segments.strip()
    else:
        raw = data.get("raw_message")
        if isinstance(raw, str) and raw.strip():
            text = raw.strip()
    return _build_parsed_payload(text)


def _parse_onebot_get_forward_payload(
    payload: dict[str, Any],
    *,
    settings: QuotedMessageParserSettings = SETTINGS,
) -> ParsedOneBotPayload:
    data = _unwrap_onebot_data(payload)
    nodes = (
        data.get("messages")
        or data.get("message")
        or data.get("nodes")
        or data.get("nodeList")
    )
    if not isinstance(nodes, list):
        return _build_parsed_payload(None)

    text, forward_ids, image_refs = (
        _extract_text_forward_ids_and_images_from_forward_nodes(
            nodes,
            settings=settings,
        )
    )
    return _build_parsed_payload(text, forward_ids, image_refs)


class ReplyChainParser:
    def __init__(self, settings: QuotedMessageParserSettings = SETTINGS):
        self._settings = settings

    @staticmethod
    def find_first_reply_component(event: AstrMessageEvent) -> Reply | None:
        return _find_first_reply_component(event)

    @staticmethod
    def is_forward_placeholder_only_text(text: str | None) -> bool:
        return _is_forward_placeholder_only_text(text)

    def extract_text_from_reply_component(
        self,
        reply: Reply,
        *,
        depth: int = 0,
    ) -> str | None:
        return _extract_text_from_reply_component(
            reply,
            depth=depth,
            settings=self._settings,
        )

    def extract_image_refs_from_reply_component(
        self,
        reply: Reply,
        *,
        depth: int = 0,
    ) -> list[str]:
        return _extract_image_refs_from_reply_component(
            reply,
            depth=depth,
            settings=self._settings,
        )


class OneBotPayloadParser:
    def __init__(self, settings: QuotedMessageParserSettings = SETTINGS):
        self._settings = settings

    def parse_get_msg_payload(self, payload: dict[str, Any]) -> ParsedOneBotPayload:
        return _parse_onebot_get_msg_payload(payload, settings=self._settings)

    def parse_get_forward_payload(
        self,
        payload: dict[str, Any],
    ) -> ParsedOneBotPayload:
        return _parse_onebot_get_forward_payload(payload, settings=self._settings)
