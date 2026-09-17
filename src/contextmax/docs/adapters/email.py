# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""`email-v1`: `.eml` messages and `.mbox` mailboxes with the standard library. Headers become
metadata and a searchable paragraph, the subject the title, the body paragraphs, attachments
references. HTML-only bodies go through the HTML adapter."""

from __future__ import annotations

import email
import email.policy
import re

from contextmax.docs.adapters.common import squash
from contextmax.docs.base import Block, DocumentTree, ExtractionError

MBOX_SEPARATOR = re.compile(rb"^From .*\r?\n", re.M)
MAX_MESSAGES = 2000


class EmailAdapter:
    id = "email-v1"
    version = "1"
    determinism = "intrinsic"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def extract(self, key: str, data: bytes) -> DocumentTree:
        tree = DocumentTree(key=key, adapter=self.id, adapter_version=self.version, determinism=self.determinism)
        if key.lower().endswith(".mbox") or data.startswith(b"From "):
            chunks = [c for c in MBOX_SEPARATOR.split(data) if c.strip()]
            if not chunks:
                raise ExtractionError("empty mailbox")
            if len(chunks) > MAX_MESSAGES:
                tree.notes.append(f"TRUNCATED: first {MAX_MESSAGES} of {len(chunks)} messages")
                chunks = chunks[:MAX_MESSAGES]
            tree.metadata["n_messages"] = len(chunks)
            tree.title = key.rsplit("/", 1)[-1]
            line = 1
            for index, chunk in enumerate(chunks, start=1):
                n_lines = chunk.count(b"\n") + 1
                self._message(tree, key, chunk, line, index)
                line += n_lines + 1
            return tree
        self._message(tree, key, data, 1, None)
        return tree

    def _message(self, tree: DocumentTree, key: str, data: bytes, line: int, index: int | None) -> None:
        try:
            msg = email.message_from_bytes(data, policy=email.policy.default)
        except Exception as exc:
            raise ExtractionError(f"unreadable message: {exc.__class__.__name__}") from exc
        subject = squash(str(msg.get("Subject", "") or "")) or "(no subject)"
        headers = {h: squash(str(msg.get(h, "") or "")) for h in ("From", "To", "Cc", "Date", "Message-ID", "In-Reply-To")}
        headers = {k: v for k, v in headers.items() if v}
        if index is None:
            tree.title = subject
            tree.metadata.update({k.lower(): v for k, v in headers.items()})
        else:
            tree.blocks.append(Block(kind="heading", text=subject, level=1, line=line, end_line=line, extra={"message": index}))
        header_text = "; ".join(f"{k}: {v}" for k, v in headers.items())
        if header_text:
            tree.blocks.append(Block(kind="paragraph", text=header_text, line=line, end_line=line))
        body_line = line + max(1, data[: data.find(b"\r\n\r\n") if b"\r\n\r\n" in data else data.find(b"\n\n")].count(b"\n"))
        body = None
        try:
            body = msg.get_body(preferencelist=("plain", "html"))
        except Exception:
            body = None
        if body is not None:
            try:
                content = body.get_content()
            except Exception:
                content = ""
            if body.get_content_type() == "text/html":
                from contextmax.docs.adapters.html import HtmlAdapter

                sub = HtmlAdapter().extract(key, content.encode("utf-8", "replace"))
                for block in sub.blocks:
                    if block.kind == "title":
                        continue
                    block.line = block.end_line = body_line
                    tree.blocks.append(block)
            else:
                para_no = body_line
                for para in re.split(r"\n\s*\n", content.replace("\r\n", "\n")):
                    text = squash(" ".join(x.strip() for x in para.split("\n")))
                    if text:
                        tree.blocks.append(Block(kind="paragraph", text=text, line=para_no, end_line=para_no))
                    para_no += para.count("\n") + 2
        for part in msg.iter_attachments():
            name = part.get_filename()
            if name:
                tree.blocks.append(Block(kind="link", text=f"attachment: {name}", target=name, line=line, end_line=line,
                                         extra={"attachment": True, "content_type": part.get_content_type()}))
